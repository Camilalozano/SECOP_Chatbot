"""Solo lectura de fuentes oficiales. Máximo tres PDF por pregunta documental."""
import hashlib
import io
import json
import re
import threading
import zipfile
import zlib
from collections import OrderedDict
from pypdf import PdfReader
from .network import api_rows, fetch, allowed, SECOP_HOST, SourceError
from .privacy import fold, safe_secop_url
from .obligations import extract_obligations

DocumentError = SourceError


def document_url(row):
    value = row.get('url_descarga_documento', '')
    return value.get('url', '') if isinstance(value, dict) else str(value or '')


def query(endpoint, params, opener):
    return api_rows(endpoint.rsplit('/', 1)[-1].split('.')[0], params)


def read_pages(data):
    if len(data) > 20 * 1024 * 1024 or not data.lstrip().startswith(b'%PDF'):
        raise DocumentError('No es un PDF de hasta 20 MB.')
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(''):
            raise ValueError()
        if len(reader.pages) > 150:
            raise DocumentError('El PDF supera 150 páginas.')
        pages = [page.extract_text() or '' for page in reader.pages]
        if sum(len(re.sub(r'\s', '', p)) for p in pages) < 100:
            raise DocumentError('El PDF requiere OCR o no tiene texto suficiente.')
        return pages
    except DocumentError:
        raise
    except Exception:
        raise DocumentError('No se pudo leer el PDF; puede estar dañado o protegido.') from None


def source_score(row, reference):
    name = fold(row.get('nombre_archivo', ''))
    ext = str(row.get('extensi_n', '')).lower().lstrip('.')
    if ext not in {'pdf', 'zip'}:
        return -1
    if any(w in name for w in ('INFORME', 'CUENTA', 'POLIZA', 'MODIFICACION', 'OTROSI', 'CESION', 'ANTECEDENTE', 'EXPERIENCIA', 'ADICION')):
        return -1
    score = 10 if ext == 'zip' else 0
    if any(w in name for w in ('MINUTA', 'CLAUSULADO', 'CONVENIO')):
        score += 80
    if 'PREVIO' in name:
        score += 50
    if re.sub(r'\W', '', reference) in re.sub(r'\W', '', name):
        score += 100
    return score


def normalized(value):
    return re.sub(r'[\s\-–—]+', '', fold(value))


