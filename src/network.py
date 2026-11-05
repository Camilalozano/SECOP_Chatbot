import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler

ORACLE_HOST = 'objectstorage.us-ashburn-1.oraclecloud.com'
SECOP_HOST = 'community.secop.gov.co'


class SourceError(ValueError):
    """Mensaje público sin URL privada ni contenido de respuesta."""
    def __init__(self, message, retryable=False):
        super().__init__(message)
        self.retryable = retryable


def allowed(url, host, path=None):
    try:
        p = urlparse(str(url))
        return p.scheme == 'https' and p.hostname == host and p.port in (None, 443) and not p.username and not p.password and (path is None or p.path == path)
    except ValueError:
        return False


class SameHost(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed(newurl, urlparse(req.full_url).hostname):
            raise SourceError('La fuente redirigió a una dirección no permitida.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _fetch_once(url, limit, headers=None, opener=None):
    opener = opener or build_opener(SameHost()).open
    try:
        req = Request(url, headers={'User-Agent': 'SECOPChatbot/1.0', **(headers or {})})
        with opener(req, timeout=20) as response:
            declared = response.headers.get('Content-Length', '')
            if declared and int(declared) > limit:
                raise SourceError('El archivo supera el tamaño permitido.')
            data = response.read(limit + 1)
            if not data or len(data) > limit:
                raise SourceError('Respuesta vacía o demasiado grande.')
            return data, dict(response.headers)
    except HTTPError as error:
        if error.code == 304:
            return None, {}
        raise SourceError(f'La fuente no está disponible (HTTP {error.code}).', error.code in {429, 500, 502, 503, 504}) from None
    except (URLError, OSError, TimeoutError, ValueError) as error:
        if isinstance(error, SourceError):
            raise
        raise SourceError('No fue posible consultar la fuente. Intente nuevamente.', True) from None


def fetch(url, limit, headers=None, opener=None):
    for attempt in range(2):
        try:
            return _fetch_once(url, limit, headers, opener)
        except SourceError as error:
            if not error.retryable or attempt == 1:
                raise
            time.sleep(0.3)


def api_rows(dataset, params):
    if dataset not in {'dmgg-8hin', 'h4m3-b4e2', 'nbae-kzan', '3skv-9na7', 'kgcd-kt7i', 'f8va-cf4m', 'jbjy-vk9h'}:
        raise SourceError('Fuente documental no permitida.')
    data, _ = fetch('https://www.datos.gov.co/resource/' + dataset + '.json?' + urlencode(params), 8 * 1024 * 1024)
    try:
        result = json.loads(data)
        if not isinstance(result, list) or not all(isinstance(r, dict) for r in result):
            raise ValueError()
        return result
    except (ValueError, TypeError):
        raise SourceError('La fuente devolvió un formato incompatible.') from None
