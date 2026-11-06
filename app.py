"""Piloto público. Los secretos y las columnas privadas nunca se entregan al navegador."""
import csv
import io
import os
import re
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
import streamlit as st
from src.ai import enabled
from src.catalog import CatalogStore, LABELS
from src.documents import Documents
from src.limits import Governor
from src.query import spec
from src.service import ChatService
from src.privacy import safe_secop_url

KEYS = ['ORACLE_PAR_URL', 'OPENAI_API_KEY', 'OPENAI_MODEL', 'AI_ENABLED', 'INCLUDED_CREDITS_ONLY_VERIFIED',
        'NO_PAID_FALLBACK_VERIFIED', 'CREDITS_VERIFIED_UNTIL', 'AI_TURN_RESERVE_USD', 'AI_RUN_BUDGET_USD',
        'HOSTING_AND_ORACLE_QUOTA_VERIFIED', 'AI_CREDIT_MODE', 'PREPAID_CREDITS_VERIFIED',
        'AUTO_RECHARGE_DISABLED_VERIFIED', 'VERIFIED_CREDIT_BALANCE_USD']


def configuration():
    values = {}
    for key in KEYS:
        try:
            value = st.secrets.get(key, os.environ.get(key, ''))
        except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
            value = os.environ.get(key, '')
        if key in {'AI_ENABLED', 'INCLUDED_CREDITS_ONLY_VERIFIED', 'NO_PAID_FALLBACK_VERIFIED', 'HOSTING_AND_ORACLE_QUOTA_VERIFIED',
                   'PREPAID_CREDITS_VERIFIED', 'AUTO_RECHARGE_DISABLED_VERIFIED'}:
            value = value is True or str(value).lower() == 'true'
        if key in {'AI_TURN_RESERVE_USD', 'AI_RUN_BUDGET_USD', 'VERIFIED_CREDIT_BALANCE_USD'}:
            try:
                value = max(0.0, float(value)) if value != '' else (0.05 if key == 'AI_TURN_RESERVE_USD' else 0.0)
            except (ValueError, TypeError):
                value = 0.0
        values[key] = value
    values['OPENAI_MODEL'] = values['OPENAI_MODEL'] or 'gpt-5-mini'
    values['AI_CREDIT_MODE'] = values['AI_CREDIT_MODE'] or 'included'
    return values


@st.cache_resource(show_spinner=False)
def shared_service(settings, revision='2026-11-05.ai-review.1'):
    return ChatService(CatalogStore(settings['ORACLE_PAR_URL'], (settings['OPENAI_API_KEY'],)),
                       Documents(), Governor(), settings)


def local_time(value):
    if not value:
        return 'No informada por la fuente'
    try:
        from email.utils import parsedate_to_datetime
        dt = datetime.fromisoformat(value.replace('Z', '+00:00')) if re.match(r'^\d{4}-', value) else parsedate_to_datetime(value)
        return dt.astimezone(ZoneInfo('America/Bogota')).strftime('%d/%m/%Y %H:%M · Bogotá')
    except (ValueError, TypeError):
        return 'No informada por la fuente'


