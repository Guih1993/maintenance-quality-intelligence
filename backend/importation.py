"""Importacao assíncrona do CSV local, exclusiva da API principal."""
import logging
from copy import deepcopy
from threading import Lock, Thread

from fastapi import APIRouter, HTTPException
from backend.ingestion import importer

router = APIRouter(prefix="/api/importacao", tags=["Importacao"])
logger = logging.getLogger(__name__)
_lock = Lock()
_estado = {"situacao": "ocioso", "mensagem": "", "resultado": None}


def _executar():
    try:
        resultado = importer.importar_csv()
        logger.info("Importacao concluida: %s", resultado)
        with _lock:
            _estado.update(situacao="concluido", mensagem="Importação concluída com sucesso.", resultado=resultado)
    except Exception as erro:
        logger.exception("Falha na importacao do CSV")
        mensagem = (str(erro) if isinstance(erro, ValueError) else
                    "CSV não encontrado em data/incoming/DADOS_EXPORTADOS.csv." if isinstance(erro, FileNotFoundError) else
                    "Falha ao importar. Verifique as permissões, o arquivo CSV e o registro técnico do backend.")
        with _lock:
            _estado.update(situacao="erro", mensagem=mensagem, resultado=None)


@router.post("/iniciar", status_code=202)
def iniciar():
    with _lock:
        if _estado["situacao"] == "importando":
            raise HTTPException(409, "Já existe uma importação em andamento.")
        _estado.update(situacao="importando", mensagem="Importando DADOS_EXPORTADOS.csv...", resultado=None)
        try:
            Thread(target=_executar, daemon=True, name="importacao-csv").start()
        except Exception as erro:
            logger.exception("Falha ao iniciar importacao")
            _estado.update(situacao="erro", mensagem="Não foi possível iniciar a importação.")
            raise HTTPException(500, _estado["mensagem"]) from erro
        return deepcopy(_estado)


@router.get("/status")
def status():
    with _lock:
        return deepcopy(_estado)
