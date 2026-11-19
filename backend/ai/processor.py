
import sys
import time
from datetime import datetime

from backend.database.connection import get_connection
from backend.database.repository import salvar_avaliacao
from backend.ai.evaluator import (
    montar_prompt,
    validar_resultado,
    ResultadoAvaliacao,
)
from backend.ai.ollama_client import (
    verificar_ollama,
    gerar_resposta,
)

MODELO = "qwen3:4b"
VERSAO_RUBRICA = "3.0"
VERSAO_PROMPT = "v3"


def buscar_pendentes(limite=10):
    """
    Seleciona OS sem avaliacao para o hash atual,
    independentemente de modelo, prompt ou rubrica.
    """

    with get_connection() as conn:
        registros = conn.execute(
            """
            SELECT o.*
            FROM ordens_servico o
            WHERE o.tipo_manutencao IN ('C01', 'C05')
              AND o.observacao_normalizada IS NOT NULL
              AND LENGTH(TRIM(o.observacao_normalizada)) > 0
              AND UPPER(TRIM(o.observacao_normalizada)) <> 'VAZIO'
              AND o.hash_avaliacao IS NOT NULL

              AND NOT EXISTS (
                  SELECT 1
                  FROM avaliacoes a
                  WHERE a.os_id = o.id
                    AND a.hash_avaliacao = o.hash_avaliacao
              )

            ORDER BY o.data_original DESC, o.id DESC
            LIMIT ?
            """,
            (limite,),
        ).fetchall()

    return [dict(registro) for registro in registros]


def os_ja_avaliada(os_id: int, hash_avaliacao: str) -> bool:
    """Verifica se existe avaliacao para o conteudo atual da OS."""
    with get_connection() as conn:
        linha = conn.execute("""
            SELECT EXISTS (
                SELECT 1
                FROM avaliacoes a
                JOIN ordens_servico o ON o.id = a.os_id
                WHERE o.id = ?
                  AND o.hash_avaliacao = ?
                  AND a.hash_avaliacao = ?
            )
        """, (os_id, hash_avaliacao, hash_avaliacao)).fetchone()
    return bool(linha[0])


def processar_os(os):
    """
    Avalia uma OS e salva o resultado no SQLite.
    """

    numero = os["ordem_servico"]

    print(f"\nAvaliando OS {numero}...")

    inicio = time.perf_counter()

    # Confere novamente antes da chamada cara ao Ollama.
    if os_ja_avaliada(os["id"], os["hash_avaliacao"]):
        print(f"OS {numero} ignorada: ja avaliada para o hash atual.")
        return {"os_id": os["id"], "score": None,
                "inserida": False, "ignorada": True}

    prompt = montar_prompt(os)

    resposta = gerar_resposta(
        prompt,
        formato=ResultadoAvaliacao.model_json_schema(),
    )

    avaliacao = validar_resultado(
        resposta["resposta"]
    )

    resultado = salvar_avaliacao(
        os_id=os["id"],
        hash_avaliacao=os["hash_avaliacao"],
        avaliacao=avaliacao,
        modelo_ia=MODELO,
        versao_rubrica=VERSAO_RUBRICA,
        versao_prompt=VERSAO_PROMPT,
    )

    duracao = time.perf_counter() - inicio

    score_texto = (
        f"{resultado['score']:.2f}%"
        if resultado["score"] is not None else "sem gravacao"
    )
    print(
        f"OS {numero} | Score: {score_texto} | "
        f"Tempo: {duracao:.1f}s | Gravada: {resultado['inserida']}"
    )

    return resultado


def processar_lote(limite=10):
    """
    Executa um lote de avaliações.
    Falhas individuais não interrompem o lote.
    """

    print("=" * 60)
    print("MAINTENANCE QUALITY INTELLIGENCE")
    print("PROCESSAMENTO AUTOMATICO DE OS")
    print("=" * 60)

    verificar_ollama()

    ordens = buscar_pendentes(limite)

    print(f"\nOS pendentes selecionadas: {len(ordens)}")

    sucesso = 0
    erros = 0
    inicio = time.perf_counter()

    for indice, os in enumerate(ordens, start=1):
        print(f"\n[{indice}/{len(ordens)}]")

        try:
            resultado = processar_os(os)

            if resultado["inserida"]:
                sucesso += 1

        except Exception as erro:
            erros += 1

            print(
                f"ERRO na OS {os['ordem_servico']}: "
                f"{erro}"
            )

    duracao = time.perf_counter() - inicio

    print("\n" + "=" * 60)
    print("PROCESSAMENTO FINALIZADO")
    print(f"Avaliacoes gravadas: {sucesso}")
    print(f"Erros: {erros}")
    print(f"Duracao: {duracao:.1f} segundos")
    print("=" * 60)

    return {
        "gravadas": sucesso,
        "erros": erros,
        "duracao_segundos": round(duracao, 2),
        "finalizado_em": datetime.now().isoformat(),
    }


if __name__ == "__main__":
    quantidade = (
        int(sys.argv[1])
        if len(sys.argv) > 1
        else 10
    )

    if quantidade < 1:
        raise ValueError("Quantidade deve ser maior que zero.")

    processar_lote(quantidade)
