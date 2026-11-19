
import json
from datetime import datetime

from backend.database.connection import get_connection


def salvar_avaliacao(
    os_id: int,
    hash_avaliacao: str,
    avaliacao,
    modelo_ia: str = "qwen3:4b",
    versao_rubrica: str = "3.0",
    versao_prompt: str = "v3",
):
    """
    Salva uma avaliação da qualidade documental.
    Evita duplicidade por OS + hash, independente de modelo/versao.
    """

    dados = avaliacao.model_dump()

    notas = [
        dados["c01_componente"],
        dados["c02_anomalia"],
        dados["c03_causa_evidencia"],
        dados["c04_intervencao"],
        dados["c05_teste"],
        dados["c06_clareza"],
    ]

    score = round(sum(notas) / 12 * 100, 2)

    with get_connection() as conn:
        cursor = conn.execute(
            """
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
            SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            WHERE EXISTS (
                SELECT 1 FROM ordens_servico o
                WHERE o.id = ? AND o.hash_avaliacao = ?
            )
              AND NOT EXISTS (
                SELECT 1 FROM avaliacoes a
                WHERE a.os_id = ? AND a.hash_avaliacao = ?
            )
            """,
            (
                os_id,
                hash_avaliacao,
                versao_rubrica,
                versao_prompt,
                modelo_ia,
                *notas,
                dados["justificativa_na"],
                json.dumps(
                    dados["lacunas_identificadas"],
                    ensure_ascii=False
                ),
                dados["orientacao_treinamento"],
                score,
                json.dumps(dados, ensure_ascii=False),
                datetime.now().isoformat(timespec="seconds"),
                os_id, hash_avaliacao,
                os_id, hash_avaliacao,
            ),
        )

        return {
            "os_id": os_id,
            "score": score,
            "inserida": cursor.rowcount == 1,
        }


def listar_avaliacoes(limite: int = 50):
    """Consulta as avaliações gravadas."""

    with get_connection() as conn:
        registros = conn.execute(
            """
            SELECT
                a.id,
                o.ordem_servico,
                o.tipo_manutencao,
                o.bem_nome,
                a.score_0_100,
                a.avaliado_em,
                a.modelo_ia
            FROM avaliacoes a
            INNER JOIN ordens_servico o
                ON o.id = a.os_id
            ORDER BY a.avaliado_em DESC, a.id DESC
            LIMIT ?
            """,
            (limite,),
        ).fetchall()

        return [dict(registro) for registro in registros]


def contar_avaliacoes():
    """Retorna a quantidade de avaliações armazenadas."""

    with get_connection() as conn:
        resultado = conn.execute(
            "SELECT COUNT(*) FROM avaliacoes"
        ).fetchone()

        return resultado[0]
