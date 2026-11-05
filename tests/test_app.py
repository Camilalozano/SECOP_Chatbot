import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from streamlit.testing.v1 import AppTest
from src.catalog import CatalogStore
from src.documents import Documents
from src.limits import Governor
from src.service import ChatService
from tests.helpers import fixture, URL

APP = str(Path(__file__).resolve().parents[1] / 'app.py')


class AppTests(unittest.TestCase):
    def test_oracle_timestamp_is_shown_in_bogota(self):
        from app import local_time
        self.assertIn('05/11/2026 00:47', local_time('Thu, 05 Nov 2026 05:47:06 GMT'))

    def start(self):
        app = AppTest.from_file(APP, default_timeout=20)
        app.secrets['ORACLE_PAR_URL'] = URL
        app.secrets['AI_ENABLED'] = False
        self.loader = Mock(return_value=(fixture(), {'ETag': 'v1'}))
        self.patch = patch('src.catalog.CatalogStore.refresh', side_effect=CatalogStore(URL, loader=self.loader).refresh)
        self.patch.start(); self.addCleanup(self.patch.stop)
        app.run()
        self.assertFalse(app.exception)
        return app

    def test_public_without_authentication_or_key_and_count(self):
        app = self.start()
        self.assertFalse(any('contraseña' in x.label.lower() for x in app.text_input))
        next(b for b in app.button if b.label == '¿Cuántos contratos hay en 2026?').click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state['messages'][-1]['rows'][0]['resultado'], 2)
        self.assertEqual(len(app.get('download_button')), 1)

    def test_filters_export_and_redaction(self):
        app = self.start()
        next(t for t in app.text_input if t.label == 'Referencia o ID contractual').set_value('ATENEA-003-2025')
        next(b for b in app.button if b.label == 'Consultar con filtros').click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.session_state['messages'][-1]['rows']), 1)
        self.assertNotIn('1013640777', str(app.session_state['messages']))

    def test_no_connection_actionable_error(self):
        app = AppTest.from_file(APP, default_timeout=20)
        app.secrets['ORACLE_PAR_URL'] = ''
        app.run()
        next(b for b in app.button if b.label == '¿Cuántos contratos hay en 2026?').click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any('no está configurada' in x.value for x in app.error))
