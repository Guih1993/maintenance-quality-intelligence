from backend.dashboard_queries import desempenho_tecnico
from datetime import date
from backend.dashboard_queries import encerramento, opcoes, evolucao_filtrada, ENCERRADA, filtro_periodo, usuario_inicio_sql

import json
import os
import sqlite3
import sys

from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse


app = FastAPI(
    title="Maintenance Quality Viewer",
    version="1.0.0",
    description="Visualizador de ordens de serviço - somente leitura",
)


def caminho_frontend():
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "frontend" / "index.html"

    return Path(__file__).resolve().parent / "frontend" / "index.html"


def caminho_banco():
    caminho = os.environ.get("MQI_VIEWER_DB")

    if caminho:
        return Path(caminho).resolve()

    return (
        Path(__file__).resolve().parent
        / "storage"
        / "quality_intelligence.db"
    )


@contextmanager
def conectar():
    banco = caminho_banco()

    if not banco.is_file():
        raise HTTPException(
            status_code=503,
            detail="Banco de consulta nao encontrado.",
        )

    # A conexao nunca permite gravacoes.
    conn = sqlite3.connect(
        banco.as_uri() + "?mode=ro",
        uri=True,
        timeout=30,
    )

    conn.row_factory = sqlite3.Row

    try:
        yield conn
    finally:
        conn.close()


DATA_OS = """
CASE
    WHEN o.data_original GLOB '??/??/????*'
    THEN substr(o.data_original, 7, 4) || '-' ||
         substr(o.data_original, 4, 2) || '-' ||
         substr(o.data_original, 1, 2)
    ELSE date(o.data_original)
END
"""

# Uma unica avaliacao por OS, correspondente ao relato atual.
JOIN_AVALIACAO = """
LEFT JOIN avaliacoes a ON a.id = (
    SELECT MAX(a2.id)
    FROM avaliacoes a2
    WHERE a2.os_id = o.id
      AND a2.hash_avaliacao = o.hash_avaliacao
)
"""

SCORE_VALIDO = """
CASE
    WHEN a.score_0_100 IS NOT NULL
     AND a.c01_componente BETWEEN 0 AND 2
     AND a.c02_anomalia BETWEEN 0 AND 2
     AND a.c03_causa_evidencia BETWEEN 0 AND 2
     AND a.c04_intervencao BETWEEN 0 AND 2
     AND a.c05_teste BETWEEN 0 AND 2
     AND a.c06_clareza BETWEEN 0 AND 2
    THEN a.score_0_100
END
"""


@app.get("/", include_in_schema=False)
@app.get("/dashboard", include_in_schema=False)
def dashboard():
    arquivo = caminho_frontend()

    if not arquivo.is_file():
        raise HTTPException(
            status_code=404,
            detail="Dashboard HTML nao encontrado.",
        )

    html = arquivo.read_text(encoding="utf-8")

    # Mantem os elementos no DOM para compatibilidade
    # com o JavaScript existente, mas oculta os
    # controles de classificacao.
    estilo = """
    <style>
      #painel-processamento,
      #btn-processar,
      #btn-parar {
        display: none !important;
      }
    </style>
    """

    html = html.replace("</head>", estilo + "</head>")

    return HTMLResponse(html)


