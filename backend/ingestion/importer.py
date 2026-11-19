
import csv
import hashlib
from pathlib import Path

from backend.database.connection import get_connection
from backend.ingestion.normalizer import (
    limpar_texto,
    normalizar_relato,
    normalizar_data,
    gerar_hash_avaliacao,
    separar_tecnicos,
)


ROOT = Path(__file__).resolve().parents[2]
CSV_PATH = ROOT / "data" / "incoming" / "DADOS_EXPORTADOS.csv"

COLUNAS = [
    "FILIAL",
    "ORDEM_SERVICO",
    "OS_DATA_ORIGINAL",
    "OS_SERVICO_TIPO_MANUTENCAO",
    "OS_BEM_CODIGO",
    "OS_BEM_NOME",
    "OS_AREA",
    "OS_SERVICO_NOME",
    "OS_TERMINO",
    "OS_DATA_FIM_MANUTENCAO_REAL",
    "OS_CENTRO_CUSTO_DEPTO",
    "OS_OBSERVACAO",
    "TECNICOS",
    "QTD_TECNICOS",
    "QTD_REGISTROS_ORIGEM",
]

CAMPOS_OS = [
    "data_original",
    "tipo_manutencao",
    "bem_codigo",
    "bem_nome",
    "area",
    "servico_nome",
    "termino",
    "data_fim_real",
    "centro_custo_depto",
    "observacao_original",
    "observacao_normalizada",
    "qtd_registros_origem",
    "hash_avaliacao",
]


def preparar_registro(linha):
    def inteiro(nome, padrao=0):
        valor = limpar_texto(linha[nome])
        return int(valor) if valor else padrao

    registro = {
        "filial": limpar_texto(linha["FILIAL"]),
        "ordem_servico": limpar_texto(
            linha["ORDEM_SERVICO"]
        ),
        "data_original": normalizar_data(
            linha["OS_DATA_ORIGINAL"]
        ),
        "tipo_manutencao": limpar_texto(
            linha["OS_SERVICO_TIPO_MANUTENCAO"]
        ),
        "bem_codigo": limpar_texto(
            linha["OS_BEM_CODIGO"]
        ),
        "bem_nome": limpar_texto(
            linha["OS_BEM_NOME"]
        ),
        "area": limpar_texto(linha["OS_AREA"]),
        "servico_nome": limpar_texto(
            linha["OS_SERVICO_NOME"]
        ),
        "termino": limpar_texto(linha["OS_TERMINO"]),
        "data_fim_real": normalizar_data(
            linha["OS_DATA_FIM_MANUTENCAO_REAL"]
        ),
        "centro_custo_depto": limpar_texto(
            linha["OS_CENTRO_CUSTO_DEPTO"]
        ),
        "observacao_original": (
            linha["OS_OBSERVACAO"] or ""
        ),
        "observacao_normalizada": normalizar_relato(
            linha["OS_OBSERVACAO"]
        ),
        "qtd_registros_origem": inteiro(
            "QTD_REGISTROS_ORIGEM"
        ),
    }

    if not registro["filial"] or not registro["ordem_servico"]:
        raise ValueError("OS sem filial ou identificador")

    registro["hash_avaliacao"] = gerar_hash_avaliacao(
        registro
    )

    if "OS_USUARIO_INICIO" in linha:
        registro["usuario_inicio"] = limpar_texto(linha["OS_USUARIO_INICIO"])

    tecnicos = separar_tecnicos(linha["TECNICOS"])

    if len(tecnicos) != inteiro("QTD_TECNICOS"):
        raise ValueError(
            "Quantidade de técnicos inconsistente: "
            f"OS {registro['ordem_servico']}"
        )

    return registro, tecnicos


def sincronizar_tecnicos(conn, os_id, tecnicos):
    ids = []

    for nome in tecnicos:
        conn.execute(
            "INSERT OR IGNORE INTO tecnicos (nome) VALUES (?)",
            (nome,)
        )

        tecnico = conn.execute(
            "SELECT id FROM tecnicos WHERE nome = ?",
            (nome,)
        ).fetchone()

        ids.append(tecnico["id"])

    existentes = {
        linha["tecnico_id"]
        for linha in conn.execute(
            "SELECT tecnico_id FROM os_tecnicos WHERE os_id = ?",
            (os_id,)
        )
    }

    desejados = set(ids)

    for tecnico_id in existentes - desejados:
        conn.execute(
            """DELETE FROM os_tecnicos
               WHERE os_id = ? AND tecnico_id = ?""",
            (os_id, tecnico_id)
        )

    for tecnico_id in desejados - existentes:
        conn.execute(
            """INSERT INTO os_tecnicos
               (os_id, tecnico_id) VALUES (?, ?)""",
            (os_id, tecnico_id)
        )


