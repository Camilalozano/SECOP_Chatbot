"""La vista pública se construye por inclusión explícita, nunca por ocultar columnas UI."""
import re
import unicodedata
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse


def fold(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(value or '')) if not unicodedata.combining(c)).upper()


def safe_secop_url(value):
    if isinstance(value, dict):
        value = value.get('url', '')
    try:
        p = urlparse(str(value or ''))
        if p.scheme == 'https' and p.hostname == 'community.secop.gov.co' and p.port in (None, 443) and not p.username and not p.password:
            params = parse_qs(p.query)
            if p.path == '/Public/Archive/RetrieveFile/Index':
                document = params.get('DocumentId', [''])[0]
                if re.fullmatch(r'\d{1,20}', document):
                    return urlunparse(('https', 'community.secop.gov.co', p.path, '', urlencode({'DocumentId': document, 'InCommunity': 'False', 'InPaymentGateway': 'False', 'DocUniqueIdentifier': ''}), ''))
            if p.path == '/Public/Tendering/OpportunityDetail/Index':
                notice = params.get('noticeUID', [''])[0]
                if re.fullmatch(r'CO1\.NTC\.\d+', notice, re.I):
                    return urlunparse(('https', 'community.secop.gov.co', p.path, '', urlencode({'noticeUID': notice.upper(), 'isFromPublicArea': 'True'}), ''))
    except ValueError:
        pass
    return ''


class Redactor:
    def __init__(self, identifiers=(), secrets=()):
        self.secrets = tuple(str(v) for v in secrets if v)
        self.identifiers = {re.sub(r'\D', '', str(v)) for v in identifiers
                            if len(re.sub(r'\D', '', str(v))) >= 5}
        # Búsqueda en conjunto: el costo no crece con cada identificación del CSV.
        self.pattern = re.compile(r'(?<!\d)\d(?:[\d.\-]*\d)?(?!\d)')
        self.spaced = re.compile(r'(?<!\d)\d{1,3}(?:[ \t]+\d{3}){1,4}(?:[- ]\d)?(?!\d)')

    def clean(self, value):
        text = unicodedata.normalize('NFKC', str(value or ''))
        for secret in self.secrets:
            text = text.replace(secret, '[credencial excluida]')
        text = re.sub(r'https?://[^\s<>]*objectstorage[^\s<>]*', '[enlace privado excluido]', text, flags=re.I)
        text = re.sub(r'\bsk-[A-Za-z0-9_-]+', '[credencial excluida]', text)
        text = re.sub(r'(?i)\b(?:c[eé]dula(?:\s+de\s+ciudadan[ií]a)?|documento\s+de\s+identidad|cuenta\s+bancaria|n[uú]mero\s+de\s+cuenta)\s*(?:No\.?|n[úu]mero|:|#)?\s*[\d.\s-]{5,}', '[identificación excluida] ', text)
        def hide_known(match):
            return '[identificación excluida]' if re.sub(r'\D', '', match.group()) in self.identifiers else match.group()
        text = self.pattern.sub(hide_known, text)
        text = self.spaced.sub(hide_known, text)
        text = re.sub(r'\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b', '[correo excluido]', text)
        # Identificadores desconocidos en documentos: no se permite trasladar cifras personales a la IA.
        text = re.sub(r'(?<![\w.])\d{7,13}(?:-\d)?(?![\w.])', '[identificación excluida]', text)
        text = re.sub(r'(?<!\d)\d{1,3}(?:\.\d{3}){2,3}-\d(?!\d)', '[identificación excluida]', text)
        text = re.sub(r'(?<![\d.])\d{1,3}(?:\.\d{3}){2,3}(?![\d.])', '[identificación excluida]', text)
        text = re.sub(r'(?i)(?:representad[oa]\s+legalmente\s+por|representante\s+legal\s*:)\s*[^;\n.]{0,160}', '[datos de representación excluidos]', text)
        return text.strip()

    def tree(self, value):
        if isinstance(value, dict):
            return {k: safe_secop_url(v) if k == 'url_secop' else self.tree(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.tree(v) for v in value]
        return self.clean(value) if isinstance(value, str) else value


def private_request(question):
    q = fold(question)
    return bool(re.search(r'CEDULA|IDENTIFICACION|DOCUMENTO (?:DEL (?:PROVEEDOR|SUPERVISOR|REPRESENTANTE)|DE IDENTIDAD)|DATOS? BANCARI|CUENTA BANCARIA|NUMERO DE CUENTA|CLAVE (?:API|SECRETA)|API[_ ]?KEY|RUTA PAR|TOKEN|SECRETOS?|CSV COMPLETO|BASE COMPLETA', q))
