import json
import unittest
from pathlib import Path
from unittest.mock import Mock
from src.catalog import CatalogStore
from src.service import ChatService
from src.query import fallback
from src.limits import Governor
from tests.helpers import fixture, URL


class AcceptanceTests(unittest.TestCase):
    def test_thirty_representative_questions(self):
        cases = json.loads(Path(__file__).with_name('cases.json').read_text(encoding='utf-8'))
        self.assertEqual(len(cases), 30)
        store = CatalogStore(URL, loader=Mock(return_value=(fixture(), {'ETag': 'v1'})))
        documents = Mock()
        service = ChatService(store, documents, Governor(), {})
        for case in cases:
            with self.subTest(question=case['question']):
                if not case.get('private'):
                    plan = fallback(case['question'])
                    self.assertEqual(plan.operacion, case['operation'])
                result = service.answer(case['question'], 'test')
                if case.get('private'):
                    self.assertTrue(result['private']); continue
                if 'total' in case:
                    self.assertEqual(result['rows'][0]['resultado'], case['total'])
                if 'groups' in case:
                    self.assertEqual(len(result['rows']), case['groups'])
                if 'matches' in case:
                    self.assertEqual(len(result['rows']), case['matches'])
                if case.get('clarify'):
                    self.assertTrue(result['text'])
                self.assertNotIn(URL, json.dumps(result, default=str))
                self.assertNotIn('1013640777', json.dumps(result, default=str))
        documents.answer.assert_not_called()
