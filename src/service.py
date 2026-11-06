import re
from .ai import Assistant, enabled
from .query import fallback, execute
from .privacy import private_request


class ChatService:
    def __init__(self, catalog, documents, governor, settings, assistant=None):
        self.catalog, self.documents, self.governor, self.settings = catalog, documents, governor, settings
        self.assistant = assistant or Assistant(settings, governor)

    def answer(self, question, session, plan=None, use_ai=None):
        question = str(question).strip()
        if not question or len(question) > 1200:
            raise ValueError('Escribe una pregunta de hasta 1.200 caracteres.')
        if private_request(question):
            return {'text': 'Este piloto no publica identificaciones personales, credenciales, datos bancarios ni la base completa. Puedes consultar información contractual y obligaciones con fuentes.',
                    'rows': [], 'warnings': [], 'sources': [], 'private': True, 'question': '[consulta excluida por privacidad]'}
        requested_ai = use_ai is not False
        use_ai = plan is None and requested_ai and enabled(self.settings) and not self.governor.credit_blocked
        interpreted = False
        summarized = False
        with self.governor.turn(session, ai=use_ai,
                                budget=float(self.settings.get('AI_RUN_BUDGET_USD', 0)),
                                reserve=float(self.settings.get('AI_TURN_RESERVE_USD', 0.05))):
            snapshot, freshness = self.catalog.refresh()
            redactor = snapshot.redactor
            warnings = list(snapshot.warnings)
            if freshness['notice']:
                warnings.append(freshness['notice'])
            if plan is None:
                if use_ai:
                    try:
                        plan = self.assistant.interpret(question, redactor)
                        interpreted = True
                    except ValueError as error:
                        warnings.append(str(error))
                        use_ai = False
                        plan = fallback(redactor.clean(question))
                else:
                    plan = fallback(redactor.clean(question))
            if plan.operacion == 'aclarar' or plan.aclaracion:
                return self._result(snapshot, freshness, question, redactor.clean(plan.aclaracion or 'Indica con más precisión qué información necesitas.'), [], warnings, ai_interpreted=interpreted)
            result = execute(snapshot.rows, plan)
            sources = []
            documents = []
            if result['truncated']:
                warnings.append('La tabla muestra los primeros 100 resultados. Los totales se calculan sobre todas las coincidencias; acota los filtros para ver otros contratos.')
            if result['missing_values']:
                warnings.append(f"{result['missing_values']} contratos sin valor válido se excluyeron de la suma.")
            if plan.operacion in ('documentos', 'obligaciones'):
                if not plan.referencia or result['matching_contracts'] != 1:
                    text = 'Indica una referencia contractual completa y única. Si hay varias coincidencias, selecciona el contrato antes de consultar documentos.'
                    return self._result(snapshot, freshness, question, text, result['rows'], warnings, ai_interpreted=interpreted)
                if not re.fullmatch(r'CO1\.PCCNTR\.\d+', result['rows'][0]['id']) or result['rows'][0].get('origen', '').lower() == 'no_secop':
                    return self._result(snapshot, freshness, question, 'La base identifica este registro fuera de SECOP II. No se pueden atribuir documentos oficiales a este identificador.', result['rows'], warnings, ai_interpreted=interpreted)
                document_result = self.documents.answer(result['rows'][0], snapshot, redactor.clean(question), plan.operacion)
                text, documents = document_result['text'], document_result['documents']
                warnings.extend(document_result['warnings'])
                sources = documents
                display_rows = documents or document_result['inventory']
            else:
                display_rows = result['rows']
                if plan.operacion in ('contar', 'sumar', 'agrupar'):
                    text = f"Resultado calculado sobre {result['matching_contracts']} contratos coincidentes."
                    if plan.medida != 'contratos':
                        text += ' Los valores son montos reportados en pesos colombianos (COP), no una reconstrucción del valor inicial o vigente.'
                else:
                    text = f"Se encontraron {result['matching_contracts']} contratos con estos filtros."
                    sources = [{'archivo': r['referencia'], 'url_secop': r['url_secop']} for r in display_rows if r.get('url_secop')]
            if use_ai and result['matching_contracts']:
                # El modelo recibe una muestra limitada; la tabla conserva el resultado del motor.
                facts = {'operation': plan.operacion, 'matching_contracts': result['matching_contracts'],
                         'measure': result['measure'], 'rows': display_rows[:10], 'documents': documents[:12],
                         'warnings': warnings, 'version': snapshot.sha256[:12], 'filters': result['filters'],
                         'sample_only': len(display_rows) > 10}
                try:
                    summary = self.assistant.explain(question, facts, redactor)
                    if summary:
                        text = summary
                        summarized = True
                except ValueError as error:
                    warnings.append(str(error))
            return self._result(snapshot, freshness, question, text, display_rows, warnings, sources, result['filters'], interpreted, summarized)

    def _result(self, snapshot, freshness, question, text, rows, warnings, sources=(), filters=None, ai_interpreted=False, ai_summarized=False):
        return {'question': snapshot.redactor.clean(question), 'text': snapshot.redactor.clean(text),
                'ai_interpreted': ai_interpreted, 'ai_summarized': ai_summarized,
                'rows': snapshot.redactor.tree(rows), 'warnings': snapshot.redactor.tree(list(dict.fromkeys(warnings))),
                'sources': snapshot.redactor.tree(list(sources)), 'filters': snapshot.redactor.tree(filters or {}),
                'freshness': {**freshness, 'loaded_at': snapshot.loaded_at, 'modified': snapshot.modified,
                              'version': snapshot.sha256[:12], 'contracts': len(snapshot.rows)}}
