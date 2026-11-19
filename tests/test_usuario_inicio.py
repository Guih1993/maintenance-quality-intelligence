import csv
import sqlite3
import tempfile
import unittest
from contextlib import closing, contextmanager
from datetime import date
from pathlib import Path
from unittest.mock import patch

from backend.database import connection
from backend.database.models import SCHEMA
from backend.ingestion import importer
from scripts.migrar_usuario_inicio import migrar
import backend.main as main
import viewer_api as viewer


class UsuarioInicioTests(unittest.TestCase):
    def test_migration_import_update_and_legacy_csv(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            db = Path(tmp)/'test.db'
            csv_path = Path(tmp)/'test.csv'
            with closing(sqlite3.connect(db)) as conn:
                conn.executescript(SCHEMA.replace('    usuario_inicio TEXT,\n', ''))
            row = dict.fromkeys(importer.COLUNAS, '')
            row.update(FILIAL='DEMO', ORDEM_SERVICO='001', OS_USUARIO_INICIO=' usuario.demo ', QTD_TECNICOS='0')
            def write_csv():
                with csv_path.open('w',encoding='utf-8-sig',newline='') as f:
                    writer=csv.DictWriter(f,fieldnames=list(row))
                    writer.writeheader()
                    writer.writerow(row)
            write_csv()
            with patch.object(connection,'DB_PATH',db):
                with self.assertRaisesRegex(ValueError,'OS_USUARIO_INICIO'):
                    importer.importar_csv(csv_path)
                backup=migrar(db)
                self.assertTrue(backup.is_file())
                self.assertIsNone(migrar(db))
                self.assertEqual(importer.importar_csv(csv_path)['novas'],1)
                with connection.get_connection() as conn:
                    original_hash=conn.execute('SELECT hash_avaliacao FROM ordens_servico').fetchone()[0]
                row['OS_USUARIO_INICIO']='OutroUsuario'
                write_csv()
                self.assertEqual(importer.importar_csv(csv_path)['alteradas'],1)
                del row['OS_USUARIO_INICIO']
                write_csv()
                self.assertEqual(importer.importar_csv(csv_path)['inalteradas'],1)
                with connection.get_connection() as conn:
                    r=conn.execute('SELECT usuario_inicio,hash_avaliacao FROM ordens_servico').fetchone()
                    self.assertEqual(tuple(r),('OutroUsuario',original_hash))

    def test_both_apis_sort_users_and_support_old_snapshots(self):
        with closing(sqlite3.connect(':memory:')) as conn:
            conn.row_factory=sqlite3.Row
            conn.executescript(SCHEMA)
            conn.executemany("INSERT INTO ordens_servico(filial,ordem_servico,data_original,usuario_inicio) VALUES ('DEMO',?,'2026-11-01',?)",[('1','ZUser'),('2','AUser')])
            @contextmanager
            def connect():
                yield conn
            with patch.object(main,'get_connection',connect),patch.object(viewer,'conectar',connect):
                for api in [main,viewer]:
                    rows=api.ordens_periodo(date(2026,11,1),date(2026,11,30),1,50,'usuario_inicio','asc')['registros']
                    self.assertEqual([r['usuario_inicio'] for r in rows],['AUser','ZUser'])
                conn.execute('ALTER TABLE ordens_servico DROP COLUMN usuario_inicio')
                for api in [main,viewer]:
                    rows=api.ordens_periodo(date(2026,11,1),date(2026,11,30),1,50,'usuario_inicio','desc')['registros']
                    self.assertTrue(all(r['usuario_inicio'] is None for r in rows))


if __name__ == '__main__':
    unittest.main()
