import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
from src.ai import Assistant
from src.privacy import Redactor
from src.query import spec
from src.limits import Governor


class ApiContractTests(unittest.TestCase):
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

    def test_unknown_document_citation_discards_summary(self):
        client = Mock()
        client.responses.create.return_value = SimpleNamespace(output_text='Revisa [D2].')
        a = Assistant(self.settings(), Governor(), client)
        self.assertEqual(a.explain('Pregunta 2', {'documents': [{'cita': 'D1'}]}, Redactor()), '')
