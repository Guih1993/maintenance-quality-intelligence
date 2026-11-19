import csv
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import HTTPException
from backend import main, importation as service
from backend.ingestion import importer
from backend.database import connection
from backend.database.models import SCHEMA
import viewer_api


class ImportationTests(unittest.TestCase):
    def setUp(self):
        service._estado.update(situacao='ocioso', mensagem='', resultado=None)

    def wait_finished(self):
        for _ in range(200):
            state = service.status()
            if state['situacao'] != 'importando':
                return state
            time.sleep(.01)
        self.fail('Importacao nao terminou')

    def test_imports_temporary_csv_and_updates_existing_order(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as tmp:
            db = Path(tmp)/'test.db'
            csv_path = Path(tmp)/'orders.csv'
            conn = sqlite3.connect(db)
            conn.executescript(SCHEMA)
            conn.close()
            row = dict.fromkeys(importer.COLUNAS, '')
            row.update(FILIAL='DEMO', ORDEM_SERVICO='001', OS_TERMINO='SIM', QTD_TECNICOS='0', QTD_REGISTROS_ORIGEM='1')
            def write_csv():
                with csv_path.open('w', encoding='utf-8-sig', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=importer.COLUNAS)
                    writer.writeheader()
                    writer.writerow(row)
            write_csv()
            real_import = importer.importar_csv
            with patch.object(connection, 'DB_PATH', db), patch.object(service.importer, 'importar_csv', side_effect=lambda: real_import(csv_path)):
                self.assertEqual(service.iniciar()['situacao'], 'importando')
                self.assertEqual(self.wait_finished()['resultado']['novas'],1)
                row['OS_TERMINO']='NAO'
                write_csv()
                service.iniciar()
                self.assertEqual(self.wait_finished()['resultado']['alteradas'],1)
            conn=sqlite3.connect(db)
            self.assertEqual(conn.execute('SELECT termino FROM ordens_servico').fetchone()[0],'NAO')
            conn.close()

    def test_rejects_concurrent_import_and_reports_error(self):
        released = threading.Event()
        def fail():
            released.wait(3)
            raise ValueError('Colunas ausentes: OS_TERMINO')
        with patch.object(service.importer, 'importar_csv', side_effect=fail):
            try:
                self.assertEqual(service.iniciar()['situacao'], 'importando')
                with self.assertRaises(HTTPException) as error:
                    service.iniciar()
                self.assertEqual(error.exception.status_code,409)
            finally:
                released.set()
            state=self.wait_finished()
            self.assertEqual(state['situacao'],'erro')
            self.assertIn('OS_TERMINO',state['mensagem'])

    def test_viewer_has_no_mutating_routes(self):
        self.assertFalse(any('POST' in (getattr(r,'methods',set()) or set()) for r in viewer_api.app.routes))
        self.assertFalse(any(r.path.startswith('/api/importacao') for r in viewer_api.app.routes))


if __name__ == '__main__':
    unittest.main()
