import unittest
from src.catalog import parse, FIELDS
from src.query import execute, spec
from tests.helpers import fixture


class TopicPhraseTests(unittest.TestCase):
    def test_topic_is_not_matched_by_unrelated_agency_words(self):
        def update(rows):
            for row, text in zip(rows, ['Apoyar ciencia de datos.', 'Proyectos de ciencia datos e innovación.',
                                       'Seguridad de datos de la Agencia de Ciencia y Tecnología.', 'Servicios de metadatos científicos.']):
                row[FIELDS['objeto']] = text
        rows = parse(fixture(update))[0]
        for phrase in ['ciencia datos', 'ciencia de datos']:
            result = execute(rows, spec(texto=phrase))
            self.assertEqual(result['matching_contracts'], 2)
