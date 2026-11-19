"""Publicacao assíncrona, exclusiva da aplicacao principal."""
import logging
from copy import deepcopy
from threading import Lock, Thread

from fastapi import APIRouter, HTTPException
from scripts import publicar_banco

router = APIRouter(prefix="/api/publicacao", tags=["Publicacao"])
logger = logging.getLogger(__name__)
_lock = Lock()
_estado = {"situacao": "ocioso", "mensagem": "", "resultado": None}


def _mensagem_erro(erro):
    if isinstance(erro, PermissionError):
        return "Sem permissão para acessar ou gravar na pasta compartilhada."
    if isinstance(erro, FileNotFoundError):
        return "Banco ou pasta de publicação não encontrado. Verifique o acesso à rede."
    if isinstance(erro, OSError):
        return "Falha de acesso aos arquivos. Verifique a rede, as permissões e o espaço disponível."
    return "Falha na publicação ou na validação dos dados. Consulte o registro técnico do backend."


def _executar():
    try:
        resultado = publicar_banco.publicar()
        logger.info("Publicacao concluida: %s", resultado)
        with _lock:
            _estado.update(situacao="concluido", mensagem="Publicação concluída com sucesso.", resultado=resultado)
    except Exception as erro:
        logger.exception("Falha na publicacao do banco")
        with _lock:
            _estado.update(situacao="erro", mensagem=_mensagem_erro(erro), resultado=None)


@router.post("/iniciar", status_code=202)
def iniciar():
    with _lock:
        if _estado["situacao"] == "publicando":
            raise HTTPException(409, "Já existe uma publicação em andamento.")
        _estado.update(situacao="publicando", mensagem="Preparando e publicando uma cópia consistente dos dados...", resultado=None)
        try:
            Thread(target=_executar, daemon=True, name="publicacao-banco").start()
        except Exception as erro:
            logger.exception("Falha ao iniciar publicacao")
            _estado.update(situacao="erro", mensagem=_mensagem_erro(erro))
            raise HTTPException(500, "Não foi possível iniciar a publicação.") from erro
        return deepcopy(_estado)


@router.get("/status")
def status():
    # Nao mantem o lock durante acesso a rede, que pode ser lento.
    ultima, aviso = None, ""
    try:
        ultima = publicar_banco.ler_ultima_publicacao()
    except Exception as erro:
        logger.warning("Falha ao consultar manifesto: %s", erro, exc_info=True)
        aviso = _mensagem_erro(erro)
    with _lock:
        return {**deepcopy(_estado), "ultima_publicacao": ultima, "aviso_manifesto": aviso}
