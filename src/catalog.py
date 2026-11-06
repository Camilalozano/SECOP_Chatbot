import csv
import hashlib
import io
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone, date
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from .network import fetch, allowed, ORACLE_HOST, SourceError
from .privacy import Redactor, safe_secop_url

FIELDS = {
    'id': 'id_contrato', 'referencia': 'referencia_del_contrato (contratos_electronicos)',
    'objeto': 'descripcion_del_proceso (contratos_electronicos)', 'anio': 'año_inferido',
    'valor': 'valor_del_contrato (contratos_electronicos)', 'pagado': 'valor_pagado (contratos_electronicos)',
    'inicio': 'fecha_de_inicio_del_contrato (contratos_electronicos)',
    'fin': 'fecha_de_fin_del_contrato (contratos_electronicos)',
    'firma': 'fecha_de_firma (contratos_electronicos)', 'estado': 'estado_contrato (contratos_electronicos)',
    'tipo': 'tipo_de_contrato (contratos_electronicos)', 'modalidad': 'modalidad_de_contratacion (contratos_electronicos)',
    'dependencia': 'paa::dependencia_solicitante', 'proveedor': 'proveedor_adjudicado (contratos_electronicos)',
    'url_secop': 'urlproceso (contratos_electronicos)',
    'origen': '_origen',
}
LABELS = {'id': 'ID SECOP', 'referencia': 'Contrato', 'objeto': 'Objeto', 'anio': 'Año reportado o inferido',
          'valor': 'Valor contractual reportado (COP)', 'pagado': 'Valor pagado reportado (COP)',
          'inicio': 'Inicio', 'fin': 'Finalización reportada', 'firma': 'Firma', 'estado': 'Estado',
          'tipo': 'Tipo de contrato', 'modalidad': 'Modalidad', 'dependencia': 'Dependencia solicitante del PAA',
          'proveedor': 'Proveedor', 'url_secop': 'Fuente SECOP', 'origen': 'Origen del registro'}


def money(value):
    value = str(value or '').strip().replace('$', '').replace(' ', '')
    if not value or value.lower() in {'nan', 'none', 'null', 'no definido'}:
        return None
    if re.fullmatch(r'\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?', value):
        value = value.replace('.', '').replace(',', '.')
    elif ',' in value and '.' not in value:
        value = value.replace(',', '.')
    try:
        number = Decimal(value)
        return number.quantize(Decimal('0.01')) if number.is_finite() and number >= 0 else None
    except InvalidOperation:
        return None


def day(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


@dataclass
class Snapshot:
    rows: list
    redactor: Redactor
    sha256: str
    etag: str
    modified: str
    loaded_at: str
    warnings: list


def parse(data, secrets=()):
    if len(data) > 50 * 1024 * 1024:
        raise SourceError('La base supera 50 MB.')
    try:
        content = data.decode('utf-8-sig')
        try:
            dialect = csv.Sniffer().sniff(content[:32768], delimiters=',;\t')
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(io.StringIO(content, newline=''), dialect)
        headers = next(reader)
        if len(headers) != len(set(headers)) or not all(FIELDS[k] in headers for k in ('id', 'referencia', 'objeto', 'valor')):
            raise SourceError('La nueva base tiene columnas faltantes o duplicadas.')
        raw = []
        for values in reader:
            if not values or not any(values):
                continue
            if len(values) != len(headers) or len(raw) >= 200000:
                raise SourceError('La base tiene filas incompatibles o supera 200.000 registros.')
            raw.append(dict(zip(headers, values)))
        if not raw:
            raise SourceError('La base no contiene contratos.')
    except (UnicodeError, csv.Error, StopIteration):
        raise SourceError('No se pudo interpretar la nueva base CSV.') from None
    private = [v for row in raw for k, v in row.items() if any(t in k.lower() for t in ('documento_proveedor', 'documento_supervisor', 'documento_ordenador', 'identificacion', 'identificaci', 'cuenta', 'banc'))]
    redactor = Redactor(private, secrets)
    result, seen, warnings = [], set(), []
    invalid_numbers = 0
    for row in raw:
        cid = row.get(FIELDS['id'], '').strip().upper()
        outside = str(row.get('_origen', '')).strip().lower() == 'no_secop'
        if not re.fullmatch(r'CO1\.PCCNTR\.\d+', cid) and not (outside and re.fullmatch(r'CO1\.PCCNTR\.\d+-20\d{2}', cid)):
            raise SourceError('La base contiene contratos sin un ID SECOP válido.')
        if cid in seen:
            raise SourceError('La nueva base contiene IDs contractuales repetidos. Se conserva la versión anterior para evitar duplicar cifras.')
        seen.add(cid)
        public = {k: redactor.clean(row.get(col, '')) for k, col in FIELDS.items()
                  if k not in {'valor', 'pagado', 'inicio', 'fin', 'firma', 'anio', 'id', 'url_secop'}}
        public['id'] = cid
        for k in ('valor', 'pagado'):
            public[k] = money(row.get(FIELDS[k]))
            if public[k] is None and row.get(FIELDS[k], '').strip():
                invalid_numbers += 1
        for k in ('inicio', 'fin', 'firma'):
            public[k] = day(row.get(FIELDS[k], ''))
        # Referencia como origen primario; la fecha de descarga no determina el año contractual.
        years = set(re.findall(r'(?<!\d)(20\d{2})(?!\d)', public['referencia']))
        reported = str(row.get(FIELDS['anio'], ''))
        public['anio'] = int(next(iter(years))) if len(years) == 1 else int(reported) if re.fullmatch(r'20\d{2}', reported) else None
        public['url_secop'] = safe_secop_url(row.get(FIELDS['url_secop'], ''))
        result.append(public)
    if invalid_numbers:
        warnings.append(f'{invalid_numbers} valores monetarios vacíos o incompatibles se excluyen de las sumas; no se convierten en cero.')
    return result, redactor, warnings


class CatalogStore:
    def __init__(self, url, secrets=(), loader=fetch):
        self.url, self.secrets, self.loader = url, secrets, loader
        self.snapshot = None
        self.lock = threading.Lock()

    def refresh(self):
        with self.lock:
            checked = datetime.now(timezone.utc).isoformat()
            try:
                if not allowed(self.url, ORACLE_HOST) or '/p/' not in self.url:
                    raise SourceError('La conexión a la base no está configurada.')
                headers = {'If-None-Match': self.snapshot.etag} if self.snapshot and self.snapshot.etag else {}
                data, meta = self.loader(self.url, 50 * 1024 * 1024, headers=headers)
                meta = {str(k).lower(): v for k, v in meta.items()}
                if data is None:
                    if self.snapshot is None:
                        raise SourceError('La fuente no entregó una versión inicial.')
                else:
                    digest = hashlib.sha256(data).hexdigest()
                    if self.snapshot is None or digest != self.snapshot.sha256:
                        rows, redactor, warnings = parse(data, (self.url, *self.secrets))
                        self.snapshot = Snapshot(rows, redactor, digest, meta.get('etag', ''),
                                                 meta.get('last-modified', ''), checked, warnings)
                    else:
                        self.snapshot.etag = meta.get('etag', self.snapshot.etag)
                return self.snapshot, {'checked_at': checked, 'stale': False, 'notice': ''}
            except SourceError as error:
                if self.snapshot is None:
                    raise
                return self.snapshot, {'checked_at': checked, 'stale': True,
                                       'notice': str(error) + ' Se utiliza una copia anterior, cargada el ' + self.snapshot.loaded_at + '.'}
