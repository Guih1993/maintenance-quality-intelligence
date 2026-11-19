
SCHEMA = """
CREATE TABLE IF NOT EXISTS ordens_servico (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filial TEXT NOT NULL,
    ordem_servico TEXT NOT NULL,
    data_original TEXT,
    tipo_manutencao TEXT,
    bem_codigo TEXT,
    bem_nome TEXT,
    area TEXT,
    servico_nome TEXT,
    termino TEXT,
    usuario_inicio TEXT,
    data_fim_real TEXT,
    centro_custo_depto TEXT,
    observacao_original TEXT,
    observacao_normalizada TEXT,
    qtd_registros_origem INTEGER,
    hash_avaliacao TEXT,
    atualizado_em TEXT DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(filial, ordem_servico)
);

CREATE TABLE IF NOT EXISTS tecnicos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS os_tecnicos (
    os_id INTEGER NOT NULL,
    tecnico_id INTEGER NOT NULL,

    PRIMARY KEY(os_id, tecnico_id),

    FOREIGN KEY(os_id)
        REFERENCES ordens_servico(id),

    FOREIGN KEY(tecnico_id)
        REFERENCES tecnicos(id)
);

CREATE TABLE IF NOT EXISTS importacoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome_arquivo TEXT NOT NULL,
    hash_arquivo TEXT,
    iniciado_em TEXT DEFAULT CURRENT_TIMESTAMP,
    finalizado_em TEXT,
    total_linhas INTEGER DEFAULT 0,
    novas INTEGER DEFAULT 0,
    alteradas INTEGER DEFAULT 0,
    inalteradas INTEGER DEFAULT 0,
    rejeitadas INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'INICIADO',
    mensagem_erro TEXT
);

CREATE TABLE IF NOT EXISTS avaliacoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    os_id INTEGER NOT NULL,
    hash_avaliacao TEXT NOT NULL,
    versao_rubrica TEXT NOT NULL,
    versao_prompt TEXT NOT NULL,
    modelo_ia TEXT NOT NULL,

    c01_componente INTEGER
        CHECK(c01_componente BETWEEN 0 AND 2),
    c02_anomalia INTEGER,
    c03_causa_evidencia INTEGER,
    c04_intervencao INTEGER,
    c05_teste INTEGER,
    c06_clareza INTEGER,

    justificativa_na TEXT,
    lacunas_identificadas TEXT,
    orientacao_treinamento TEXT,
    score_0_100 REAL
        CHECK(score_0_100 BETWEEN 0 AND 100),

    resposta_json TEXT,
    avaliado_em TEXT DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY(os_id)
        REFERENCES ordens_servico(id),

    UNIQUE(
        os_id, hash_avaliacao,
        versao_rubrica, versao_prompt, modelo_ia
    )
);

CREATE TABLE IF NOT EXISTS processamentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    os_id INTEGER NOT NULL,
    hash_avaliacao TEXT NOT NULL,
    versao_rubrica TEXT NOT NULL,
    versao_prompt TEXT NOT NULL,
    modelo_ia TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDENTE',
    tentativas INTEGER NOT NULL DEFAULT 0,
    iniciado_em TEXT,
    finalizado_em TEXT,
    erro TEXT,

    FOREIGN KEY(os_id)
        REFERENCES ordens_servico(id),

    UNIQUE(
        os_id, hash_avaliacao,
        versao_rubrica, versao_prompt, modelo_ia
    )
);

CREATE INDEX IF NOT EXISTS idx_os_tipo
    ON ordens_servico(tipo_manutencao);

CREATE INDEX IF NOT EXISTS idx_os_data
    ON ordens_servico(data_original);

CREATE INDEX IF NOT EXISTS idx_avaliacoes_os
    ON avaliacoes(os_id);

CREATE INDEX IF NOT EXISTS idx_processamento_status
    ON processamentos(status);
"""
