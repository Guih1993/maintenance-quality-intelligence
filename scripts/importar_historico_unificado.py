
import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from backend.database.connection import get_connection

ROOT = Path(__file__).resolve().parents[1]
ARQUIVO = ROOT / "data/incoming/HISTORICO_AVALIACOES.csv"

CAMPOS = {
    "C01_COMPONENTE": "c01_componente",
    "C02_ANOMALIA": "c02_anomalia",
    "C03_CAUSA_EVIDENCIA": "c03_causa_evidencia",
    "C04_INTERVENCAO": "c04_intervencao",
    "C05_TESTE": "c05_teste",
    "C06_CLAREZA": "c06_clareza",
}

ORIGEM = "CSV_HISTORICO"
VERSAO_RUBRICA = "HISTORICA_PESOS_IGUAIS"
VERSAO_PROMPT = "importacao_csv_v1"


def normalizar_texto(valor):
    return re.sub(r"\s+", " ", valor or "").strip().casefold()


def normalizar_numero(valor):
    numero = str(valor or "").strip()
    if numero.isdigit():
        return str(int(numero))
    return numero


def normalizar_filial(valor):
    filial = str(valor or "").strip()
    return filial.zfill(2) if filial.isdigit() else filial


def ler_notas(registro):
    notas = {}

    for coluna, campo in CAMPOS.items():
        valor = (registro.get(coluna) or "").strip().upper()

        if valor == "NA":
            notas[campo] = None
        elif valor in ("0", "1", "2"):
            notas[campo] = int(valor)
        else:
            raise ValueError(
                f"Nota invalida em {coluna}: {valor!r}"
            )

    return notas


def importar(aplicar=False):
    if not ARQUIVO.is_file():
        raise FileNotFoundError(ARQUIVO)

    contadores = {
        "linhas_csv": 0,
        "preparadas": 0,
        "inseridas": 0,
        "ja_avaliadas": 0,
        "sem_vinculo": 0,
        "relato_diferente": 0,
        "invalidas": 0,
        "nao_aplicaveis": 0,
        "conflitos": 0,
    }

    # Mantemos a transacao integral:
    # ou todas as insercoes sao confirmadas,
    # ou nenhuma alteracao e salva.
    with get_connection() as conn:
        ordens = {}

        for os in conn.execute("""
            SELECT
                id,
                filial,
                ordem_servico,
                observacao_original,
                hash_avaliacao
            FROM ordens_servico
        """):
            chave = (
                normalizar_filial(os["filial"]),
                normalizar_numero(os["ordem_servico"]),
            )
            ordens[chave] = dict(os)

        existentes = {
            (r["os_id"], r["hash_avaliacao"])
            for r in conn.execute("""
                SELECT os_id, hash_avaliacao
                FROM avaliacoes
            """)
        }

        vistos = set()

        with ARQUIVO.open(
            "r",
            encoding="utf-8-sig",
            newline=""
        ) as arquivo:

            leitor = csv.DictReader(arquivo, delimiter=";")

            obrigatorias = {
                "FILIAL",
                "ORDEM_SERVICO",
                "OS_OBSERVACAO",
                *CAMPOS.keys(),
            }

            ausentes = obrigatorias - set(
                leitor.fieldnames or []
            )

            if ausentes:
                raise ValueError(
                    f"Colunas ausentes: {sorted(ausentes)}"
                )

            for registro in leitor:
                contadores["linhas_csv"] += 1

                filial = normalizar_filial(
                    registro["FILIAL"]
                )

                numero = normalizar_numero(
                    registro["ORDEM_SERVICO"]
                )

                chave = (filial, numero)

                if chave in vistos:
                    contadores["invalidas"] += 1
                    continue

                vistos.add(chave)

                os = ordens.get(chave)

                if os is None:
                    contadores["sem_vinculo"] += 1
                    continue

                # Nao marcamos uma avaliacao historica
                # como atual quando os relatos diferem.
                relato_csv = normalizar_texto(
                    registro["OS_OBSERVACAO"]
                )

                relato_banco = normalizar_texto(
                    os["observacao_original"]
                )

                if relato_csv != relato_banco:
                    contadores["relato_diferente"] += 1
                    continue

                identidade = (
                    os["id"],
                    os["hash_avaliacao"],
                )

                if identidade in existentes:
                    contadores["ja_avaliadas"] += 1
                    continue

                try:
                    notas = ler_notas(registro)
                except ValueError:
                    contadores["invalidas"] += 1
                    continue

                possui_na = any(
                    nota is None
                    for nota in notas.values()
                )

                justificativa_na = (
                    registro.get("JUSTIFICATIVA_NA") or ""
                ).strip()

                if possui_na and not justificativa_na:
                    contadores["invalidas"] += 1
                    continue

                if possui_na:
                    status = "NAO_APLICAVEL"
                    score = 0.0
                    contadores["nao_aplicaveis"] += 1
                else:
                    status = "AVALIADA"
                    score = round(
                        sum(notas.values()) / 12 * 100,
                        2
                    )

                # O historico nao contem as seis
                # justificativas individuais do Qwen3.
                # Nao inventamos essas informacoes.
                resposta = {
                    **notas,
                    "justificativas": {},
                    "justificativa_na": justificativa_na,
                    "lacunas_identificadas": (
                        registro.get(
                            "LACUNAS_IDENTIFICADAS"
                        ) or ""
                    ),
                    "orientacao_treinamento": (
                        registro.get(
                            "ORIENTACAO_TREINAMENTO"
                        ) or ""
                    ),
                    "status": status,
                    "origem": ORIGEM,
                    "score_historico_csv": (
                        registro.get("SCORE_0_100")
                    ),
                }

                contadores["preparadas"] += 1

                if not aplicar:
                    continue

                cursor = conn.execute("""
                    INSERT OR IGNORE INTO avaliacoes (
                        os_id,
                        hash_avaliacao,
                        versao_rubrica,
                        versao_prompt,
                        modelo_ia,
                        c01_componente,
                        c02_anomalia,
                        c03_causa_evidencia,
                        c04_intervencao,
                        c05_teste,
                        c06_clareza,
                        justificativa_na,
                        lacunas_identificadas,
                        orientacao_treinamento,
                        score_0_100,
                        resposta_json,
                        avaliado_em
                    )
                    VALUES (
                        ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?
                    )
                """, (
                    os["id"],
                    os["hash_avaliacao"],
                    VERSAO_RUBRICA,
                    VERSAO_PROMPT,
                    ORIGEM,
                    *notas.values(),
                    justificativa_na,
                    json.dumps(
                        resposta["lacunas_identificadas"],
                        ensure_ascii=False
                    ),
                    resposta["orientacao_treinamento"],
                    score,
                    json.dumps(
                        resposta,
                        ensure_ascii=False
                    ),
                    datetime.now().isoformat(
                        timespec="seconds"
                    ),
                ))

                if cursor.rowcount == 1:
                    contadores["inseridas"] += 1
                    existentes.add(identidade)
                else:
                    contadores["conflitos"] += 1

        if aplicar:
            conn.commit()

    print("\nRESULTADO DA IMPORTACAO")
    print("Modo:", "GRAVACAO" if aplicar else "SIMULACAO")

    for nome, valor in contadores.items():
        print(f"{nome}: {valor}")

    return contadores


if __name__ == "__main__":
    importar(aplicar="--aplicar" in sys.argv)
