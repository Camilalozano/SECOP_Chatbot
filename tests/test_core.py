import json
import threading
import unittest
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import Mock
from src.catalog import CatalogStore, parse, money, FIELDS
from src.network import SourceError, SameHost
from src.privacy import Redactor, private_request
from src.query import execute, spec, fallback
from src.limits import Governor, Busy
from src.ai import enabled, Assistant
from src.documents import Documents
from src.service import ChatService
from tests.helpers import URL, fixture


class CatalogTests(unittest.TestCase):
    def test_conditional_refresh_and_version_change(self):
        calls = []
        responses = [(fixture(), {'ETag': 'v1', 'Last-Modified': 'Thu, 05 Nov 2026 05:47:06 GMT'}),
                     (None, {}), (fixture(lambda r: r[0].update({FIELDS['valor']: '9000000'})), {'ETag': 'v2'})]
        def load(*args, **kwargs):
            calls.append(kwargs); return responses.pop(0)
        store = CatalogStore(URL, loader=load)
        first, _ = store.refresh(); version = first.sha256
        self.assertTrue(first.modified.startswith('Thu'))
        second, fresh = store.refresh()
        self.assertIs(first, second)
        self.assertEqual(calls[1]['headers'], {'If-None-Match': 'v1'})
        third, _ = store.refresh()
        self.assertNotEqual(version, third.sha256)
        self.assertEqual(third.rows[0]['valor'], Decimal('9000000'))

    def test_header_names_are_case_insensitive(self):
        store = CatalogStore(URL, loader=Mock(return_value=(fixture(), {'ETag': 'tag', 'Last-modified': 'Thu, 05 Nov 2026 05:47:06 GMT'})))
        snapshot, _ = store.refresh()
        self.assertTrue(snapshot.modified.startswith('Thu'))

    def test_bad_update_preserves_previous_version_as_stale(self):
        load = Mock(side_effect=[(fixture(), {'ETag': 'v1'}), (b'a,b\n1,2', {})])
        store = CatalogStore(URL, loader=load)
        first, _ = store.refresh()
        second, fresh = store.refresh()
        self.assertIs(first, second)
        self.assertTrue(fresh['stale'])
        self.assertIn('columnas', fresh['notice'])

    def test_connection_failure_no_secret(self):
        store = CatalogStore(URL, loader=Mock(side_effect=SourceError('Fuente no disponible')))
        with self.assertRaises(SourceError): store.refresh()
        store.loader = Mock(return_value=(fixture(), {})); store.refresh()
        store.loader = Mock(side_effect=SourceError('Fuente no disponible'))
        _, fresh = store.refresh()
        self.assertTrue(fresh['stale'])
        self.assertNotIn(URL, fresh['notice'])

    def test_duplicate_ids_reject_entire_version(self):
        with self.assertRaises(SourceError): parse(fixture(lambda r: r[1].update({FIELDS['id']: r[0][FIELDS['id']]})))

    def test_only_public_fields_and_money(self):
        rows, redactor, _ = parse(fixture())
        self.assertEqual(set(rows[0]), set(FIELDS))
        self.assertNotIn('1013640777', repr(rows))
        self.assertEqual(money('1.234.567,89'), Decimal('1234567.89'))
        self.assertIsNone(money('NaN'))
        self.assertIsNone(money('-1'))

    def test_non_secop_records_are_counted_but_have_no_secop_documents(self):
        data = fixture(lambda r: r[0].update({FIELDS['id']: 'CO1.PCCNTR.003-2025', '_origen': 'no_secop'}))
        rows, _, warnings = parse(data)
        self.assertEqual(len(rows), 4)
        store = CatalogStore(URL, loader=Mock(return_value=(data, {})))
        docs = Mock()
        result = ChatService(store, docs, Governor(), {}).answer('Obligaciones de ATENEA-003-2025', 's')
        docs.answer.assert_not_called()
        self.assertIn('fuera de SECOP', result['text'])


