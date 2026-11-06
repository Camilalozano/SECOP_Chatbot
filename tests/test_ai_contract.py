import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
from src.ai import Assistant
from src.privacy import Redactor
from src.query import spec
from src.limits import Governor


class ApiContractTests(unittest.TestCase):
    def test_table_answer_cannot_publish_document_labels(self):
        client = Mock()
        client.responses.create.return_value = SimpleNamespace(output_text='Hay 2 contratos [D1].')
        a = Assistant(self.settings(), Governor(), client)
        result = a.explain('Cuántos', {'matching_contracts': 2, 'documents': []}, Redactor())
        self.assertNotIn('[D1]', result)
        self.assertIn('2 contratos', result)
    def test_summary_inserts_exact_verified_values_from_model_slots(self):
        import json
        client = Mock()
        def create(**kwargs):
            evidence = json.loads(kwargs['input'])['evidencia']
            return SimpleNamespace(output_text='Se encontraron ' + evidence['matching_contracts'] + ' contratos.')
        client.responses.create.side_effect = create
        a = Assistant(self.settings(), Governor(), client)
        self.assertEqual(a.explain('Cuántos', {'matching_contracts': 24}, Redactor()), 'Se encontraron 24 contratos.')

    def test_unnecessary_clarification_gets_reviewed_by_ai(self):
        client = Mock()
        client.responses.parse.side_effect = [
            SimpleNamespace(output_parsed=spec(operacion='aclarar', aclaracion='Confirma si buscar en el objeto')),
            SimpleNamespace(output_parsed=spec(operacion='contar', texto='inteligencia artificial'))]
        result = Assistant(self.settings(), Governor(), client).interpret(
            'cuantos contratos relacionados con inteligencia artificial hay en atenea?', Redactor())
        self.assertEqual(result.texto, 'inteligencia artificial')
        self.assertEqual(result.operacion, 'contar')
        self.assertEqual(client.responses.parse.call_count, 2)
        self.assertFalse(client.responses.parse.call_args.kwargs['store'])

    def test_review_preserves_real_unsupported_question(self):
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(output_parsed=spec(operacion='aclarar', aclaracion='No se puede calcular cumplimiento'))
        result = Assistant(self.settings(), Governor(), client).interpret('Porcentaje de cumplimiento', Redactor())
        self.assertEqual(result.operacion, 'aclarar')

    def settings(self):
        return {'OPENAI_API_KEY': 'sk-fake', 'AI_ENABLED': True, 'INCLUDED_CREDITS_ONLY_VERIFIED': True,
                'NO_PAID_FALLBACK_VERIFIED': True, 'HOSTING_AND_ORACLE_QUOTA_VERIFIED': True,
                'AI_RUN_BUDGET_USD': 1, 'CREDITS_VERIFIED_UNTIL': (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()}

    def test_structured_plan_store_false_and_redacted_input(self):
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(output_parsed=spec(operacion='contar'))
        a = Assistant(self.settings(), Governor(), client)
        result = a.interpret('Consultar 1111111111', Redactor(['1111111111']))
        self.assertEqual(result.operacion, 'contar')
        kwargs = client.responses.parse.call_args.kwargs
        self.assertFalse(kwargs['store'])
        self.assertNotIn('1111111111', kwargs['input'])
        self.assertEqual(kwargs['model'], 'gpt-5-mini')

    def test_unsourced_number_discards_generated_summary(self):
        client = Mock()
        client.responses.create.return_value = SimpleNamespace(output_text='Hay 999 contratos.')
        a = Assistant(self.settings(), Governor(), client)
        self.assertEqual(a.explain('Cuántos', {'matching_contracts': 2}, Redactor()), '')
        self.assertFalse(client.responses.create.call_args.kwargs['store'])

    def test_summary_review_recovers_without_accepting_new_numbers(self):
        client = Mock()
        client.responses.create.side_effect = [SimpleNamespace(output_text='Hay 999 contratos.'),
                                                SimpleNamespace(output_text='Hay 2 contratos.')]
        a = Assistant(self.settings(), Governor(), client)
        self.assertEqual(a.explain('Cuántos', {'matching_contracts': 2}, Redactor()), 'Hay 2 contratos.')
        self.assertEqual(client.responses.create.call_count, 2)

    def test_leading_zero_date_format_does_not_reject_supported_number(self):
        client = Mock()
        client.responses.create.return_value = SimpleNamespace(output_text='Finaliza el 5 de noviembre de 2026.')
        a = Assistant(self.settings(), Governor(), client)
        self.assertTrue(a.explain('Fecha', {'fin': '2026-11-05'}, Redactor()))

    def test_unknown_document_citation_discards_summary(self):
        client = Mock()
        client.responses.create.return_value = SimpleNamespace(output_text='Revisa [D2].')
        a = Assistant(self.settings(), Governor(), client)
        self.assertEqual(a.explain('Pregunta 2', {'documents': [{'cita': 'D1'}]}, Redactor()), '')
