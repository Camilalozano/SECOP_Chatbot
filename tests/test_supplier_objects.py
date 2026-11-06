import unittest
from unittest.mock import Mock
from src.catalog import CatalogStore, FIELDS
from src.limits import Governor
from src.query import basic_plan
from src.service import ChatService
from tests.helpers import fixture, URL


class SupplierObjectsTests(unittest.TestCase):
    def test_specific_university_and_objects_are_answered_without_ai(self):
        def update(rows):
            rows[0][FIELDS['proveedor']] = 'UNIVERSIDAD EAN'
            rows[0][FIELDS['objeto']] = 'Formación en emprendimiento'
        ai = Mock()
        service = ChatService(CatalogStore(URL, loader=Mock(return_value=(fixture(update), {}))), Mock(), Governor(), {}, ai)
        result = service.answer('hay contratos con la universidad EAN? de qué son?', 's')
        self.assertEqual(len(result['rows']), 1)
        self.assertEqual(result['filters']['proveedor'], 'UNIVERSIDAD EAN')
        self.assertIn('ATENEA-003-2025', result['text'])
        self.assertIn('Formación en emprendimiento', result['text'])
        ai.interpret.assert_not_called()

    def test_extra_conditions_do_not_get_swallowed_into_supplier_name(self):
        for q in ['Hay contratos con la universidad EAN vigentes',
                  'Hay contratos con la universidad EAN en 2026',
                  'Hay contratos con la universidad EAN y la universidad Nacional']:
            self.assertIsNone(basic_plan(q))
