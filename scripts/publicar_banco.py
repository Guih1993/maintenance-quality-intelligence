
import json
import logging
import time
from threading import Lock
import os
import re
import shutil
import sqlite3
import tempfile
import uuid

from contextlib import closing
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

BANCO_ORIGINAL = (
    ROOT / "storage" / "quality_intelligence.db"
)

BASE_PUBLICACAO = ROOT
PASTA_DADOS = Path(os.environ.get("MQI_PUBLICACAO_DIR", BASE_PUBLICACAO / "data" / "publicado")).resolve()
_lock_manifesto = Lock()
logger = logging.getLogger(__name__)


def substituir_manifesto(temporario, destino):
    # Leitores externos/SMB podem impedir brevemente a substituicao.
    # Nao remover nem truncar o manifesto anterior em caso de falha.
    esperas = (0.2, 0.5, 1.0, 2.0)
    for tentativa in range(len(esperas) + 1):
        try:
            with _lock_manifesto:
                os.replace(temporario, destino)
            return
        except PermissionError:
            if tentativa == len(esperas):
                raise
            logger.warning("Manifesto ocupado ou acesso negado; repetindo substituicao (%s/5): %s", tentativa + 1, destino)
            time.sleep(esperas[tentativa])


def ler_ultima_publicacao():
    # Verificar a pasta distingue uma publicacao inexistente de rede indisponivel.
    PASTA_DADOS.stat()
    try:
        with _lock_manifesto:
            texto = (PASTA_DADOS / "versao.json").read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    versao = json.loads(texto)
    if not re.fullmatch(r"quality_[0-9a-f]{12}\.db", versao["arquivo"]):
        raise ValueError("Nome de arquivo invalido no manifesto")
    datetime.fromisoformat(versao["publicado_em"])
    if not isinstance(versao["total_avaliacoes"], int) or versao["total_avaliacoes"] < 0:
        raise ValueError("Quantidade invalida no manifesto")
    return {**versao, "destino": str(PASTA_DADOS / versao["arquivo"])}


def publicar():
    if not BANCO_ORIGINAL.is_file():
        raise FileNotFoundError(
            f"Banco original não encontrado: {BANCO_ORIGINAL}"
        )

    PASTA_DADOS.mkdir(parents=True, exist_ok=True)

    identificador = uuid.uuid4().hex[:12]
    nome_banco = f"quality_{identificador}.db"

    with tempfile.TemporaryDirectory(
        prefix="mqi_publicacao_"
    ) as pasta_temp:

        banco_local = Path(pasta_temp) / nome_banco

        # Cria snapshot consistente, fechando conexões.
        with closing(
            sqlite3.connect(
                BANCO_ORIGINAL.resolve().as_uri() + "?mode=ro",
                uri=True,
                timeout=30
            )
        ) as origem:

            with closing(
                sqlite3.connect(str(banco_local))
            ) as destino:

                origem.backup(destino)

        # Verifica integridade e obtém estatísticas.
        with closing(
            sqlite3.connect(
                banco_local.resolve().as_uri() + "?mode=ro",
                uri=True
            )
        ) as conn:

            integridade = conn.execute(
                "PRAGMA integrity_check"
            ).fetchone()[0]

            if integridade != "ok":
                raise RuntimeError(
                    f"Falha de integridade: {integridade}"
                )

            total = conn.execute(
                "SELECT COUNT(*) FROM avaliacoes"
            ).fetchone()[0]

        # Publica arquivo com nome exclusivo.
        banco_rede = PASTA_DADOS / nome_banco

        shutil.copy2(banco_local, banco_rede)

        # Rele a copia publicada para validar localmente. O SQLite nao precisa
        # interpretar o servidor UNC como autoridade de uma URI file://.
        banco_verificacao = Path(pasta_temp) / "verificacao_rede.db"
        shutil.copy2(banco_rede, banco_verificacao)
        with closing(
            sqlite3.connect(
                banco_verificacao.resolve().as_uri() + "?mode=ro",
                uri=True,
                timeout=30
            )
        ) as conn:

            resultado = conn.execute(
                "PRAGMA quick_check"
            ).fetchone()[0]

            if resultado != "ok":
                raise RuntimeError(
                    f"Falha na cópia da rede: {resultado}"
                )

        versao = {
            "publicado_em": datetime.now().isoformat(
                timespec="seconds"
            ),
            "total_avaliacoes": total,
            "arquivo": nome_banco,
        }

        manifesto_final = PASTA_DADOS / "versao.json"
        manifesto_temp = (
            PASTA_DADOS / f"versao_{identificador}.tmp"
        )

        manifesto_temp.write_text(
            json.dumps(
                versao,
                ensure_ascii=False,
                indent=2
            ),
            encoding="utf-8"
        )

        # Atualiza o manifesto por último.
        substituir_manifesto(manifesto_temp, manifesto_final)

        print("=" * 55)
        print("PUBLICACAO CONCLUIDA")
        print(f"Avaliações: {total}")
        print(f"Banco publicado: {banco_rede}")
        print(f"Manifesto: {manifesto_final}")
        print("=" * 55)

    return {**versao, "destino": str(banco_rede)}


if __name__ == "__main__":
    publicar()
