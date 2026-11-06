import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
from src.ai import enabled
from src.catalog import CatalogStore
from src.limits import Governor
from src.query import spec
from src.service import ChatService
from tests.helpers import fixture, URL


def settings():
    return {'OPENAI_API_KEY': 'sk-fake-test', 'AI_ENABLED': True, 'AI_CREDIT_MODE': 'prepaid',
            'PREPAID_CREDITS_VERIFIED': True, 'AUTO_RECHARGE_DISABLED_VERIFIED': True,
            'VERIFIED_CREDIT_BALANCE_USD': 5, 'HOSTING_AND_ORACLE_QUOTA_VERIFIED': True,
            'AI_RUN_BUDGET_USD': 1, 'AI_TURN_RESERVE_USD': 0.05,
            'CREDITS_VERIFIED_UNTIL': (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()}


class PrepaidTests(unittest.TestCase):
    def service(self):
        assistant = Mock()
        assistant.interpret.return_value = spec(operacion='contar', anio=2025, proveedor='UNIVERSIDAD', estado='En ejecución')
        assistant.explain.return_value = 'Hay 1 contrato con estos filtros.'
        store = CatalogStore(URL, loader=Mock(return_value=(fixture(), {})))
        return ChatService(store, Mock(), Governor(), settings(), assistant), assistant

    def test_purchased_balance_does_not_require_false_included_credit_claim(self):
        s = settings()
        self.assertTrue(enabled(s))
        self.assertNotIn('INCLUDED_CREDITS_ONLY_VERIFIED', s)

    def test_no_key_or_no_verified_auto_reload_blocks_ai(self):
        for field, value in [('OPENAI_API_KEY', ''), ('OPENAI_API_KEY', None), ('AUTO_RECHARGE_DISABLED_VERIFIED', False),
                             ('PREPAID_CREDITS_VERIFIED', False), ('VERIFIED_CREDIT_BALANCE_USD', 0),
                             ('AI_RUN_BUDGET_USD', 6), ('AI_CREDIT_MODE', 'unknown')]:
            with self.subTest(field=field):
                s = settings(); s[field] = value
                self.assertFalse(enabled(s))

    def test_ai_query_combines_filters_and_explains_computed_fact(self):
        service, assistant = self.service()
        result = service.answer('Cuántos contratos de universidades están en ejecución en 2025', 's', use_ai=True)
        self.assertTrue(result['ai_interpreted'])
        self.assertTrue(result['ai_summarized'])
        self.assertEqual(result['rows'][0]['resultado'], 1)
        self.assertEqual(result['filters']['anio'], 2025)
        self.assertEqual(assistant.explain.call_args.args[1]['matching_contracts'], 1)
        self.assertEqual(service.governor.reserved, 0.05)

    def test_basic_mode_and_filters_never_call_ai_with_a_valid_key(self):
        service, assistant = self.service()
        result = service.answer('Cuántos contratos hay en 2025', 's', use_ai=False)
        self.assertEqual(result['rows'][0]['resultado'], 2)
        self.assertFalse(result['ai_interpreted'])
        service.answer('Consulta con filtros', 's', plan=spec(operacion='contar'), use_ai=True)
        assistant.interpret.assert_not_called()
        assistant.explain.assert_not_called()
        self.assertEqual(service.governor.reserved, 0)

    def test_ai_error_keeps_basic_query_available(self):
        service, assistant = self.service()
        assistant.interpret.side_effect = ValueError('IA temporalmente no disponible.')
        result = service.answer('Cuántos contratos hay en 2026', 's', use_ai=True)
        self.assertEqual(result['rows'][0]['resultado'], 2)
        self.assertFalse(result['ai_interpreted'])
        self.assertTrue(result['warnings'])

    def test_budget_status_disables_ai_without_disabling_filters(self):
        gov = Governor()
        self.assertTrue(gov.ai_available(0.05))
        with gov.turn('s', ai=True, budget=0.05): pass
        self.assertFalse(gov.ai_available(0.05))
        with gov.turn('s', ai=False): pass