@app.get("/api/resumo")
def resumo(inicio: date | None = None, fim: date | None = None):
    where, params = filtro_periodo(inicio, fim, DATA_OS)
    with conectar() as conn:
        fechamento = encerramento(conn, where, params)
        total = conn.execute(
            f"SELECT COUNT(*) FROM ordens_servico o WHERE {where}", params
        ).fetchone()[0]

        total_avaliacoes = conn.execute(
            f"SELECT COUNT(*) FROM avaliacoes a JOIN ordens_servico o ON o.id=a.os_id WHERE {where}", params
        ).fetchone()[0]

        consulta = f"""
            SELECT
                COUNT(a.id) AS os_avaliadas,
                COUNT({SCORE_VALIDO}) AS avaliacoes_validas,
                ROUND(AVG({SCORE_VALIDO}), 2) AS score_medio,
                ROUND(AVG(CASE WHEN {SCORE_VALIDO} IS NOT NULL
                    THEN a.c01_componente END), 2) AS c01,
                ROUND(AVG(CASE WHEN {SCORE_VALIDO} IS NOT NULL
                    THEN a.c02_anomalia END), 2) AS c02,
                ROUND(AVG(CASE WHEN {SCORE_VALIDO} IS NOT NULL
                    THEN a.c03_causa_evidencia END), 2) AS c03,
                ROUND(AVG(CASE WHEN {SCORE_VALIDO} IS NOT NULL
                    THEN a.c04_intervencao END), 2) AS c04,
                ROUND(AVG(CASE WHEN {SCORE_VALIDO} IS NOT NULL
                    THEN a.c05_teste END), 2) AS c05,
                ROUND(AVG(CASE WHEN {SCORE_VALIDO} IS NOT NULL
                    THEN a.c06_clareza END), 2) AS c06
            FROM ordens_servico o
            {JOIN_AVALIACAO}
            WHERE {where}
        """

        r = conn.execute(consulta, params).fetchone()

    return {
        **fechamento,
        "total_os_importadas": total,
        "total_avaliacoes": total_avaliacoes,
        "os_avaliadas": r["os_avaliadas"],
        "avaliacoes_validas": r["avaliacoes_validas"],
        "score_medio": r["score_medio"],
        "medias_criterios": {
            f"C{i:02d}": r[f"c{i:02d}"] for i in range(1, 7)
        },
    }


@app.get("/api/avaliacoes")
def listar_avaliacoes(
    limite: int = Query(50, ge=1, le=500),
    busca: str = "",
    inicio: date | None = None,
    fim: date | None = None,
):
    where, params = filtro_periodo(inicio, fim, DATA_OS)
    with conectar() as conn:
        rows = conn.execute(f"""
            SELECT
                a.id AS avaliacao_id,
                o.ordem_servico,
                o.tipo_manutencao,
                o.bem_codigo,
                o.bem_nome,
                o.area,
                {SCORE_VALIDO} AS score_0_100,
                a.avaliado_em,
                a.modelo_ia
            FROM ordens_servico o
            {JOIN_AVALIACAO}
            WHERE a.id IS NOT NULL
              AND (
                  ? = ''
                  OR o.ordem_servico LIKE ?
                  OR o.bem_nome LIKE ?
              )
            AND {where}
            ORDER BY a.id DESC
            LIMIT ?
        """, (
            busca, f"%{busca}%", f"%{busca}%", *params, limite
        )).fetchall()

    return [dict(r) for r in rows]


@app.get("/api/avaliacoes/{avaliacao_id}")
def detalhe_avaliacao(avaliacao_id: int):
    with conectar() as conn:
        row = conn.execute("""
            SELECT a.*, o.filial, o.ordem_servico,
                   o.tipo_manutencao, o.bem_codigo,
                   o.bem_nome, o.area, o.servico_nome,
                   o.observacao_original, o.data_original
            FROM avaliacoes a
            JOIN ordens_servico o ON o.id = a.os_id
            WHERE a.id = ?
        """, (avaliacao_id,)).fetchone()

        if row is None:
            raise HTTPException(
                status_code=404,
                detail="Avaliacao nao encontrada",
            )

        dados = dict(row)

        tecnicos = conn.execute("""
            SELECT DISTINCT t.nome
            FROM tecnicos t
            JOIN os_tecnicos ot ON ot.tecnico_id = t.id
            WHERE ot.os_id = ?
            ORDER BY t.nome
        """, (dados["os_id"],)).fetchall()

    dados["tecnicos"] = [r["nome"] for r in tecnicos]

    try:
        dados["resposta_json"] = json.loads(
            dados["resposta_json"] or "{}"
        )
    except (ValueError, TypeError):
        dados["resposta_json"] = {}

    lacunas = dados["lacunas_identificadas"]

    try:
        valor = json.loads(lacunas or "[]")
    except (ValueError, TypeError):
        valor = lacunas

    if isinstance(valor, list):
        dados["lacunas_identificadas"] = valor
    elif valor:
        dados["lacunas_identificadas"] = [str(valor)]
    else:
        dados["lacunas_identificadas"] = []

    return dados