def render(result, index):
    st.write(result['text'])
    if result.get('ai_interpreted'):
        st.caption('Consulta interpretada con IA · Cálculos verificados por el motor de datos'
                   + (' · Resumen generado con IA' if result.get('ai_summarized') else ''))
    elif not result.get('private'):
        st.caption('Consulta sin respuesta de IA')
    for warning in result['warnings']:
        if 'registros están identificados como no_secop por la base' not in warning:
            st.warning(warning)
    rows = result['rows']
    if rows:
        public_rows = [{LABELS.get(k, {'resultado': 'Resultado', 'pagina': 'Página', 'archivo': 'Archivo', 'numero': 'Número', 'texto': 'Obligación específica', 'cita': 'Cita', 'fecha': 'Fecha de carga', 'asociacion': 'Asociación'}.get(k, k)): v
                        for k, v in row.items() if k not in {'sha256'}} for row in rows]
        for row in public_rows:
            if 'Fuente SECOP' in row:
                row['Fuente SECOP'] = safe_secop_url(row['Fuente SECOP'])
        st.dataframe(public_rows, hide_index=True, width='stretch')
        output = io.StringIO(newline='')
        writer = csv.DictWriter(output, fieldnames=list(public_rows[0]), extrasaction='ignore')
        writer.writeheader(); writer.writerows(public_rows)
        st.download_button('Descargar este resultado', ('\ufeff' + output.getvalue()).encode('utf-8'),
                           'resultado_contractual.csv', 'text/csv', key=f'download_{index}')
    fresh = result.get('freshness')
    if fresh:
        st.caption('Comprobación del PAR: ' + local_time(fresh['checked_at'])
                   + ' · Versión: ' + fresh['version'] + ' · ' + str(fresh['contracts']) + ' contratos')
        st.caption('Modificación del archivo en Oracle: ' + local_time(fresh['modified'])
                   + '. Esta fecha no garantiza la actualización de cada registro en SECOP.')
    with st.expander('Ver fuentes y criterios de consulta'):
        st.write('Base contractual exportada desde Oracle; campos originales e inferidos según su definición. Dependencia corresponde al PAA.')
        if result.get('filters'):
            st.write({LABELS.get(k, {'operacion': 'Consulta', 'medida': 'Medida', 'agrupar_por': 'Agrupación', 'vence_dias': 'Vencimiento en días', 'texto': 'Palabras del objeto'}.get(k, k)): v
                      for k, v in result['filters'].items()})
        # Las URL se validan en el servidor; nunca se renderiza el PAR.
        links = set()
        for source in result.get('sources', []):
            url = source.get('url_secop', '')
            if url and url not in links:
                if safe_secop_url(url):
                    st.link_button('Abrir fuente oficial · ' + source.get('archivo', 'SECOP'), safe_secop_url(url))
                    links.add(url)


def main():
    st.set_page_config(page_title='Consulta contractual · SECOP', page_icon='💬', layout='wide')
    st.title('Consulta contractual')
    st.caption('Piloto público · Contratos y obligaciones con fuentes verificables')
    settings = configuration()
    settings['AI_ONLY'] = True
    service = shared_service(settings)
    st.session_state.setdefault('session_id', uuid.uuid4().hex)
    st.session_state.setdefault('messages', [])
    available = enabled(settings) and service.governor.ai_available(settings['AI_RUN_BUDGET_USD'], settings['AI_TURN_RESERVE_USD'])
    st.subheader('Pregúntale a la base de datos')
    with st.container():
        typed = st.chat_input('Pregunta por un contrato, un total, un plazo o sus obligaciones', max_chars=1200)
    if available:
        st.caption('Todas las preguntas se interpretan y responden con IA. Hasta 5 preguntas por sesión cada hora.')
    else:
        st.info('La IA no está disponible en este momento. No se resolverán consultas hasta recuperar la conexión o el presupuesto.')
    prompt = None
    plan = None
    if typed:
        prompt, plan = typed, None
    if prompt:
        try:
            with st.spinner('Comprobando la base y consultando las fuentes…'):
                result = service.answer(prompt, st.session_state['session_id'], plan)
            st.session_state['messages'].append(result)
            st.session_state['messages'] = st.session_state['messages'][-8:]
        except ValueError as error:
            st.error(str(error))
        except Exception:
            # Ningún traceback, solicitud, credencial o contenido privado llega al visitante.
            st.error('No fue posible completar esta consulta. Intenta nuevamente.')
    for index, result in enumerate(st.session_state['messages']):
        with st.chat_message('user'):
            st.text(result.get('question', 'Consulta'))
        with st.chat_message('assistant'):
            render(result, index)
    if st.session_state['messages'] and st.button('Borrar conversación de esta sesión'):
        st.session_state['messages'] = []
        st.rerun()


if __name__ == '__main__':
    main()
