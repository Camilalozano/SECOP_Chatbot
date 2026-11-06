import unittest
from unittest.mock import patch
from tests import test_prepaid
from src.query import spec


class AIOnlyTests(unittest.TestCase):
    def test_even_simple_questions_and_explicit_plans_require_ai(self):
        service, ai = test_prepaid.PrepaidTests().service()
        service.settings['AI_ONLY'] = True
        ai.interpret.return_value = spec(operacion='contar', anio=2025)
        with (patch('src.service.basic_plan', side_effect=AssertionError('basic route')),
              patch('src.service.fallback', side_effect=AssertionError('fallback'))):
            result = service.answer('Cuántos contratos hay en 2025', 's', plan=spec(), use_ai=False)
        self.assertTrue(result['ai_interpreted'])
        self.assertTrue(result['ai_summarized'])
        ai.interpret.assert_called_once()
        ai.explain.assert_called_once()

    def test_unavailable_or_failed_ai_never_falls_back(self):
        service, ai = test_prepaid.PrepaidTests().service()
        service.settings['AI_ONLY'] = True
        ai.interpret.side_effect = ValueError('failed')
        with self.assertRaises(ValueError):
            service.answer('Cuántos contratos hay en 2025', 's')
        service.settings['AI_ENABLED'] = False
        with self.assertRaises(ValueError):
            service.answer('Cuántos contratos hay en 2025', 's2')