class Documents:
    def __init__(self, lookup=None, download=fetch, reader=read_pages):
        self.lookup = lookup
        self.download, self.reader = download, reader
        self.cache = OrderedDict()
        self.lock = threading.Lock()

    def answer(self, contract, snapshot, question, operation):
        from .secop_catalog import lookup_documents
        listing = self.lookup or (lambda cid: lookup_documents(cid, query, None))
        rows, warnings = listing(contract['id'])
        clean = snapshot.redactor.clean
        inventory = []
        for row in rows:
            url = document_url(row)
            if not allowed(url, SECOP_HOST, '/Public/Archive/RetrieveFile/Index'):
                continue
            inventory.append({'archivo': clean(row.get('nombre_archivo', 'Documento')),
                              'fecha': clean(row.get('fecha_carga', '')),
                              'asociacion': row.get('_asociacion', 'contrato'), 'url_secop': url})
        warnings = [clean(w) for w in warnings]
        if operation == 'documentos':
            return {'inventory': inventory[:100], 'documents': [], 'warnings': warnings,
                    'text': f'Se encontraron {len(inventory)} documentos con enlaces oficiales. Datos Abiertos puede tener rezago frente al portal SECOP.'}
        version = hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()
        key = (contract['id'], snapshot.sha256, version)
        with self.lock:
            cached = self.cache.get(key)
        if cached is not None:
            return {**cached, 'warnings': warnings + cached['warnings']}
        candidates = sorted((r for r in rows if source_score(r, contract['referencia']) > 0),
                            key=lambda r: source_score(r, contract['referencia']), reverse=True)
        documents, failures, attempts = [], [], 0
        seen, downloaded, retrievals = set(), 0, 0
        # No se descargan archivos personales de soporte ni todo el expediente.
        for row in candidates:
            if attempts >= 3 or retrievals >= 3 or documents or downloaded >= 100 * 1024 * 1024:
                break
            url = document_url(row)
            if url in seen or not allowed(url, SECOP_HOST, '/Public/Archive/RetrieveFile/Index'):
                continue
            seen.add(url)
            retrievals += 1
            try:
                data, _ = self.download(url, min(50 * 1024 * 1024, 100 * 1024 * 1024 - downloaded),
                                        headers={'Referer': 'https://community.secop.gov.co/'})
                downloaded += len(data)
                pdfs = []
                if str(row.get('extensi_n', '')).lower().lstrip('.') == 'zip':
                    with zipfile.ZipFile(io.BytesIO(data)) as archive:
                        members = archive.infolist()
                        if len(members) > 500 or sum(m.file_size for m in members) > 100 * 1024 * 1024:
                            raise DocumentError('El ZIP supera los límites de lectura segura.')
                        for member in sorted(members, key=lambda m: source_score({'nombre_archivo': m.filename, 'extensi_n': 'pdf'}, contract['referencia']), reverse=True):
                            if attempts + len(pdfs) >= 3:
                                break
                            if member.is_dir() or not member.filename.lower().endswith('.pdf') or member.flag_bits & 1:
                                continue
                            name = member.filename.replace('\\', '/').rsplit('/', 1)[-1]
                            if source_score({'nombre_archivo': name, 'extensi_n': 'pdf'}, contract['referencia']) <= 0:
                                continue
                            if member.file_size > 20 * 1024 * 1024:
                                failures.append('Un PDF candidato supera 20 MB.'); continue
                            with archive.open(member) as stream:
                                pdfs.append((member.filename, stream.read(20 * 1024 * 1024 + 1)))
                else:
                    pdfs = [(row.get('nombre_archivo', 'Documento.pdf'), data)]
                for name, pdf in pdfs:
                    if attempts >= 3:
                        break
                    attempts += 1
                    try:
                        raw_pages = self.reader(pdf)
                        # Rechazar documentos que mencionan expresamente otra referencia contractual.
                        refs = re.findall(r'ATENEA[\s-]+(?:\d+)[\s-]+20\d{2}\b', '\n'.join(raw_pages), re.I)
                        target = normalized(contract['referencia'])
                        if refs and target not in {normalized(r) for r in refs}:
                            failures.append('Se excluyó un documento que corresponde a otra referencia contractual.'); continue
                        if row.get('_asociacion') == 'proceso' and target not in {normalized(r) for r in refs}:
                            failures.append('Un documento del proceso no permite comprobar la referencia contractual.'); continue
                        pages = [clean(p) for p in raw_pages]
                        items = extract_obligations('', pages)
                        if not items:
                            failures.append(clean(name) + ': no se identificaron obligaciones específicas de la contraparte.'); continue
                        for item in items:
                            documents.append({'cita': f'D{len(documents) + 1}', 'archivo': clean(name),
                                              'pagina': item.get('pagina'), 'numero': item['numero_obligacion'],
                                              'texto': clean(item['obligaciones_especificas']),
                                              'url_secop': url, 'sha256': hashlib.sha256(pdf).hexdigest()})
                            failures.extend(clean(w) for w in item.get('advertencias', []))
                        if any('MODIFICACION' in fold(r.get('nombre_archivo', '')) or 'OTROSI' in fold(r.get('nombre_archivo', '')) for r in rows):
                            failures.append('Existen documentos de modificación; las obligaciones corresponden al soporte citado y pueden requerir revisión.')
                        break
                    except DocumentError as error:
                        failures.append(clean(name) + ': ' + str(error))
            except (DocumentError, zipfile.BadZipFile, RuntimeError, OSError, EOFError, zlib.error, NotImplementedError):
                failures.append('No se pudo recuperar o abrir uno de los archivos candidatos.')
        if not documents:
            failures.append('No se localizaron obligaciones en los soportes revisados. Esto no demuestra que el contrato carezca de obligaciones. El piloto revisa hasta tres archivos fuente y tres PDF candidatos.')
        result = {'inventory': inventory[:100], 'documents': documents,
                  'warnings': list(dict.fromkeys(failures)), 'text': f'{len(documents)} obligaciones específicas localizadas en el soporte citado.' if documents else 'Sin obligaciones verificables en los PDF revisados.'}
        if documents:
            with self.lock:
                self.cache[key] = result
                while len(self.cache) > 8:
                    self.cache.popitem(last=False)
        return {**result, 'warnings': warnings + result['warnings']}
