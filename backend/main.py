from backend.dashboard_queries import desempenho_tecnico
from datetime import date
from backend.dashboard_queries import encerramento, opcoes, evolucao_filtrada, ENCERRADA, filtro_periodo, usuario_inicio_sql
from pathlib import Path
from typing import Literal
from fastapi.responses import FileResponse
import json
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from backend.database.connection import get_connection

app = FastAPI(
    title="Maintenance Quality Intelligence",
    version="0.1.0",
    description="API local de qualidade documental da manutenção",
)

from backend.publication import router as publication_router

app.include_router(publication_router)
from backend.importation import router as importation_router
app.include_router(importation_router)

BASE_DIR = Path(__file__).resolve().parents[1]

FRONTEND_DIR = BASE_DIR / "frontend"


@app.get("/dashboard", include_in_schema=False)
def dashboard():
    arquivo = FRONTEND_DIR / "index.html"

    if not arquivo.is_file():
        raise HTTPException(
            status_code=404,
            detail="Arquivo do dashboard não encontrado"
        )

    return FileResponse(arquivo, media_type="text/html")



@app.get("/")
def inicio():
    return {
        "aplicacao": "Maintenance Quality Intelligence",
        "status": "online",
        "documentacao": "/docs",
    }



@app.get("/api/resumo")
def resumo(inicio: date | None = None, fim: date | None = None):
    where, params = filtro_periodo(inicio, fim, DATA_OS_SQL)
    # Mesma regra de selecao utilizada pelo viewer_api.
    join_avaliacao = """
    LEFT JOIN avaliacoes a ON a.id = (
        SELECT MAX(a2.id)
        FROM avaliacoes a2
        WHERE a2.os_id = o.id
          AND a2.hash_avaliacao = o.hash_avaliacao
    )
    """

    score_valido = """
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

    consulta = f"""
        SELECT
            COUNT(a.id) AS os_avaliadas,

            COUNT({score_valido})
                AS avaliacoes_validas,

            ROUND(
                AVG({score_valido}), 2
            ) AS score_medio,

            ROUND(AVG(
                CASE WHEN {score_valido} IS NOT NULL
                THEN a.c01_componente END
            ), 2) AS c01,

            ROUND(AVG(
                CASE WHEN {score_valido} IS NOT NULL
                THEN a.c02_anomalia END
            ), 2) AS c02,

            ROUND(AVG(
                CASE WHEN {score_valido} IS NOT NULL
                THEN a.c03_causa_evidencia END
            ), 2) AS c03,

            ROUND(AVG(
                CASE WHEN {score_valido} IS NOT NULL
                THEN a.c04_intervencao END
            ), 2) AS c04,

            ROUND(AVG(
                CASE WHEN {score_valido} IS NOT NULL
                THEN a.c05_teste END
            ), 2) AS c05,

            ROUND(AVG(
                CASE WHEN {score_valido} IS NOT NULL
                THEN a.c06_clareza END
            ), 2) AS c06

        FROM ordens_servico o
        {join_avaliacao}
        WHERE {where}
    """

    with get_connection() as conn:
        fechamento = encerramento(conn, where, params)
        total_os = conn.execute(
            f"SELECT COUNT(*) FROM ordens_servico o WHERE {where}", params
        ).fetchone()[0]

        total_avaliacoes = conn.execute(
            f"SELECT COUNT(*) FROM avaliacoes a JOIN ordens_servico o ON o.id=a.os_id WHERE {where}", params
        ).fetchone()[0]

        dados = conn.execute(consulta, params).fetchone()

    return {
        **fechamento,
        "total_os_importadas": total_os,
        "total_avaliacoes": total_avaliacoes,
        "os_avaliadas": dados["os_avaliadas"],
        "avaliacoes_validas": dados["avaliacoes_validas"],
        "score_medio": dados["score_medio"],
        "medias_criterios": {
            "C01": dados["c01"],
            "C02": dados["c02"],
            "C03": dados["c03"],
            "C04": dados["c04"],
            "C05": dados["c05"],
            "C06": dados["c06"],
            "avaliacoes_validas": dados["avaliacoes_validas"],
        },
    }



@app.get("/api/avaliacoes")
def listar_avaliacoes(
    limite: int = Query(default=50, ge=1, le=500),
    busca: str = "",
    inicio: date | None = None,
    fim: date | None = None,
):
    where, params = filtro_periodo(inicio, fim, DATA_OS_SQL)
    with get_connection() as conn:
        registros = conn.execute(f"""
            SELECT
                a.id AS avaliacao_id,
                o.ordem_servico,
                o.tipo_manutencao,
                o.bem_codigo,
                o.bem_nome,
                o.area,
                a.score_0_100,
                a.avaliado_em,
                a.modelo_ia
            FROM avaliacoes a
            INNER JOIN ordens_servico o
                ON o.id = a.os_id
            WHERE
                (? = ''
                 OR o.ordem_servico LIKE ?
                 OR o.bem_nome LIKE ?)
            AND {where}
            ORDER BY a.avaliado_em DESC, a.id DESC
            LIMIT ?
        """, (
            busca,
            f"%{busca}%",
            f"%{busca}%",
            *params, limite,
        )).fetchall()

    return [dict(registro) for registro in registros]


@app.get("/api/avaliacoes/{avaliacao_id}")
def detalhe_avaliacao(avaliacao_id: int):
    with get_connection() as conn:
        registro = conn.execute("""
            SELECT
                a.*,
                o.filial,
                o.ordem_servico,
                o.tipo_manutencao,
                o.bem_codigo,
                o.bem_nome,
                o.area,
                o.servico_nome,
                o.observacao_original,
                o.data_original
            FROM avaliacoes a
            INNER JOIN ordens_servico o
                ON o.id = a.os_id
            WHERE a.id = ?
        """, (avaliacao_id,)).fetchone()

        if registro is None:
            raise HTTPException(
                status_code=404,
                detail="Avaliacao nao encontrada",
            )

        dados = dict(registro)

        tecnicos = conn.execute("""
            SELECT t.nome
            FROM tecnicos t
            INNER JOIN os_tecnicos ot
                ON ot.tecnico_id = t.id
            WHERE ot.os_id = ?
            ORDER BY t.nome
        """, (dados["os_id"],)).fetchall()

    dados["tecnicos"] = [t["nome"] for t in tecnicos]

    dados["resposta_json"] = json.loads(
        dados["resposta_json"]
    )

    
    lacunas = dados["lacunas_identificadas"]

    if not lacunas:
        dados["lacunas_identificadas"] = []
    else:
        try:
            valor = json.loads(lacunas)
            dados["lacunas_identificadas"] = (
                valor if isinstance(valor, list) else [str(valor)]
            )
        except (json.JSONDecodeError, TypeError):
            dados["lacunas_identificadas"] = [lacunas]


    return dados


# ==========================================================
# PROCESSAMENTO WEB DE ORDENS DE SERVICO
# ==========================================================

from copy import deepcopy
from datetime import datetime
from threading import Lock, Thread
from uuid import uuid4

from fastapi import HTTPException

from backend.ai.processor import (
    buscar_pendentes,
    processar_os,
)


# Lote controlado para uso no dashboard e demonstracao.
# Altere somente se desejar explicitamente outro tamanho.
QUANTIDADE_LOTE_WEB = -1

_lock_processamento = Lock()

_estado_processamento = {
    "job_id": None,
    "situacao": "ocioso",
    "total": 0,
    "processadas": 0,
    "gravadas": 0,
    "erros": 0,
    "percentual": 0.0,
    "ultima_os": None,
    "os_em_andamento": None,
    "iniciado_em": None,
    "finalizado_em": None,
    "mensagem": "Nenhum processamento iniciado.",
    "detalhes_erros": [],
}


def _agora():
    return datetime.now().isoformat(timespec="seconds")


def _snapshot():
    """
    Retorna uma copia segura do estado atual.
    """
    with _lock_processamento:
        return deepcopy(_estado_processamento)


def _atualizar_estado(**campos):
    """
    Atualiza os indicadores de processamento.
    """
    with _lock_processamento:
        _estado_processamento.update(campos)


def _executar_lote_web(ordens, job_id):
    """
    Worker executado em uma thread separada.

    Cada avaliacao utiliza o fluxo ja validado:
    processar_os -> Qwen3 -> salvar_avaliacao.
    """

    try:
        total = len(ordens)

        for indice, os in enumerate(ordens, start=1):
            with _lock_processamento:
                if _estado_processamento["job_id"] != job_id:
                    return
                if _estado_processamento["situacao"] == "parando":
                    break
                numero_os = os["ordem_servico"]
                _estado_processamento["os_em_andamento"] = numero_os
                _estado_processamento["mensagem"] = f"Classificando OS {numero_os}."


            try:
                resultado = processar_os(os)

                with _lock_processamento:
                    if _estado_processamento["job_id"] != job_id:
                        return

                    if resultado["inserida"]:
                        _estado_processamento["gravadas"] += 1

            except Exception as erro:
                print(
                    f"[PROCESSAMENTO WEB] "
                    f"Erro na OS {numero_os}: {erro}"
                )

                with _lock_processamento:
                    _estado_processamento["erros"] += 1

                    _estado_processamento[
                        "detalhes_erros"
                    ].append({
                        "ordem_servico": numero_os,
                        "erro": str(erro)[:300],
                    })

            finally:
                with _lock_processamento:
                    _estado_processamento["processadas"] = indice
                    _estado_processamento["ultima_os"] = numero_os
                    _estado_processamento["os_em_andamento"] = None

                    _estado_processamento["percentual"] = round(
                        indice / total * 100, 2
                    )

                    _estado_processamento["mensagem"] = (
                        "Parada solicitada. Finalizando a classificacao."
                        if _estado_processamento["situacao"] == "parando"
                        else f"Processadas {indice} de {total} OS."
                    )

        with _lock_processamento:
            erros = _estado_processamento["erros"]

            interrompido = _estado_processamento["situacao"] == "parando"
            _estado_processamento["situacao"] = (
                "parado" if interrompido else
                "concluido_com_erros" if erros else "concluido"
            )

            _estado_processamento["finalizado_em"] = _agora()

            _estado_processamento["mensagem"] = (
                "Classificacao parada. Voce pode iniciar novamente para continuar as pendentes."
                if interrompido else
                "Classificacao finalizada com erros. As OS com falha continuam pendentes."
                if erros else "Todas as OS selecionadas foram processadas."
            )

    except Exception as erro:
        print(f"[PROCESSAMENTO WEB] Erro geral: {erro}")

        with _lock_processamento:
            _estado_processamento["situacao"] = "falha"
            _estado_processamento["finalizado_em"] = _agora()
            _estado_processamento["mensagem"] = (
                "Falha geral no processamento."
            )
            _estado_processamento["detalhes_erros"].append({
                "ordem_servico": None,
                "erro": str(erro)[:300],
            })


@app.post("/api/processamento/iniciar")
def iniciar_processamento():
    """
    Inicia a avaliacao de ate 20 OS pendentes para o hash atual.

    Apenas um lote web pode ser executado
    por vez neste processo FastAPI.
    """

    with _lock_processamento:

        if _estado_processamento["situacao"] in ("executando", "parando"):
            raise HTTPException(
                status_code=409,
                detail="Ja existe um lote em execucao.",
            )

        ordens = buscar_pendentes(QUANTIDADE_LOTE_WEB)

        if not ordens:
            raise HTTPException(
                status_code=409,
                detail="Nao existem OS pendentes para avaliacao.",
            )

        job_id = str(uuid4())

        _estado_processamento.update({
            "job_id": job_id,
            "situacao": "executando",
            "total": len(ordens),
            "processadas": 0,
            "gravadas": 0,
            "erros": 0,
            "percentual": 0.0,
            "ultima_os": None,
            "os_em_andamento": None,
            "iniciado_em": _agora(),
            "finalizado_em": None,
            "mensagem": "Processamento iniciado.",
            "detalhes_erros": [],
        })

    trabalhador = Thread(
        target=_executar_lote_web,
        args=(ordens, job_id),
        daemon=True,
        name=f"avaliacao-{job_id[:8]}",
    )

    try:
        trabalhador.start()
    except Exception as erro:
        _atualizar_estado(
            situacao="falha",
            finalizado_em=_agora(),
            mensagem="Nao foi possivel iniciar o trabalhador.",
        )
        raise HTTPException(
            status_code=500,
            detail="Falha ao iniciar processamento.",
        ) from erro

    return {
        "mensagem": "Processamento iniciado.",
        "job_id": job_id,
        "total": len(ordens),
        "situacao": "executando",
    }


@app.post("/api/processamento/parar")
def parar_processamento():
    """Solicita parada entre OS; preserva a gravacao da OS em andamento."""
    with _lock_processamento:
        if _estado_processamento["situacao"] == "executando":
            _estado_processamento["situacao"] = "parando"
            _estado_processamento["mensagem"] = (
                "Parada solicitada. Aguardando finalizar e salvar a OS em andamento."
            )
        return deepcopy(_estado_processamento)


@app.get("/api/processamento/status")
def consultar_processamento():
    """
    Permite ao HTML acompanhar o lote
    sem interromper a execucao do Qwen3.
    """
    return _snapshot()


# ============================================================
# CONSULTAS GERENCIAIS DO DASHBOARD
# ============================================================

from datetime import date, timedelta
from fastapi import Query

# Compatível com datas ISO e datas brasileiras DD/MM/AAAA.
DATA_OS_SQL = """
CASE
    WHEN o.data_original GLOB '??/??/????*'
    THEN substr(o.data_original, 7, 4) || '-' ||
         substr(o.data_original, 4, 2) || '-' ||
         substr(o.data_original, 1, 2)
    ELSE date(o.data_original)
