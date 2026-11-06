import re
from .ai import Assistant, enabled, AIResponseError
from .query import fallback, execute, basic_plan, spec
from .privacy import private_request, fold


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
        ai_only = self.settings.get('AI_ONLY') is True
        if ai_only:
            if not enabled(self.settings) or self.governor.credit_blocked:
                raise ValueError('La IA no está disponible. No se ejecutó ninguna consulta. Intenta nuevamente cuando se restablezca la conexión o el presupuesto.')
            plan, use_ai = None, True
        requested_ai = use_ai is not False
        automatic = use_ai is None
        if automatic and plan is None:
            plan = basic_plan(question)
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
                        if ai_only:
                            raise ValueError('No fue posible interpretar la pregunta con IA. Reformúlala o intenta nuevamente; no se ejecutó una consulta básica.') from None
                        warnings.append(str(error))
                        use_ai = False
                        plan = (spec(operacion='aclarar', aclaracion='No fue posible interpretar toda la pregunta. Usa los filtros para conservar exactamente las condiciones de tu búsqueda.')
                                if automatic else fallback(redactor.clean(question)))
                else:
                    plan = (spec(operacion='aclarar', aclaracion='Esta pregunta necesita interpretación con IA, que no está disponible en este momento. Usa los filtros para precisar la consulta.')
                            if automatic else fallback(redactor.clean(question)))
            if plan.operacion == 'aclarar' or plan.aclaracion:
                return self._result(snapshot, freshness, question, redactor.clean(plan.aclaracion or 'Indica con más precisión qué información necesitas.'), [], warnings, ai_interpreted=interpreted)
            # La lista ya incorpora un conteo completo: no son dos operaciones incompatibles.
            q = fold(question)
            if plan.operacion == 'contar' and re.search(r'\bCUANTOS\b', q) and re.search(r'\bCUALES\b', q):
                plan = plan.model_copy(update={'operacion': 'listar', 'medida': 'contratos'})
            if plan.proveedor and fold(plan.proveedor).strip() == 'UNIVERSIDADES':
                plan = plan.model_copy(update={'proveedor': 'universidad'})
            if plan.estado and fold(plan.estado).strip() in {'VIGENTE', 'VIGENTES', 'ACTIVO', 'ACTIVOS'}:
                plan = plan.model_copy(update={'estado': 'En ejecución'})
            criteria = []
            if plan.texto:
                criteria.append(f'Búsqueda temática por palabras en el objeto contractual: «{plan.texto}». No es una clasificación exhaustiva de temas ni una búsqueda en todos los documentos de SECOP.')
            if re.search(r'\b(?:VIGENTES?|ACTIVOS?)\b', q) and plan.estado and fold(plan.estado).strip() == 'EN EJECUCION':
                criteria.append('Se interpreta «vigentes/activos» como estado reportado «En ejecución», sin comprobar vigencia por fechas ni emitir una conclusión jurídica.')
            if plan.proveedor and fold(plan.proveedor).strip() == 'UNIVERSIDAD':
                criteria.append('Universidades: proveedores cuyo nombre registrado contiene la palabra «universidad». La base no ofrece una clasificación exhaustiva de instituciones de educación superior.')
            warnings.extend(criteria)
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
            named_count = plan.operacion == 'contar' and bool(plan.proveedor)
            if named_count:
                text = (f"En la base consultada se encontraron {result['matching_contracts']} contratos "
                        f"con todas las palabras del nombre «{plan.proveedor}» en el proveedor registrado. "
                        'La búsqueda admite nombres intermedios y apellidos en distinto orden.')
                if not result['matching_contracts']:
                    text += ' No encontrar coincidencias en esta base no demuestra que la persona nunca haya contratado.'
                elif len(display_rows) > 1:
                    warnings.append('Hay varios nombres de proveedor coincidentes. Revisa el desglose y precisa el nombre completo; no se ha verificado que correspondan a una misma persona.')
                text += ' El resultado se limita a los contratos contenidos en esta base.'
            combined_list = plan.operacion == 'listar' and re.search(r'\bCUANTOS\b', q) and re.search(r'\bCUALES\b', q)
            if combined_list:
                text = f"Se encontraron {result['matching_contracts']} contratos en la base consultada. La tabla detalla los contratos coincidentes."
            object_list = plan.operacion == 'listar' and bool(re.search(r'DE QUE SON|\bOBJETOS?\b', q))
            if object_list:
                text = f"Se encontraron {result['matching_contracts']} contratos en la base consultada."
                if display_rows:
                    text += '\n\n' + '\n\n'.join(f"{r['referencia']} — {r.get('objeto') or 'Objeto no informado por la fuente.'}" for r in display_rows[:5])
                    if len(display_rows) > 5:
                        text += '\n\nLa tabla contiene los demás resultados mostrados y sus objetos.'
                else:
                    text += ' No hay coincidencias para los filtros indicados; esto no demuestra ausencia de contratos fuera de esta base.'
            if use_ai and (ai_only or (result['matching_contracts'] and not named_count and not combined_list and not object_list)):
                # El modelo recibe una muestra limitada; la tabla conserva el resultado del motor.
                facts = {'operation': plan.operacion, 'matching_contracts': result['matching_contracts'],
                         'measure': result['measure'], 'rows': display_rows[:3], 'documents': documents[:12],
                         'warnings': warnings, 'version': snapshot.sha256[:12], 'filters': result['filters'],
                         'sample_only': len(display_rows) > 3}
                try:
                    summary = self.assistant.explain(question, facts, redactor)
                    if summary:
                        text = summary
                        summarized = True
                    elif ai_only:
                        reason = getattr(self.assistant, 'last_validation', '')
                        reason = reason if isinstance(reason, str) else ''
                        raise AIResponseError('No se pudo validar la respuesta de IA: ' + (reason or 'redacción no verificable') + '.')
                except ValueError as error:
                    if ai_only:
                        if isinstance(error, AIResponseError):
                            raise error from None
                        trace = error.__traceback__
                        while trace and trace.tb_next:
                            trace = trace.tb_next
                        point = (trace.tb_frame.f_code.co_name + ':' + str(trace.tb_lineno)) if trace else 'sin-traza'
                        raise ValueError('No fue posible generar una respuesta verificable con IA. Referencia de diagnóstico: ' + point) from None
                    warnings.append(str(error))
            return self._result(snapshot, freshness, question, text, display_rows, warnings, sources, result['filters'], interpreted, summarized)

    def _result(self, snapshot, freshness, question, text, rows, warnings, sources=(), filters=None, ai_interpreted=False, ai_summarized=False):
        return {'question': snapshot.redactor.clean(question), 'text': snapshot.redactor.clean(text),
                'ai_interpreted': ai_interpreted, 'ai_summarized': ai_summarized,
                'rows': snapshot.redactor.tree(rows), 'warnings': snapshot.redactor.tree(list(dict.fromkeys(warnings))),
                'sources': snapshot.redactor.tree(list(sources)), 'filters': snapshot.redactor.tree(filters or {}),
                'freshness': {**freshness, 'loaded_at': snapshot.loaded_at, 'modified': snapshot.modified,
                              'version': snapshot.sha256[:12], 'contracts': len(snapshot.rows)}}
