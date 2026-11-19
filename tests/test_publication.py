import hashlib
import json
import sqlite3
import tempfile
import threading
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import backend.main as main
import backend.publication as service
import viewer_api
from scripts import publicar_banco as publisher


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / 'original.db'
        self.data = self.root / 'data'
        self.data.mkdir()
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute('CREATE TABLE avaliacoes (id INTEGER PRIMARY KEY)')
            conn.execute('INSERT INTO avaliacoes VALUES (1)')
            conn.commit()
        self.patches = [patch.object(publisher, 'BANCO_ORIGINAL', self.db),
                        patch.object(publisher, 'PASTA_DADOS', self.data)]
        for p in self.patches:
            p.start()
        with service._lock:
            service._estado.update(situacao='ocioso', mensagem='', resultado=None)

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def test_network_copy_is_verified_using_local_sqlite_connection(self):
        real_connect = sqlite3.connect
        opened = []
        def connect(path, *args, **kwargs):
            opened.append(str(path))
            return real_connect(path, *args, **kwargs)
        with patch.object(publisher.sqlite3, 'connect', side_effect=connect):
            publisher.publicar()
        self.assertTrue(any('verificacao_rede.db' in path for path in opened))
        self.assertFalse(any(self.data.as_uri() in path for path in opened))

    def test_transient_manifest_lock_retries_without_recopying_database(self):
        real_replace = publisher.os.replace
        calls = []
        def transient(source, target):
            calls.append(1)
            if len(calls) < 3:
                raise PermissionError('temporary lock')
            return real_replace(source, target)
        with patch.object(publisher.os, 'replace', side_effect=transient), patch.object(publisher.time, 'sleep'):
            result = publisher.publicar()
        self.assertEqual(len(calls), 3)
        self.assertEqual(publisher.ler_ultima_publicacao()['arquivo'], result['arquivo'])

    def test_snapshot_manifest_and_closed_connections(self):
        before = hashlib.sha256(self.db.read_bytes()).digest()
        result = publisher.publicar()
        manifest = json.loads((self.data / 'versao.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['arquivo'], result['arquivo'])
        self.assertEqual(manifest['total_avaliacoes'], 1)
        self.assertEqual(publisher.ler_ultima_publicacao(), result)
        self.assertEqual(before, hashlib.sha256(self.db.read_bytes()).digest())
        # On Windows rename/delete also catches leaked SQLite file handles.
        exported = self.data / result['arquivo']
        exported.rename(self.data / 'closed.db')
        self.db.rename(self.root / 'closed-original.db')

    def test_failed_copy_and_manifest_replacement_preserve_last_version(self):
        publisher.publicar()
        old = (self.data / 'versao.json').read_bytes()
        for target in ['shutil.copy2', 'os.replace']:
            with patch('scripts.publicar_banco.' + target, side_effect=PermissionError('simulated')):
                with self.assertRaises(PermissionError):
                    publisher.publicar()
            self.assertEqual((self.data / 'versao.json').read_bytes(), old)

    def test_integrity_failure_preserves_manifest(self):
        publisher.publicar()
        old = (self.data / 'versao.json').read_bytes()
        def corrupt(source, destination):
            Path(destination).write_bytes(b'not a database')
        with patch.object(publisher.shutil, 'copy2', side_effect=corrupt):
            with self.assertRaises(sqlite3.DatabaseError):
                publisher.publicar()
        self.assertEqual((self.data / 'versao.json').read_bytes(), old)

    def test_snapshot_while_writer_has_uncommitted_work(self):
        with closing(sqlite3.connect(self.db)) as writer:
            writer.execute('PRAGMA journal_mode=WAL')
            writer.execute('INSERT INTO avaliacoes VALUES (2)')
            result = publisher.publicar()
            self.assertEqual(result['total_avaliacoes'], 1)
            writer.commit()
        self.assertEqual(publisher.publicar()['total_avaliacoes'], 2)

    def test_async_lock_status_and_errors(self):
        release = threading.Event()
        actual = publisher.publicar
        def delayed():
            if not release.wait(5):
                raise RuntimeError('test timeout')
            return actual()
        def finished():
            for _ in range(200):
                state = service.status()
                if state['situacao'] != 'publicando':
                    return state
                time.sleep(.01)
            self.fail('Worker did not finish')
        try:
            with patch.object(publisher, 'publicar', side_effect=delayed):
                self.assertEqual(service.iniciar()['situacao'], 'publicando')
                with self.assertRaises(main.HTTPException) as ctx:
                    service.iniciar()
                self.assertEqual(ctx.exception.status_code, 409)
                self.assertEqual(service.status()['situacao'], 'publicando')
                self.assertIsInstance(main.consultar_processamento(), dict)
                release.set()
                state = finished()
                self.assertEqual(state['situacao'], 'concluido')
                self.assertEqual(state['ultima_publicacao']['arquivo'], state['resultado']['arquivo'])
            with patch.object(publisher, 'publicar', side_effect=PermissionError('test denied')):
                service.iniciar()
                state = finished()
                self.assertEqual(state['situacao'], 'erro')
                self.assertIsNotNone(state['ultima_publicacao'])
            paths = main.app.openapi()['paths']
            self.assertIn('202', paths['/api/publicacao/iniciar']['post']['responses'])
            self.assertIn('get', paths['/api/publicacao/status'])
            self.assertEqual(main.inicio()['status'], 'online')
        finally:
            release.set()

    def test_viewer_excludes_mutations_and_main_retains_processing(self):
        self.assertFalse(any('POST' in getattr(r, 'methods', set()) for r in viewer_api.app.routes))
        self.assertFalse(any(r.path.startswith('/api/publicacao') for r in viewer_api.app.routes))
        routes = set(main.app.openapi()["paths"])
        self.assertIn('/api/processamento/iniciar', routes)
        self.assertIn('/api/processamento/parar', routes)
        self.assertEqual(main.QUANTIDADE_LOTE_WEB, -1)


if __name__ == '__main__':
    unittest.main()
