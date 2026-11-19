"""Adiciona usuario_inicio. Executar somente apos autorizacao para migrar o banco."""
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from backend.database.connection import DB_PATH


def migrar(caminho=DB_PATH):
    caminho = Path(caminho).resolve()
    # mode=rw impede criar um banco vazio caso o caminho esteja incorreto.
    with closing(sqlite3.connect(caminho.as_uri() + '?mode=rw', uri=True, timeout=30)) as conn:
        campos = {r[1] for r in conn.execute('PRAGMA table_info(ordens_servico)')}
        if not campos:
            raise ValueError('Tabela ordens_servico nao encontrada.')
        if 'usuario_inicio' in campos:
            return None
        destino = caminho.parent / 'backups'
        destino.mkdir(exist_ok=True)
        backup = destino / f'antes_usuario_inicio_{datetime.now():%Y%m%d_%H%M%S}_{uuid4().hex[:8]}.db'
        with closing(sqlite3.connect(backup)) as copia:
            conn.backup(copia)
            if copia.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('Backup invalido. Migracao cancelada.')
        with conn:
            conn.execute('ALTER TABLE ordens_servico ADD COLUMN usuario_inicio TEXT')
        return backup


if __name__ == '__main__':
    backup = migrar()
    print(f'Migracao concluida. Backup: {backup}' if backup else 'Coluna ja existente; nenhuma alteracao.')
