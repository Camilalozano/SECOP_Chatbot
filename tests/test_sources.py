import io
import unittest
import zipfile
from unittest.mock import Mock
from src.catalog import CatalogStore
from src.documents import Documents
from src.secop_catalog import lookup_documents
from tests.helpers import fixture, URL


class SourcesTests(unittest.TestCase):
    def test_historical_process_and_other_contract(self):
        def query(endpoint, params, opener):
            if 'h4m3-b4e2' not in endpoint:
                return []
            own = {'id_documento': '1', 'proceso': 'CO1.BDOS.42', 'n_mero_de_contrato': 'CO1.PCCNTR.200'}
            if 'proceso' in params:
                return [own, {'id_documento': '2', 'proceso': 'CO1.BDOS.42'},
                        {'id_documento': '3', 'proceso': 'CO1.BDOS.42', 'n_mero_de_contrato': 'CO1.PCCNTR.999'}]
            return [own]
        rows, warnings = lookup_documents('CO1.PCCNTR.200', query, None)
        self.assertEqual([r['id_documento'] for r in rows], ['1', '2'])
        self.assertFalse(warnings)

    def test_zip_pdf_provenance_and_ocr_failure(self):
        snapshot = CatalogStore(URL, loader=Mock(return_value=(fixture(), {}))).refresh()[0]
        content = io.BytesIO()
        with zipfile.ZipFile(content, 'w') as archive:
            archive.writestr('CARPETA/ESTUDIOS PREVIOS.pdf', b'%PDF-fixture')
            archive.writestr('CARPETA/CDP.pdf', b'%PDF-unrelated')
        rows = [{'id_documento': '1', '_asociacion': 'contrato', 'nombre_archivo': 'CARPETA.zip', 'extensi_n': 'zip',
                 'url_descarga_documento': 'https://community.secop.gov.co/Public/Archive/RetrieveFile/Index?DocumentId=1'}]
        reader = Mock(return_value=['ATENEA-582-2025 OBLIGACIONES DE LA IES: 1. Reportar. D. OBLIGACIONES DE LA AGENCIA: Pagar.'])
        docs = Documents(lookup=lambda cid: (rows, []), download=Mock(return_value=(content.getvalue(), {})), reader=reader)
        result = docs.answer(snapshot.rows[1], snapshot, '', 'obligaciones')
        self.assertEqual(result['documents'][0]['archivo'], 'CARPETA/ESTUDIOS PREVIOS.pdf')
        self.assertEqual(reader.call_count, 1)
        self.assertIn('sha256', result['documents'][0])

    def test_number_inside_obligation_is_not_a_new_marker(self):
        from src.obligations import extract_obligations
        result = extract_obligations('OBLIGACIONES DE LA IES: 1. Reportar en 30 días. 2. Entregar a 20 beneficiarios. D. OBLIGACIONES DE LA AGENCIA: Pagar.')
        self.assertEqual(len(result), 2)
        self.assertIn('30 días', result[0]['obligaciones_especificas'])
