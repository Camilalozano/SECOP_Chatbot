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
        'HOSTING_AND_ORACLE_QUOTA_VERIFIED']


def configuration():
    values = {}
    for key in KEYS:
        try:
            value = st.secrets.get(key, os.environ.get(key, ''))
        except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
            value = os.environ.get(key, '')
        if key in {'AI_ENABLED', 'INCLUDED_CREDITS_ONLY_VERIFIED', 'NO_PAID_FALLBACK_VERIFIED', 'HOSTING_AND_ORACLE_QUOTA_VERIFIED'}:
            value = value is True or str(value).lower() == 'true'
        if key in {'AI_TURN_RESERVE_USD', 'AI_RUN_BUDGET_USD'}:
            try:
                value = max(0.0, float(value)) if value != '' else (0.05 if key == 'AI_TURN_RESERVE_USD' else 0.0)
            except (ValueError, TypeError):
                value = 0.0
        values[key] = value
    values['OPENAI_MODEL'] = values['OPENAI_MODEL'] or 'gpt-5-mini'
    return values


@st.cache_resource(show_spinner=False)
def shared_service(settings, revision='2026-11-05.4'):
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
    for warning in result['warnings']:
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
    service = shared_service(settings)
    st.session_state.setdefault('session_id', uuid.uuid4().hex)
    st.session_state.setdefault('messages', [])
    available = enabled(settings) and not service.governor.credit_blocked
    if available:
        st.info('IA disponible · Hasta 5 preguntas por sesión cada hora. Los cálculos se realizan sobre la base consultada.')
    else:
        st.info('Modo de consulta sin IA. Puedes buscar contratos, usar filtros y consultar obligaciones. La IA se habilitará únicamente con créditos verificados.')
    st.caption('No ingreses cédulas, datos bancarios ni información privada. Este piloto ofrece información contractual y no certifica cumplimiento ni emite conceptos jurídicos.')
    prompt = None
    cols = st.columns(3)
    for col, text in zip(cols, ['¿Cuántos contratos hay en 2026?', 'Contratos que terminan en 60 días', 'Obligaciones de ATENEA-582-2025']):
        if col.button(text, width='stretch'):
            prompt = text
    plan = None
    with st.expander('Buscar y calcular con filtros'):
        with st.form('filters'):
            left, right = st.columns(2)
            reference = left.text_input('Referencia o ID contractual', placeholder='ATENEA-003-2025')
            object_text = right.text_input('Palabras del objeto')
            provider = left.text_input('Proveedor')
            year = right.number_input('Año (0 = todos)', min_value=0, max_value=2100, value=0, step=1)
            status = left.text_input('Estado')
            department = right.text_input('Dependencia solicitante del PAA')
            modality = left.text_input('Modalidad')
            days = right.number_input('Terminan en próximos días (0 = sin filtro)', min_value=0, max_value=366, value=0, step=1)
            operation = left.selectbox('Qué consultar', ['Contratos', 'Cantidad', 'Valor reportado (COP)', 'Pagado reportado (COP)', 'Obligaciones específicas', 'Documentos SECOP', 'Agrupar'])
            group = right.selectbox('Agrupar por', ['dependencia', 'anio', 'estado', 'proveedor', 'modalidad', 'tipo'])
            measure = right.selectbox('Medida al agrupar', ['contratos', 'valor', 'pagado'])
            if st.form_submit_button('Consultar con filtros', type='primary'):
                operations = {'Contratos': 'listar', 'Cantidad': 'contar', 'Valor reportado (COP)': 'sumar', 'Pagado reportado (COP)': 'sumar', 'Obligaciones específicas': 'obligaciones', 'Documentos SECOP': 'documentos', 'Agrupar': 'agrupar'}
                plan = spec(operacion=operations[operation], referencia=reference.strip() or None,
                            texto=object_text.strip() or None, proveedor=provider.strip() or None,
                            anio=int(year) or None, estado=status.strip() or None, dependencia=department.strip() or None,
                            modalidad=modality.strip() or None, vence_dias=int(days) or None,
                            agrupar_por=group if operation == 'Agrupar' else None,
                            medida=measure if operation == 'Agrupar' else 'valor' if operation.startswith('Valor') else 'pagado' if operation.startswith('Pagado') else 'contratos')
                prompt = 'Consulta mediante filtros'
    typed = st.chat_input('Pregunta por un contrato, un total, un plazo o sus obligaciones', max_chars=1200)
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
            st.error('No fue posible completar esta consulta. Intenta nuevamente o utiliza los filtros.')
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
