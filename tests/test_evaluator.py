import json
import unittest
from unittest.mock import patch

from backend.ai.evaluator import CRITERIOS, ResultadoAvaliacao, validar_resultado
from backend.ai import processor


def resposta_valida():
    return {
        **dict.fromkeys(CRITERIOS, 1),
        'justificativas': dict.fromkeys(CRITERIOS, 'Evidencia documental parcial.'),
        'justificativa_na': '',
        'lacunas_identificadas': [],
        'orientacao_treinamento': 'Detalhar a intervencao.',
    }


class EvaluatorTests(unittest.TestCase):
    def test_schema_requires_exact_six_justifications(self):
        schema = ResultadoAvaliacao.model_json_schema()['properties']['justificativas']
        self.assertEqual(set(schema['required']), set(CRITERIOS))
        self.assertEqual(set(schema['properties']), set(CRITERIOS))
        self.assertIs(schema['additionalProperties'], False)
        self.assertTrue(all(p['minLength'] == 1 for p in schema['properties'].values()))

    def test_valid_response_preserves_notes_and_serialization(self):
        data = resposta_valida()
        self.assertEqual(validar_resultado(json.dumps(data)).model_dump(), data)

    def test_missing_or_renamed_justifications_are_rejected(self):
        for replacement in ({}, {'C01': 'Componente identificado.'}):
            data = resposta_valida()
            data['justificativas'] = replacement
            with self.assertRaisesRegex(ValueError, 'Chaves ausentes:'):
                validar_resultado(json.dumps(data))
        data = resposta_valida()
        data['justificativas']['extra'] = 'Texto'
        with self.assertRaisesRegex(ValueError, 'Chaves inesperadas: extra'):
            validar_resultado(json.dumps(data))

    def test_empty_justification_and_invalid_notes_remain_rejected(self):
        for value in ('', '   '):
            data = resposta_valida()
            data['justificativas']['c06_clareza'] = value
            with self.assertRaisesRegex(ValueError, 'Justificativa vazia: c06_clareza'):
                validar_resultado(json.dumps(data))
        for value in (-1, 3, None):
            data = resposta_valida()
            data['c01_componente'] = value
            with self.assertRaises(ValueError):
                validar_resultado(json.dumps(data))
        data = resposta_valida()
        del data['c06_clareza']
        with self.assertRaises(ValueError):
            validar_resultado(json.dumps(data))

    def test_processor_sends_strict_schema_and_never_saves_invalid_response(self):
        order = {'id': 1, 'hash_avaliacao': 'test', 'ordem_servico': 'DEMO-001'}
        with patch.object(processor, 'os_ja_avaliada', return_value=False), \
             patch.object(processor, 'montar_prompt', return_value='prompt preservado'), \
             patch.object(processor, 'gerar_resposta') as generate, \
             patch.object(processor, 'salvar_avaliacao') as save:
            data = resposta_valida()
            data['justificativas'] = {}
            generate.return_value = {'resposta': json.dumps(data)}
            with self.assertRaises(ValueError):
                processor.processar_os(order)
            save.assert_not_called()
            schema = generate.call_args.kwargs['formato']['properties']['justificativas']
            self.assertEqual(set(schema['required']), set(CRITERIOS))
            generate.return_value = {'resposta': json.dumps(resposta_valida())}
            save.return_value = {'score': 50, 'inserida': True}
            processor.processar_os(order)
            save.assert_called_once()


if __name__ == '__main__':
    unittest.main()
