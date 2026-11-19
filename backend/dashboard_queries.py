from calendar import monthrange
"""Consultas compartilhadas de evolucao e encerramento (somente leitura)."""
ENCERRADA = "UPPER(TRIM(COALESCE(o.termino, ''))) = 'SIM'"
ABERTA = "UPPER(TRIM(COALESCE(o.termino, ''))) IN ('NÃO', 'NAO')"


def encerramento(conn, where="1=1", params=()):
    r = conn.execute(f"""SELECT COUNT(*) AS total,
        COALESCE(SUM({ENCERRADA}),0) AS encerradas,
        COALESCE(SUM({ABERTA}),0) AS abertas
        FROM ordens_servico o WHERE {where}""", params).fetchone()
    return {"taxa_encerramento": round(100*r['encerradas']/r['total'],2) if r['total'] else None,
            "os_encerradas": r['encerradas'], "os_abertas": r['abertas'],
            "os_termino_desconhecido": r['total']-r['encerradas']-r['abertas']}


def opcoes(conn):
    return {"tecnicos": [dict(r) for r in conn.execute('SELECT id,nome FROM tecnicos ORDER BY nome')],
            "setores": [r[0] for r in conn.execute("SELECT DISTINCT area FROM ordens_servico WHERE area IS NOT NULL AND TRIM(area) <> '' ORDER BY area")]}


def evolucao_filtrada(conn, ano, mes, setor, tecnicos, data_sql, join_sql, score_sql):
    ids = sorted(set(tecnicos or []))
    todos = {r[0] for r in conn.execute('SELECT id FROM tecnicos')}
    if set(ids) == todos:
        ids = []
    periodo = f"substr({data_sql},1,{10 if mes is not None else 7})"
    where = [f"substr({data_sql},1,4) = ?"]
    params = [str(ano)]
    if mes is not None:
        where.append(f"substr({data_sql},6,2) = ?")
        params.append(f"{mes:02d}")
    if setor:
        where.append('o.area = ?')
        params.append(setor)
    tecnico_join = ''
    serie = "NULL AS tecnico_id, 'Todos os técnicos' AS tecnico"
    grupo = ''
    if ids:
        tecnico_join = 'JOIN os_tecnicos ot ON ot.os_id=o.id JOIN tecnicos t ON t.id=ot.tecnico_id'
        where.append('t.id IN (' + ','.join('?' for _ in ids) + ')')
        params.extend(ids)
        serie = 't.id AS tecnico_id, t.nome AS tecnico'
        grupo = ', t.id, t.nome'
    rows = [dict(r) for r in conn.execute(f"""
        SELECT {periodo} AS periodo, {serie}, COUNT(a.id) AS avaliacoes,
               COUNT({score_sql}) AS os_com_score, SUM({score_sql}) AS soma_score
        FROM ordens_servico o {join_sql} {tecnico_join}
        WHERE {' AND '.join(where)} GROUP BY {periodo}{grupo}
        ORDER BY periodo, tecnico_id
    """,params)]

    # Media ponderada por OS, acumulada desde o inicio do periodo selecionado.
    series = {}
    for row in rows:
        series.setdefault(row['tecnico_id'], {})[row['periodo']] = row
    periodos = ([f"{ano}-{mes:02d}-{d:02d}" for d in range(1, monthrange(ano, mes)[1]+1)]
                if mes is not None else [f"{ano}-{m:02d}" for m in range(1,13)])
    resultado = []
    for tecnico_id, pontos in series.items():
        soma = 0
        quantidade = 0
        avaliacoes = 0
        nome = next(iter(pontos.values()))['tecnico']
        for periodo in periodos:
            row = pontos.get(periodo)
            if row:
                soma += row['soma_score'] or 0
                quantidade += row['os_com_score']
                avaliacoes += row['avaliacoes']
            if quantidade:
                resultado.append(dict(periodo=periodo, tecnico_id=tecnico_id, tecnico=nome,
                    avaliacoes=avaliacoes, os_com_score=quantidade,
                    score_medio=round(soma/quantidade, 2)))
    return sorted(resultado, key=lambda r: (r['periodo'], r['tecnico_id'] or 0))


def filtro_periodo(inicio, fim, data_sql):
    from fastapi import HTTPException
    if inicio and fim and inicio > fim:
        raise HTTPException(422, "Data inicial deve ser anterior ou igual a data final.")
    clauses, params = [], []
    for value, operator in [(inicio, '>='), (fim, '<=')]:
        if value:
            clauses.append(f"{data_sql} {operator} ?")
            params.append(value.isoformat())
    return ' AND '.join(clauses) or '1=1', params


def usuario_inicio_sql(conn):
    """Mantem a consulta compativel com snapshots anteriores a migracao."""
    campos = {r[1] for r in conn.execute('PRAGMA table_info(ordens_servico)')}
    return 'o.usuario_inicio' if 'usuario_inicio' in campos else 'NULL'


def desempenho_tecnico(conn, tecnico_id, join_sql, score_sql):
    from fastapi import HTTPException
    tecnico = conn.execute('SELECT nome FROM tecnicos WHERE id = ?', (tecnico_id,)).fetchone()
    if tecnico is None:
        raise HTTPException(404, "Tecnico nao encontrado.")
    criterios = ['c01_componente', 'c02_anomalia', 'c03_causa_evidencia',
                 'c04_intervencao', 'c05_teste', 'c06_clareza']
    medias = ', '.join(f'ROUND(AVG(CASE WHEN {score_sql} IS NOT NULL THEN a.{campo} END),2) AS {campo}' for campo in criterios)
    row = conn.execute(f"""
        SELECT COUNT(*) AS total_os, COUNT(a.id) AS os_avaliadas,
               COUNT({score_sql}) AS os_com_score,
               ROUND(AVG({score_sql}),2) AS score_medio, {medias}
        FROM ordens_servico o {join_sql}
        WHERE EXISTS (SELECT 1 FROM os_tecnicos ot WHERE ot.os_id=o.id AND ot.tecnico_id=?)
    """, (tecnico_id,)).fetchone()
    return dict(tecnico_id=tecnico_id, tecnico=tecnico[0], total_os=row['total_os'],
                os_avaliadas=row['os_avaliadas'], os_com_score=row['os_com_score'],
                score_medio=row['score_medio'], medias_criterios={campo:row[campo] for campo in criterios})