END
"""

# Retorna apenas a avaliação mais recente de cada OS.
AVALIACAO_ATUAL_SQL = """
LEFT JOIN avaliacoes a ON a.id = (
    SELECT MAX(a2.id)
    FROM avaliacoes a2
    WHERE a2.os_id = o.id
      AND a2.hash_avaliacao = o.hash_avaliacao
)
"""

# Exclui N/A das médias, preservando score zero válido.

SCORE_VALIDO_SQL = """
CASE
    WHEN a.id IS NOT NULL
     AND a.score_0_100 IS NOT NULL
     AND a.c01_componente BETWEEN 0 AND 2
     AND a.c02_anomalia BETWEEN 0 AND 2
     AND a.c03_causa_evidencia BETWEEN 0 AND 2
     AND a.c04_intervencao BETWEEN 0 AND 2
     AND a.c05_teste BETWEEN 0 AND 2
     AND a.c06_clareza BETWEEN 0 AND 2
    THEN a.score_0_100
    ELSE NULL
END
"""


@app.get("/api/evolucao/filtros")
def filtros_evolucao():
    with get_connection() as conn:
        return opcoes(conn)


@app.get("/api/evolucao")
def evolucao_score(
    ano: int = Query(ge=2000, le=2100),
    mes: int | None = Query(default=None, ge=1, le=12),
    setor: str = "",
    tecnicos: list[int] | None = Query(default=None),
):
    with get_connection() as conn:
        return evolucao_filtrada(conn, ano, mes, setor, tecnicos, DATA_OS_SQL, AVALIACAO_ATUAL_SQL, SCORE_VALIDO_SQL)


@app.get("/api/tecnicos-indicadores")
def indicadores_tecnicos(
    busca: str = "",
    limite: int = Query(default=200, ge=1, le=500),
    ordenar: Literal["tecnico", "total_os", "os_avaliadas", "cobertura_percentual", "score_medio", "taxa_encerramento"] = "total_os",
    direcao: Literal["asc", "desc"] = "desc",
    somente_score: bool = False,
    inicio: date | None = None,
    fim: date | None = None,
    minimo_os_score: int = 0,
):
    where, params = filtro_periodo(inicio, fim, DATA_OS_SQL)
    if minimo_os_score < 0:
        raise HTTPException(422, "Minimo de OS deve ser positivo ou zero.")
    campos = {"taxa_encerramento": "taxa_encerramento","tecnico": "t.nome COLLATE NOCASE", "total_os": "total_os",
              "os_avaliadas": "os_avaliadas", "score_medio": "score_medio",
              "cobertura_percentual": "(COUNT(DISTINCT CASE WHEN a.id IS NOT NULL THEN o.id END) * 1.0 / COUNT(DISTINCT o.id))"}
    consulta = f"""
        SELECT
            t.id AS tecnico_id,
            t.nome AS tecnico,

            COUNT(DISTINCT o.id) AS total_os,
                    ROUND(100.0 * COUNT(DISTINCT CASE WHEN {ENCERRADA} THEN o.id END) / NULLIF(COUNT(DISTINCT o.id),0),2) AS taxa_encerramento,

            COUNT(DISTINCT CASE
                WHEN a.id IS NOT NULL
                THEN o.id
            END) AS os_avaliadas,

            COUNT(DISTINCT CASE
                WHEN {SCORE_VALIDO_SQL} IS NOT NULL
                THEN o.id
            END) AS os_com_score,

            ROUND(
                AVG({SCORE_VALIDO_SQL}), 2
            ) AS score_medio

        FROM tecnicos t

        JOIN os_tecnicos ot
            ON ot.tecnico_id = t.id

        JOIN ordens_servico o
            ON o.id = ot.os_id

        {AVALIACAO_ATUAL_SQL}

        WHERE (? = '' OR t.nome LIKE ?) AND {where}

        GROUP BY t.id, t.nome

        HAVING (? = 0 OR COUNT(CASE WHEN {SCORE_VALIDO_SQL} IS NOT NULL THEN 1 END) > 0)
        AND os_com_score >= ?
        ORDER BY {"(score_medio IS NULL)," if ordenar == "score_medio" else ""} {campos[ordenar]} {direcao}, t.nome, t.id

        LIMIT ?
    """

    with get_connection() as conn:
        registros = [
            dict(r)
            for r in conn.execute(
                consulta,
                (busca, f"%{busca}%", *params, int(somente_score), minimo_os_score, limite)
            ).fetchall()
        ]

    for r in registros:
        total = r["total_os"]
        avaliadas = r["os_avaliadas"]

        r["cobertura_percentual"] = (
            round(avaliadas / total * 100, 2)
            if total else 0
        )

        r["os_sem_avaliacao"] = total - avaliadas

        r["os_sem_score"] = (
            avaliadas - r["os_com_score"]
        )

    return registros



@app.get("/api/ordens-periodo")
def ordens_periodo(
    inicio: date,
    fim: date,
    pagina: int = Query(default=1, ge=1),
    limite: int = Query(default=50, ge=1, le=500),
    ordenar: Literal["data_os", "ordem_servico", "descricao", "score_0_100", "tecnicos", "termino", "usuario_inicio"] = "data_os",
    direcao: Literal["asc", "desc"] = "desc",
):
    if inicio > fim:
        raise HTTPException(status_code=422, detail="Data inicial deve ser anterior ou igual a data final.")

    campos = {"usuario_inicio": "usuario_inicio COLLATE NOCASE", "termino": "o.termino","data_os": "data_os", "ordem_servico": "CAST(o.ordem_servico AS INTEGER)",
              "descricao": "COALESCE(NULLIF(o.observacao_original, ''), NULLIF(o.servico_nome, ''), 'Sem descrição') COLLATE NOCASE",
              "score_0_100": "score_0_100", "tecnicos": "tecnicos COLLATE NOCASE"}
    parametros = (inicio.isoformat(), fim.isoformat())
    with get_connection() as conn:
        usuario_sql = usuario_inicio_sql(conn)
        resumo = dict(conn.execute(f"""
            SELECT COUNT(*) AS total,
                   COALESCE(SUM(o.tipo_manutencao = 'C01'), 0) AS c01,
                   COALESCE(SUM(o.tipo_manutencao = 'C05'), 0) AS c05,
                   ROUND(AVG({SCORE_VALIDO_SQL}), 2) AS score_medio
            FROM ordens_servico o
            {AVALIACAO_ATUAL_SQL}
            WHERE {DATA_OS_SQL} BETWEEN ? AND ?
        """, parametros).fetchone())
        resumo.update(encerramento(conn, "{} BETWEEN ? AND ?".format(DATA_OS_SQL), parametros))
        registros = conn.execute(f"""
            SELECT o.id AS os_id, {DATA_OS_SQL} AS data_os,
                   o.ordem_servico, o.termino, {usuario_sql} AS usuario_inicio, o.observacao_original, o.servico_nome,
                   a.id AS avaliacao_id,
                   {SCORE_VALIDO_SQL} AS score_0_100,
                   CASE WHEN a.id IS NULL THEN 'PENDENTE'
                        WHEN {SCORE_VALIDO_SQL} IS NULL THEN 'NAO_APLICAVEL'
                        ELSE 'AVALIADA' END AS status_avaliacao,
                   (SELECT group_concat(nome, ', ') FROM (
                       SELECT DISTINCT t.nome
                       FROM tecnicos t JOIN os_tecnicos ot ON ot.tecnico_id = t.id
                       WHERE ot.os_id = o.id ORDER BY t.nome
                   )) AS tecnicos
            FROM ordens_servico o
            {AVALIACAO_ATUAL_SQL}
            WHERE {DATA_OS_SQL} BETWEEN ? AND ?
            ORDER BY {"(score_0_100 IS NULL)," if ordenar == "score_0_100" else ""} {campos[ordenar]} {direcao}, o.id DESC
            LIMIT ? OFFSET ?
        """, (*parametros, limite, (pagina - 1) * limite)).fetchall()
    return {"total": resumo["total"], "resumo": resumo, "registros": [dict(r) for r in registros]}


@app.get("/api/tecnicos/{tecnico_id}/criterios")
def criterios_tecnico(tecnico_id: int):
    with get_connection() as conn:
        return desempenho_tecnico(conn, tecnico_id, AVALIACAO_ATUAL_SQL, SCORE_VALIDO_SQL)