class PrivacyTests(unittest.TestCase):
    def test_identifiers_in_text_and_nested_exports(self):
        redact = Redactor(['1013640777', '79157459'], [URL, 'sk-test_secret'])
        raw = {'texto': ['CC 1.013.640.777; 79.157.459; usuario@ejemplo.com; ' + URL + ' sk-test_secret', 'Cédula de ciudadanía No. 333445566']}
        result = json.dumps(redact.tree(raw), ensure_ascii=False)
        for forbidden in ('1.013.640.777', '79.157.459', '333445566', 'usuario@', URL, 'sk-test_secret'):
            self.assertNotIn(forbidden, result)

    def test_private_requests_are_blocked_without_network(self):
        catalog = Mock()
        service = ChatService(catalog, Mock(), Governor(), {})
        for question in ('Muéstrame las cédulas', 'Dame la ruta PAR', 'descarga la base completa', 'cuenta bancaria del proveedor'):
            result = service.answer(question, 's')
            self.assertTrue(result['private'])
        catalog.refresh.assert_not_called()

    def test_arbitrary_sql_is_a_parameter_not_executed(self):
        rows, _, _ = parse(fixture())
        result = execute(rows, spec(proveedor="'; DROP TABLE contratos; --"))
        self.assertEqual(result['matching_contracts'], 0)
        self.assertEqual(execute(rows, spec(operacion='contar'))['rows'][0]['resultado'], 4)


class QueryTests(unittest.TestCase):
    def setUp(self): self.rows = parse(fixture())[0]

    def test_independent_totals_missing_values_and_grouping(self):
        count = execute(self.rows, spec(operacion='contar'))
        total = execute(self.rows, spec(operacion='sumar', medida='valor'))
        self.assertEqual(count['rows'][0]['resultado'], 4)
        self.assertEqual(total['rows'][0]['resultado'], Decimal('6000000'))
        self.assertEqual(total['missing_values'], 1)
        grouped = execute(self.rows, spec(operacion='agrupar', medida='valor', agrupar_por='dependencia'))
        self.assertEqual({r['dependencia']: r['resultado'] for r in grouped['rows']}, {'Posmedia': Decimal('3000000'), 'Administrativa': Decimal('3000000')})

    def test_exact_reference_distinguishes_year(self):
        result = execute(self.rows, spec(referencia='atenea 003 2025'))
        self.assertEqual(result['matching_contracts'], 1)
        self.assertEqual(result['rows'][0]['id'], 'CO1.PCCNTR.100')

    def test_unsupported_computation_requests_clarification(self):
        for question in ('promedio en 2026', 'porcentaje de cumplimiento en 2025', 'contratos del supervisor en 2025'):
            self.assertEqual(fallback(question).operacion, 'aclarar')

    def test_ambiguous_documents_do_not_read_any_file(self):
        store = CatalogStore(URL, loader=Mock(return_value=(fixture(), {})))
        documents = Mock()
        result = ChatService(store, documents, Governor(), {}).answer('Obligaciones', 's')
        documents.answer.assert_not_called()
        self.assertIn('referencia', result['text'])