def importar_csv(caminho=CSV_PATH):
    caminho = Path(caminho)

    if not caminho.is_file():
        raise FileNotFoundError(
            f"CSV não encontrado: {caminho}"
        )

    hash_arquivo = hashlib.sha256(
        caminho.read_bytes()
    ).hexdigest()

    with caminho.open(
        "r", encoding="utf-8-sig", newline=""
    ) as arquivo:
        leitor = csv.DictReader(
            arquivo, delimiter=","
        )

        if leitor.fieldnames is None:
            raise ValueError("CSV sem cabeçalho")

        faltantes = set(COLUNAS) - set(leitor.fieldnames)

        if faltantes:
            raise ValueError(
                f"Colunas ausentes: {sorted(faltantes)}"
            )

        importar_usuario = "OS_USUARIO_INICIO" in leitor.fieldnames
        campos_os = CAMPOS_OS + (["usuario_inicio"] if importar_usuario else [])
        registros = []
        chaves = set()

        for numero_linha, linha in enumerate(
            leitor, start=2
        ):
            if None in linha:
                raise ValueError(
                    f"Colunas extras na linha {numero_linha}"
                )

            try:
                registro, tecnicos = preparar_registro(linha)
            except (ValueError, TypeError) as erro:
                raise ValueError(
                    f"Linha {numero_linha}: {erro}"
                ) from erro

            chave = (
                registro["filial"],
                registro["ordem_servico"]
            )

            if chave in chaves:
                raise ValueError(
                    f"OS duplicada no CSV: {chave}"
                )

            chaves.add(chave)
            registros.append((registro, tecnicos))

    contadores = {
        "novas": 0,
        "alteradas": 0,
        "inalteradas": 0,
    }

    with get_connection() as conn:
        colunas_banco = {r[1] for r in conn.execute('PRAGMA table_info(ordens_servico)')}
        if importar_usuario and 'usuario_inicio' not in colunas_banco:
            raise ValueError("O CSV possui OS_USUARIO_INICIO, mas o banco ainda precisa da migração usuario_inicio. Execute a migração autorizada antes de importar.")
        cursor = conn.execute(
            """INSERT INTO importacoes
               (nome_arquivo, hash_arquivo, total_linhas)
               VALUES (?, ?, ?)""",
            (caminho.name, hash_arquivo, len(registros))
        )
        importacao_id = cursor.lastrowid

        for registro, tecnicos in registros:
            existente = conn.execute(
                """SELECT * FROM ordens_servico
                   WHERE filial = ? AND ordem_servico = ?""",
                (
                    registro["filial"],
                    registro["ordem_servico"]
                )
            ).fetchone()

            valores = [
                registro[campo] for campo in campos_os
            ]

            if existente is None:
                campos = ["filial", "ordem_servico"] + campos_os
                placeholders = ", ".join("?" for _ in campos)

                cursor = conn.execute(
                    f"""INSERT INTO ordens_servico
                        ({", ".join(campos)})
                        VALUES ({placeholders})""",
                    [
                        registro["filial"],
                        registro["ordem_servico"],
                        *valores
                    ]
                )

                os_id = cursor.lastrowid
                contadores["novas"] += 1

            else:
                os_id = existente["id"]

                mudou = any(
                    existente[campo] != registro[campo]
                    for campo in campos_os
                )

                if mudou:
                    atribuicoes = ", ".join(
                        f"{campo} = ?" for campo in campos_os
                    )

                    conn.execute(
                        f"""UPDATE ordens_servico
                            SET {atribuicoes},
                                atualizado_em = CURRENT_TIMESTAMP
                            WHERE id = ?""",
                        [*valores, os_id]
                    )
                    contadores["alteradas"] += 1
                else:
                    contadores["inalteradas"] += 1

            sincronizar_tecnicos(
                conn, os_id, tecnicos
            )

        conn.execute(
            """UPDATE importacoes
               SET finalizado_em = CURRENT_TIMESTAMP,
                   novas = ?,
                   alteradas = ?,
                   inalteradas = ?,
                   status = 'CONCLUIDO'
               WHERE id = ?""",
            (
                contadores["novas"],
                contadores["alteradas"],
                contadores["inalteradas"],
                importacao_id
            )
        )

    print("\nIMPORTAÇÃO CONCLUÍDA")
    print(f"Arquivo: {caminho.name}")
    print(f"Total de linhas: {len(registros)}")

    for nome, quantidade in contadores.items():
        print(f"{nome.capitalize()}: {quantidade}")

    return contadores


if __name__ == "__main__":
    importar_csv()
