import unittest
from unittest.mock import Mock
from src.query import basic_plan, spec
from tests import test_prepaid


class RoutingTests(unittest.TestCase):
    def test_simple_question_does_not_consume_ai_or_quota(self):
        service, ai = test_prepaid.PrepaidTests().service()
        result = service.answer('¿Cuántos contratos hay en 2025?', 's')
        self.assertEqual(result['rows'][0]['resultado'], 2)
        self.assertFalse(result['ai_interpreted'])
        ai.interpret.assert_not_called()
        ai.explain.assert_not_called()
        self.assertEqual(service.governor.reserved, 0)

    def test_unrecognized_conditions_are_never_silently_dropped(self):
        service, ai = test_prepaid.PrepaidTests().service()
        question = 'Cuantos contratos ha tenido Camila Lozano'
        self.assertIsNone(basic_plan(question))
        ai.interpret.return_value = spec(operacion='contar', proveedor='Camila Lozano')
        service.answer(question, 's')
        ai.interpret.assert_called_once()
        service.settings['AI_ENABLED'] = False
        result = service.answer(question, 's2')
        self.assertEqual(result['rows'], [])
        self.assertIn('filtros', result['text'])
        for question in ['Cuántos contratos hay en 2026 de Camila Lozano',
                         'Valor contratado en 2026 para universidades',
                         'Obligaciones de ATENEA-582-2025 y ATENEA-003-2026']:
            self.assertIsNone(basic_plan(question))

    def test_ai_failure_asks_for_filters_instead_of_unfiltered_count(self):
        service, ai = test_prepaid.PrepaidTests().service()
        ai.interpret.side_effect = ValueError('IA no disponible')
        result = service.answer('Cuantos contratos ha tenido Camila Lozano', 's')
        self.assertEqual(result['rows'], [])
        self.assertIn('filtros', result['text'])