@app.get("/api/evolucao/filtros")
def filtros_evolucao():
    with conectar() as conn:
        return opcoes(conn)


@app.get("/api/evolucao")
def evolucao(
    ano: int = Query(ge=2000, le=2100),
    mes: int | None = Query(default=None, ge=1, le=12),
    setor: str = "",
    tecnicos: list[int] | None = Query(default=None),
):
    with conectar() as conn:
        return evolucao_filtrada(conn, ano, mes, setor, tecnicos, DATA_OS, JOIN_AVALIACAO, SCORE_VALIDO)


@app.get("/api/ordens-periodo")
def ordens_periodo(
    inicio: date,
    fim: date,
    pagina: int = Query(1, ge=1),
    limite: int = Query(50, ge=1, le=500),
    ordenar: Literal[
        "data_os", "ordem_servico", "descricao",
        "score_0_100", "tecnicos", "termino", "usuario_inicio"
    ] = "data_os",
    direcao: Literal["asc", "desc"] = "desc",
):
    if inicio > fim:
        raise HTTPException(422, "Intervalo de datas invalido.")

    campos = {"usuario_inicio": "usuario_inicio COLLATE NOCASE", "termino": "o.termino",
        "data_os": "data_os",
        "ordem_servico": "CAST(o.ordem_servico AS INTEGER)",
        "descricao": "o.observacao_original COLLATE NOCASE",
        "score_0_100": "score_0_100",
        "tecnicos": "tecnicos COLLATE NOCASE",
    }

    parametros = (inicio.isoformat(), fim.isoformat())

    with conectar() as conn:
        usuario_sql = usuario_inicio_sql(conn)
        resumo = dict(conn.execute(f"""
            SELECT
                COUNT(*) AS total,
                COALESCE(SUM(o.tipo_manutencao = 'C01'), 0) AS c01,
                COALESCE(SUM(o.tipo_manutencao = 'C05'), 0) AS c05,
                ROUND(AVG({SCORE_VALIDO}), 2) AS score_medio
            FROM ordens_servico o
            {JOIN_AVALIACAO}
            WHERE {DATA_OS} BETWEEN ? AND ?
        """, parametros).fetchone())

        resumo.update(encerramento(conn, "{} BETWEEN ? AND ?".format(DATA_OS), parametros))
        rows = conn.execute(f"""
            SELECT
                o.id AS os_id,
                {DATA_OS} AS data_os,
                o.ordem_servico, o.termino, {usuario_sql} AS usuario_inicio,
                o.observacao_original,
                o.servico_nome,
                a.id AS avaliacao_id,
                {SCORE_VALIDO} AS score_0_100,

                CASE
                    WHEN a.id IS NULL THEN 'PENDENTE'
                    WHEN {SCORE_VALIDO} IS NULL
                    THEN 'NAO_APLICAVEL'
                    ELSE 'AVALIADA'
                END AS status_avaliacao,

                (
                    SELECT GROUP_CONCAT(nome, ', ')
                    FROM (
                        SELECT DISTINCT t.nome AS nome
                        FROM tecnicos t
                        JOIN os_tecnicos ot
                          ON ot.tecnico_id = t.id
                        WHERE ot.os_id = o.id
                        ORDER BY t.nome
                    )
                ) AS tecnicos

            FROM ordens_servico o
            {JOIN_AVALIACAO}
            WHERE {DATA_OS} BETWEEN ? AND ?
            ORDER BY
                {"(score_0_100 IS NULL)," if ordenar == "score_0_100" else ""}
                {campos[ordenar]} {direcao}, o.id DESC
            LIMIT ? OFFSET ?
        """, (
            *parametros,
            limite,
            (pagina - 1) * limite,
        )).fetchall()

    return {
        "total": resumo["total"],
        "resumo": resumo,
        "pagina": pagina,
        "limite": limite,
        "registros": [dict(r) for r in rows],
    }


