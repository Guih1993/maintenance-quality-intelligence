import sqlite3
import unittest
from contextlib import contextmanager
from unittest.mock import patch
from datetime import date
import backend.main as main
import viewer_api as viewer
from backend.database.models import SCHEMA


class DashboardFiltersTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.executemany("INSERT INTO ordens_servico(id,filial,ordem_servico,data_original,area,termino,hash_avaliacao) VALUES (?, 'DEMO', ?, '2026-01-10', ?, ?, 'hash')", [(1,'001','A','SIM'),(2,'002','A','NAO'),(3,'003','B','SIM'),(4,'004','B',None)])
        self.conn.executemany("INSERT INTO tecnicos(id,nome) VALUES (?,?)",[(1,'Ana'),(2,'Beto')])
        self.conn.executemany("INSERT INTO os_tecnicos VALUES (?,?)",[(1,1),(1,2),(2,1),(3,2),(4,2)])
        for os_id,score in [(1,100),(2,0)]:
            self.conn.execute("INSERT INTO avaliacoes(os_id,hash_avaliacao,versao_rubrica,versao_prompt,modelo_ia,c01_componente,c02_anomalia,c03_causa_evidencia,c04_intervencao,c05_teste,c06_clareza,score_0_100) VALUES (?,'hash','v','p','m',1,1,1,1,1,1,?)",(os_id,score))
        @contextmanager
        def connection():
            yield self.conn
        self.patches=[patch.object(main,'get_connection',connection),patch.object(viewer,'conectar',connection)]
        for p in self.patches:p.start()

    def tearDown(self):
        for p in self.patches:p.stop()
        self.conn.close()

    def test_closure_counts_all_orders_and_unknown_separately(self):
        for api in [main,viewer]:
            r=api.resumo()
            self.assertEqual((r['taxa_encerramento'],r['os_abertas'],r['os_termino_desconhecido']),(50,1,1))
            rows=api.indicadores_tecnicos('',500,'taxa_encerramento','asc',False)
            self.assertEqual([r['taxa_encerramento'] for r in rows],[50,66.67])
            rows=api.ordens_periodo(date(2026,1,1),date(2026,1,31),1,50,'termino','asc')['registros']
            self.assertEqual(len(rows),4)
            self.assertEqual(sum(r['termino']=='SIM' for r in rows),2)

    def test_all_technicians_do_not_duplicate_shared_orders(self):
        for query in [main.evolucao_score,viewer.evolucao]:
            for ids in [None,[1,2],[1,1,2]]:
                row=query(2026,None,'',ids)[0]
                self.assertEqual(row['score_medio'],50)
                self.assertEqual(row['os_com_score'],2)
                self.assertIsNone(row['tecnico_id'])

    def test_technician_criteria_current_valid_scores_and_empty(self):
        from fastapi import HTTPException
        self.conn.execute("UPDATE avaliacoes SET c01_componente=2 WHERE os_id=1")
        self.conn.execute("UPDATE avaliacoes SET c01_componente=0 WHERE os_id=2")
        self.conn.execute("INSERT INTO tecnicos(id,nome) VALUES (3,'Sem OS')")
        for api in [main,viewer]:
            ana=api.criterios_tecnico(1)
            self.assertEqual((ana['total_os'],ana['os_com_score']),(2,2))
            self.assertEqual(ana['medias_criterios']['c01_componente'],1)
            self.assertEqual(len(ana['medias_criterios']),6)
            self.assertEqual(api.criterios_tecnico(2)['medias_criterios']['c01_componente'],2)
            vazio=api.criterios_tecnico(3)
            self.assertEqual(vazio['os_com_score'],0)
            self.assertTrue(all(v is None for v in vazio['medias_criterios'].values()))
            with self.assertRaises(HTTPException) as erro:
                api.criterios_tecnico(999)
            self.assertEqual(erro.exception.status_code,404)
        self.conn.execute("UPDATE avaliacoes SET hash_avaliacao='antigo' WHERE os_id=2")
        for api in [main,viewer]:
            self.assertEqual(api.criterios_tecnico(1)['medias_criterios']['c01_componente'],2)
        self.conn.execute("UPDATE avaliacoes SET c06_clareza=NULL WHERE os_id=1")
        for api in [main,viewer]:
            self.assertEqual(api.criterios_tecnico(1)['os_com_score'],0)

    def test_overview_dates_closure_and_validation(self):
        from fastapi import HTTPException
        self.conn.execute("UPDATE ordens_servico SET data_original='2026-02-10' WHERE id=2")
        for api in [main, viewer]:
            r = api.resumo(date(2026,2,1), date(2026,2,28))
            self.assertEqual((r['total_os_importadas'],r['os_avaliadas'],r['score_medio'],r['os_abertas'],r['taxa_encerramento']), (1,1,0,1,0))
            self.assertEqual(len(api.listar_avaliacoes(50,'',date(2026,2,1),date(2026,2,28))),1)
            period = api.ordens_periodo(date(2026,1,1),date(2026,2,28),1,1,'data_os','asc')['resumo']
            self.assertEqual((period['taxa_encerramento'],period['os_abertas']),(50,1))
            self.assertIsNone(api.resumo(date(2027,1,1),None)['taxa_encerramento'])
            with self.assertRaises(HTTPException):
                api.resumo(date(2026,2,1),date(2026,1,1))

    def test_ranking_requires_eleven_scores_before_limit_and_in_period(self):
        for os_id in range(5,14):
            self.conn.execute("INSERT INTO ordens_servico(id,filial,ordem_servico,data_original,hash_avaliacao) VALUES (?,'DEMO',?,'2026-01-10','hash')",(os_id,str(os_id)))
            self.conn.execute("INSERT INTO os_tecnicos VALUES (?,1)",(os_id,))
            self.conn.execute("INSERT INTO os_tecnicos VALUES (?,2)",(os_id,))
            self.conn.execute("INSERT INTO avaliacoes(os_id,hash_avaliacao,versao_rubrica,versao_prompt,modelo_ia,c01_componente,c02_anomalia,c03_causa_evidencia,c04_intervencao,c05_teste,c06_clareza,score_0_100) SELECT ?,hash_avaliacao,versao_rubrica,versao_prompt,modelo_ia,c01_componente,c02_anomalia,c03_causa_evidencia,c04_intervencao,c05_teste,c06_clareza,100 FROM avaliacoes WHERE os_id=1",(os_id,))
        for api in [main,viewer]:
            rows=api.indicadores_tecnicos('',1,'score_medio','desc',True,None,None,11)
            self.assertEqual([(r['tecnico'],r['os_com_score']) for r in rows],[('Ana',11)])
            self.assertEqual(api.indicadores_tecnicos('',5,'score_medio','desc',True,date(2026,2,1),None,11),[])

    def test_technician_sector_month_and_empty_filters(self):
        for query in [main.evolucao_score,viewer.evolucao]:
            row=query(2026,1,'A',[2])[0]
            self.assertEqual((row['tecnico_id'],row['score_medio'],row['periodo']),(2,100,'2026-01-10'))
            self.assertEqual(query(2026,2,'A',[2]),[])
            self.assertEqual(query(2026,1,"A' OR 1=1 --",[2]),[])
            self.assertEqual(query(2026,1,'B',[1]),[])

    def test_cumulative_weighted_score_carries_over_empty_months(self):
        self.conn.execute("UPDATE ordens_servico SET data_original='2026-03-10' WHERE id=2")
        for query in [main.evolucao_score, viewer.evolucao]:
            rows = query(2026, None, 'A', [1])
            self.assertEqual([r['score_medio'] for r in rows[:4]], [100,100,50,50])
            self.assertEqual([r['os_com_score'] for r in rows[:4]], [1,1,2,2])
            self.assertEqual(query(2026,3,'A',[1])[0]['score_medio'], 0)
        self.conn.execute("UPDATE ordens_servico SET area='A' WHERE id=3")
        self.conn.execute("INSERT INTO os_tecnicos VALUES (3,1)")
        self.conn.execute("INSERT INTO avaliacoes(os_id,hash_avaliacao,versao_rubrica,versao_prompt,modelo_ia,c01_componente,c02_anomalia,c03_causa_evidencia,c04_intervencao,c05_teste,c06_clareza,score_0_100) SELECT 3,hash_avaliacao,versao_rubrica,versao_prompt,modelo_ia,c01_componente,c02_anomalia,c03_causa_evidencia,c04_intervencao,c05_teste,c06_clareza,100 FROM avaliacoes WHERE os_id=1")
        for query in [main.evolucao_score, viewer.evolucao]:
            self.assertEqual(query(2026,None,'A',[1])[2]['score_medio'], 66.67)

if __name__ == '__main__':
    unittest.main()
