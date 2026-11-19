
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.database.connection import get_connection
from backend.ai.evaluator import avaliar_os, buscar_os


QUANTIDADE = 10


def selecionar_ordens(quantidade):
    with get_connection() as conn:
        registros = conn.execute(
            """
            SELECT filial, ordem_servico
            FROM ordens_servico
            WHERE tipo_manutencao IN ('C01', 'C05')
              AND LENGTH(TRIM(observacao_normalizada))
                  BETWEEN 30 AND 1000
              AND UPPER(TRIM(observacao_normalizada))
                  <> 'VAZIO'
            ORDER BY RANDOM()
            LIMIT ?
            """,
            (quantidade,),
        ).fetchall()

    return [(r["filial"], r["ordem_servico"]) for r in registros]


def executar_teste():
    ordens = selecionar_ordens(QUANTIDADE)

    if not ordens:
        raise RuntimeError(
            "Quantidade insuficiente de OS elegíveis."
        )

    resultados = []
    inicio = time.perf_counter()

    print(f"\nIniciando teste de {len(ordens)} OS")

    for indice, (filial, numero_os) in enumerate(ordens, 1):
        print(f"\n{'=' * 60}")
        print(f"AVALIAÇÃO {indice}/{len(ordens)}")
        print(f"{'=' * 60}")

        try:
            avaliacao = avaliar_os(numero_os, filial)

            notas = [
                avaliacao.c01_componente,
                avaliacao.c02_anomalia,
                avaliacao.c03_causa_evidencia,
                avaliacao.c04_intervencao,
                avaliacao.c05_teste,
                avaliacao.c06_clareza,
            ]

            pontos = sum(notas)

            score_provisorio = round(pontos / 12 * 100, 2)

            resultados.append({
                "ordem_servico": numero_os,
                "status": "SUCESSO",
                "notas": notas,
                "score_provisorio": score_provisorio,
                "avaliacao": avaliacao.model_dump(),
                "relato_original": buscar_os(numero_os, filial)["observacao_original"],
            })

            print(
                f"\nScore provisório: "
                f"{score_provisorio:.2f}%"
            )

        except Exception as erro:
            print(f"\nERRO na OS {numero_os}: {erro}")

            resultados.append({
                "ordem_servico": numero_os,
                "status": "ERRO",
                "erro": str(erro),
            })

    duracao = time.perf_counter() - inicio

    saida = ROOT / "data" / "processed"
    saida.mkdir(parents=True, exist_ok=True)

    destino = saida / "teste_lote_10_v2.json"

    destino.write_text(
        json.dumps(
            resultados,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    sucessos = sum(
        r["status"] == "SUCESSO"
        for r in resultados
    )

    print(f"\n{'=' * 60}")
    print("RESUMO DO TESTE")
    print(f"{'=' * 60}")
    print(f"OS selecionadas: {len(ordens)}")
    print(f"Avaliações concluídas: {sucessos}")
    print(f"Erros: {len(ordens) - sucessos}")
    print(f"Tempo total: {duracao:.2f} segundos")
    print(f"Resultados salvos em: {destino}")

if __name__ == "__main__":
    executar_teste()