@app.get("/api/tecnicos-indicadores")
def indicadores_tecnicos(
    busca: str = "",
    limite: int = Query(200, ge=1, le=500),
    ordenar: Literal[
        "tecnico", "total_os", "os_avaliadas",
        "cobertura_percentual", "score_medio", "taxa_encerramento"
    ] = "total_os",
    direcao: Literal["asc", "desc"] = "desc",
    somente_score: bool = False,
    inicio: date | None = None,
    fim: date | None = None,
    minimo_os_score: int = 0,
):
    where, params = filtro_periodo(inicio, fim, DATA_OS)
    if minimo_os_score < 0:
        raise HTTPException(422, "Minimo de OS deve ser positivo ou zero.")
    campos = {"taxa_encerramento": "taxa_encerramento",
        "tecnico": "tecnico COLLATE NOCASE",
        "total_os": "total_os",
        "os_avaliadas": "os_avaliadas",
        "cobertura_percentual": "cobertura_percentual",
        "score_medio": "score_medio",
    }

    with conectar() as conn:
        rows = conn.execute(f"""
            WITH indicadores AS (
                SELECT
                    t.id AS tecnico_id,
                    t.nome AS tecnico,
                    COUNT(DISTINCT o.id) AS total_os,
                    ROUND(100.0 * COUNT(DISTINCT CASE WHEN {ENCERRADA} THEN o.id END) / NULLIF(COUNT(DISTINCT o.id),0),2) AS taxa_encerramento,
                    COUNT(DISTINCT CASE WHEN a.id IS NOT NULL
                        THEN o.id END) AS os_avaliadas,
                    COUNT(DISTINCT CASE
                        WHEN {SCORE_VALIDO} IS NOT NULL
                        THEN o.id END) AS os_com_score,
                    ROUND(AVG({SCORE_VALIDO}), 2) AS score_medio
                FROM tecnicos t
                JOIN os_tecnicos ot
                  ON ot.tecnico_id = t.id
                JOIN ordens_servico o
                  ON o.id = ot.os_id
                {JOIN_AVALIACAO}
                WHERE (? = '' OR t.nome LIKE ?) AND {where}
                GROUP BY t.id, t.nome
            )
            SELECT *,
                ROUND(100.0 * os_avaliadas /
                    NULLIF(total_os, 0), 2
                ) AS cobertura_percentual,
                total_os - os_avaliadas AS os_sem_avaliacao,
                os_avaliadas - os_com_score AS os_sem_score
            FROM indicadores
            WHERE (? = 0 OR os_com_score > 0) AND os_com_score >= ?
            ORDER BY
                {campos[ordenar]} IS NULL,
                {campos[ordenar]} {direcao},
                tecnico COLLATE NOCASE
            LIMIT ?
        """, (
            busca,
            f"%{busca}%",
            *params,
            int(somente_score),
            minimo_os_score,
            limite,
        )).fetchall()

    return [dict(r) for r in rows]


# Compatibilidade com o JavaScript de processamento
# existente. Nao existe qualquer endpoint de gravacao.
@app.get("/api/processamento/status")
def status_processamento():
    return {
        "job_id": None,
        "situacao": "ocioso",
        "total": 0,
        "processadas": 0,
        "gravadas": 0,
        "erros": 0,
        "percentual": 0,
        "ultima_os": None,
        "mensagem": "Visualizador somente leitura.",
    }


@app.get("/api/tecnicos/{tecnico_id}/criterios")
def criterios_tecnico(tecnico_id: int):
    with conectar() as conn:
        return desempenho_tecnico(conn, tecnico_id, JOIN_AVALIACAO, SCORE_VALIDO)
