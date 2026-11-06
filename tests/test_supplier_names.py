import unittest
from unittest.mock import Mock

from src.catalog import CatalogStore, FIELDS, parse
from src.limits import Governor
from src.query import execute, spec
from src.service import ChatService
from tests.helpers import URL, fixture


def names_fixture():
    def update(rows):
        for row, name in zip(rows, ['LOZANO, CAMILA ANDREA', 'Camila Andrea Lozano',
                                   'Camila Lozano Perez', 'Camilano Lozano']):
            row[FIELDS['proveedor']] = name
    return fixture(update)


class SupplierNameTests(unittest.TestCase):
    def test_middle_names_order_accents_spacing_and_word_boundaries(self):
        rows = parse(names_fixture())[0]
        for name in ['Camila Lozano', 'lozano camila', ' Cámila  Lozano ']:
            with self.subTest(name=name):
                result = execute(rows, spec(operacion='contar', proveedor=name))
                self.assertEqual(result['matching_contracts'], 3)
                self.assertEqual(sum(r['resultado'] for r in result['rows']), 3)
                self.assertNotIn('Camilano Lozano', str(result['rows']))
        result = execute(rows, spec(proveedor='Camila Lozano', anio=2025))
        self.assertEqual(result['matching_contracts'], 2)

    def test_unknown_and_malicious_names_do_not_broaden_query(self):
        rows = parse(names_fixture())[0]
        for name in ['Persona inexistente', "Camila'; DROP TABLE contratos; --"]:
            self.assertEqual(execute(rows, spec(proveedor=name))['matching_contracts'], 0)

    def test_answer_shows_scope_and_warns_about_multiple_names(self):
        store = CatalogStore(URL, loader=Mock(return_value=(names_fixture(), {})))
        service = ChatService(store, Mock(), Governor(), {})
        result = service.answer('Cuantos contratos ha tenido Camila Lozano', 's',
                                plan=spec(operacion='contar', proveedor='Camila Lozano'))
        self.assertIn('3 contratos', result['text'])
        self.assertIn('base consultada', result['text'])
        self.assertTrue(any('misma persona' in w for w in result['warnings']))
        self.assertEqual(len(result['rows']), 3)

    def test_zero_is_not_a_claim_of_no_contract_history(self):
        store = CatalogStore(URL, loader=Mock(return_value=(names_fixture(), {})))
        result = ChatService(store, Mock(), Governor(), {}).answer('consulta', 's',
                       plan=spec(operacion='contar', proveedor='Persona inexistente'))
        self.assertIn('0 contratos', result['text'])
        self.assertIn('no demuestra', result['text'])
