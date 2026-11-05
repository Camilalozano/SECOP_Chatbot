"""Adaptado del extractor de obligaciones IES de Camilalozano.

Mantiene sección objetivo y numeración consecutiva; requiere revisión humana.
"""
import re
import unicodedata

def normalize_for_search(text: str) -> str:
    text = unicodedata.normalize("NFD", text)
    return "".join(c for c in text if unicodedata.category(c) != "Mn").upper()


def clean_text(text: str) -> str:
    text = text.replace("\u00ad", "").replace("\u2013", "-").replace("\u2014", "-")
    text = re.sub(
        r"(?im)^\s*(Carrera 10 No\..*|PBX:.*|www\.agenciaatenea.*|"
        r"atencionalciudadano.*|Información: Línea 195.*|Página \d+ de \d+)\s*$",
        "",
        text,
    )
    text = re.sub(r"\[\[PAGE:\d+\]\]", " ", text)
    text = re.sub(
        r"(?im)^\s*CONVENIO POR R[ÉE]GIMEN PRIVADO[^\n]*\n"
        r"\s*DISTRITAL DE EDUCACI[ÓO]N SUPERIOR[^\n]*\n"
        r"\s*[^\n]{2,120}\.\s*$",
        "",
        text,
    )
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def extract_obligations(text: str, pages: list[str] | None = None) -> list[dict]:
    """Sección específica de la IES o contraparte, sin obligaciones de ATENEA."""
    marked = []
    for number, page in enumerate(pages or [text], 1):
        header = re.match(r'(?is)\A.{0,1000}?Formato\s+de\s+Estudios\s+y\s+Documentos\s+Previos.{0,500}?P[aá]gina\s+\d+\s+de\s+\d+[^\S\n]*\n', page)
        if header:
            page = page[header.end():]
        page = re.sub(r'(?im)^\s*(?:Carrera 10 No\..*|PBX:.*|www\.agenciaatenea.*|atencionalciudadano.*|Información: Línea 195.*|Página \d+ de \d+)\s*$', '', page)
        page = re.sub(r'(?im)^\s*CONVENIO POR R[ÉE]GIMEN PRIVADO[^\n]*\n\s*DISTRITAL DE EDUCACI[ÓO]N SUPERIOR[^\n]*\n\s*[^\n]{2,120}\.\s*$', '', page)
        marked.append(f'[[PAGE:{number}]]\n{page}')
    original = '\n'.join(marked).replace('\u00ad', '')
    parts, offsets = [], []
    for index, char in enumerate(original):
        folded = normalize_for_search(char)
        parts.append(folded)
        offsets.extend([index] * len(folded))
    normalized = ''.join(parts)
    party = r'(?:LAS?\s+IES|LA\s+IES|LA\s+INSTITUCION\s+DE\s+EDUCACION\s+SUPERIOR(?:\s*[-–—]\s*IES)?|EL\s+ASOCIADO|LA\s+ASOCIADA|EL\s+CONTRATISTA)'
    patterns = [
        rf'(?:COMPROMISOS|OBLIGACIONES)\s+ESPECIFIC[OA]S(?:\s+(?:DE\s+{party}|DEL\s+(?:CONTRATISTA|ASOCIADO)))?\s*[:.\-]?',
        rf'(?:OBLIGACIONES|COMPROMISOS)\s+DE\s+{party}\s*:\s*(?:SE\s+OBLIGA\s+A\s*:)?',
    ]
    starts = sorted({m.span() for pattern in patterns for m in re.finditer(pattern, normalized)})
    results = []
    for start, begin in starts:
        tail = normalized[begin:]
        if re.match(r'\s*(?:DE\s+(?:LA\s+AGENCIA|ATENEA|LA\s+ENTIDAD)|DEL\s+(?!CONTRATISTA|ASOCIADO))', tail):
            continue
        ends = []
        for pattern in [
            r'\b(?:OBLIGACIONES|COMPROMISOS)\s+(?:ESPECIFIC[OA]S\s+)?DE\s+(?:LA\s+)?(?:AGENCIA|ATENEA|ENTIDAD)\b',
            r'\b(?:D|E)[.)]\s+(?:OBLIGACIONES|COMPROMISOS)\b',
            r'\bPARAGRAFO\s*[:.\-]',
            r'\bPARAGRAFO\.?\s+TODOS\s+LOS\s+DOCUMENTOS',
            r'\bDECIMA[ .\-]+COMITE\s+TECNICO',
            r'\bCLAUSULA\s+(?:PRIMERA|SEGUNDA|TERCERA|CUARTA|QUINTA|SEXTA|SEPTIMA|OCTAVA|NOVENA|DECIMA|[IVX]+)\b\s*[:.\-–—]',
            r'(?m)^\s*(?:(?:\d+(?:\.\d+)*[.)]?|[A-Z][.)])\s+)?(?:OBLIGACIONES\s+GENERALES|MODALIDAD\s+DE\s+SELECCION|VALOR\s+(?:DEL|ESTIMADO)|FORMA\s+DE\s+PAGO|GARANTIAS|PLAZO\s+DE\s+EJECUCION|PRODUCTOS\s+ESPERADOS)\b',
        ]:
            match = re.search(pattern, tail)
            if match:
                ends.append(match.start())
        end = begin + (min(ends) if ends else min(len(tail), 35000))
        original_begin = offsets[begin] if begin < len(offsets) else len(original)
        original_end = offsets[end] if end < len(offsets) else len(original)
        section = original[original_begin:original_end]
        markers = list(re.finditer(r'(?<![\d\w.])\(?(?P<prefix>(?:\d{1,2}\.)+)?(?P<number>\d{1,2})(?(prefix)[.)]*|[.)]+)\s+(?=[A-Za-zÁÉÍÓÚÜÑáéíóúüñ])', section))
        selected, prefix = [], None
        for marker in markers:
            number = int(marker.group('number'))
            if prefix is None and number == 1:
                prefix = marker.group('prefix') or ''
            if prefix is not None and (marker.group('prefix') or '') == prefix and (not selected or number > int(selected[-1].group('number'))):
                selected.append(marker)
        items = []
        numbers = [int(m.group('number')) for m in selected]
        warnings = []
        if numbers != list(range(1, len(numbers) + 1)):
            warnings.append('Numeración con saltos: compare la sección con el PDF.')
        if not ends:
            warnings.append('No se identificó el cierre de sección; revise la última obligación.')
        for index, marker in enumerate(selected):
            stop = selected[index + 1].start() if index + 1 < len(selected) else len(section)
            value = clean_text(section[marker.end():stop]).strip(' ;')
            if not value:
                continue
            prior = list(re.finditer(r'\[\[PAGE:(\d+)\]\]', original[:original_begin + marker.start()]))
            item = {'numero_obligacion': int(marker.group('number')), 'obligaciones_especificas': value}
            if pages:
                item['pagina'] = int(prior[-1].group(1)) if prior else 1
            if warnings:
                item['advertencias'] = warnings
            items.append(item)
        if items:
            results.append(items)
    if not results:
        return []
    best = max(results, key=len)
    if len(results) > 1:
        for item in best:
            item.setdefault('advertencias', []).append('Varias secciones candidatas; verifique la contraparte y el documento.')
    return best