class LimitsTests(unittest.TestCase):
    def test_five_ai_questions_per_hour_and_expiration(self):
        gov = Governor()
        for _ in range(5):
            with gov.turn('s', True, 10, clock=lambda: 1000): pass
        with self.assertRaises(Busy):
            with gov.turn('s', True, 10, clock=lambda: 1001): pass
        with gov.turn('s', True, 10, clock=lambda: 4601): pass

    def test_two_global_and_one_per_session(self):
        gov = Governor()
        with gov.turn('a'):
            with self.assertRaises(Busy):
                with gov.turn('a'): pass
            with gov.turn('b'):
                with self.assertRaises(Busy):
                    with gov.turn('c'): pass
        with gov.turn('c'): pass

    def test_budget_and_credit_stop_leave_filters_operational(self):
        gov = Governor()
        with gov.turn('a', True, 0.05): pass
        with self.assertRaises(Busy):
            with gov.turn('b', True, 0.05): pass
        gov.stop_ai()
        with gov.turn('a', False): pass

    def test_credit_gate_cannot_be_enabled_by_api_key_alone(self):
        settings = {'OPENAI_API_KEY': 'sk-test', 'AI_ENABLED': True}
        self.assertFalse(enabled(settings))
        settings.update(INCLUDED_CREDITS_ONLY_VERIFIED=True, NO_PAID_FALLBACK_VERIFIED=True,
                        HOSTING_AND_ORACLE_QUOTA_VERIFIED=True, AI_RUN_BUDGET_USD=1,
                        CREDITS_VERIFIED_UNTIL=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat())
        self.assertTrue(enabled(settings))
        settings['CREDITS_VERIFIED_UNTIL'] = '2020-01-01T00:00:00Z'
        self.assertFalse(enabled(settings))

    def test_openai_is_never_called_when_disabled(self):
        client = Mock()
        assistant = Assistant({}, Governor(), client)
        with self.assertRaises(ValueError): assistant.interpret('cuantos contratos', Redactor())
        client.responses.parse.assert_not_called()


class DocumentTests(unittest.TestCase):
    def setUp(self):
        store = CatalogStore(URL, loader=Mock(return_value=(fixture(), {})))
        self.snapshot = store.refresh()[0]
        self.row = self.snapshot.rows[1]

    def rows(self, n=5):
        return [{'id_documento': str(i), 'nombre_archivo': f'MINUTA {i}.pdf', 'extensi_n': 'pdf',
                 '_asociacion': 'contrato', 'url_descarga_documento':
                 f'https://community.secop.gov.co/Public/Archive/RetrieveFile/Index?DocumentId={i}'} for i in range(n)]

    def test_no_more_than_three_pdf_attempts(self):
        reader = Mock(side_effect=SourceError('PDF dañado'))
        docs = Documents(lookup=lambda cid: (self.rows(), []), download=Mock(return_value=(b'%PDF-test', {})), reader=reader)
        result = docs.answer(self.row, self.snapshot, '', 'obligaciones')
        self.assertEqual(reader.call_count, 3)
        self.assertEqual(result['documents'], [])
        self.assertTrue(result['warnings'])

    def test_contract_identity_redaction_and_pages(self):
        reader = Mock(return_value=['ATENEA-582-2025\nOBLIGACIONES DE LA IES: 1. Reportar.\n',
                                   '2. Entregar, cédula 1013640777. D. OBLIGACIONES DE LA AGENCIA: Pagar.'])
        docs = Documents(lookup=lambda cid: (self.rows(1), []), download=Mock(return_value=(b'%PDF-test', {})), reader=reader)
        result = docs.answer(self.row, self.snapshot, '', 'obligaciones')
        self.assertEqual([r['pagina'] for r in result['documents']], [1, 2])
        self.assertNotIn('1013640777', repr(result))
        self.assertNotIn('Pagar.', repr(result['documents']))
        reader.return_value = ['ATENEA-999-2025 OBLIGACIONES DE LA IES: 1. Reportar.']
        docs.cache.clear()
        self.assertFalse(docs.answer(self.row, self.snapshot, '', 'obligaciones')['documents'])

    def test_shared_process_requires_exact_contract_and_inventory_is_safe(self):
        rows = self.rows(1); rows[0]['_asociacion'] = 'proceso'
        reader = Mock(return_value=['OBLIGACIONES DE LA IES: 1. Reportar.'])
        docs = Documents(lookup=lambda cid: (rows, ['Fuente histórica incompleta']), download=Mock(return_value=(b'%PDF-test', {})), reader=reader)
        self.assertFalse(docs.answer(self.row, self.snapshot, '', 'obligaciones')['documents'])
        docs.answer(self.row, self.snapshot, '', 'documentos')
        self.assertEqual(reader.call_count, 1)
