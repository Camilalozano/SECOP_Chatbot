import unittest
from unittest.mock import Mock
from src.catalog import CatalogStore, FIELDS
from src.limits import Governor
from src.query import spec
from src.service import ChatService
from tests.helpers import URL, fixture
from tests.test_prepaid import settings


class CombinedListTests(unittest.TestCase):
    def test_count_and_list_normalize_supplier_class_and_active_state(self):
        def update(rows):
            rows[2][FIELDS['proveedor']] = 'UNIVERSIDAD OTRA'
        for operation in ['listar', 'contar']:
            with self.subTest(operation=operation):
                ai = Mock()
                ai.interpret.return_value = spec(operacion=operation, proveedor='universidades', estado='vigentes')
                store = CatalogStore(URL, loader=Mock(return_value=(fixture(update), {})))
                result = ChatService(store, Mock(), Governor(), settings(), ai).answer(
                    'Cuantos y cuales contratos con universidades hay vigentes en atenea?', 's')
                self.assertIn('2 contratos', result['text'])
                self.assertEqual(len(result['rows']), 2)
                self.assertEqual({r['referencia'] for r in result['rows']}, {'ATENEA-582-2025', 'ATENEA-003-2026'})
                self.assertEqual(result['filters']['estado'], 'En ejecución')
                self.assertNotIn('anio', result['filters'])
                self.assertTrue(any('sin comprobar vigencia por fechas' in w for w in result['warnings']))
                self.assertTrue(any('clasificación exhaustiva' in w for w in result['warnings']))
                self.assertEqual(len(result['sources']), 2)
                ai.explain.assert_not_called()
