"""Solo operaciones estructuradas; ninguna cadena del LLM se ejecuta como SQL."""
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import duckdb
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from .catalog import FIELDS
from .privacy import fold

class QuerySpec(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operacion: Literal['listar', 'contar', 'sumar', 'agrupar', 'obligaciones', 'documentos', 'aclarar']
    referencia: str | None
    texto: str | None
    proveedor: str | None
    estado: str | None
    dependencia: str | None
    modalidad: str | None
    anio: int | None
    vence_dias: int | None
    agrupar_por: Literal['anio', 'estado', 'dependencia', 'proveedor', 'modalidad', 'tipo'] | None
    medida: Literal['contratos', 'valor', 'pagado']
    aclaracion: str | None


def spec(**kwargs):
    return QuerySpec(**{**{k: None for k in QuerySpec.model_fields}, 'operacion': 'listar', 'medida': 'contratos', **kwargs})


def fallback(question):
    q = fold(question)
    if re.search(r'PROMEDIO|PORCENTAJE|CUMPLIMIENTO|LEGALIDAD|RIESGO|COMPARA|VALOR (?:INICIAL|VIGENTE)|SUPERVISOR|MAS DE|MENOS DE|MAYOR QUE|MENOR QUE', q):
        return spec(operacion='aclarar', aclaracion='Esta pregunta requiere una definición o un filtro adicional. En el piloto puedes consultar valores reportados, cantidades, referencias y obligaciones; usa los filtros para precisar el alcance.')
    match = re.search(r'ATENEA[\s-]+[A-Z0-9]+(?:[\s-]+[A-Z0-9]+)*[\s-]+20\d{2}\b', q)
    cid = re.search(r'CO1\.PCCNTR\.\d+', q)
    reference = re.sub(r'\s+', '-', match.group()) if match else cid.group() if cid else None
    if any(w in q for w in ('OBLIGACION', 'COMPROMISO')):
        return spec(operacion='obligaciones', referencia=reference,
                    aclaracion=None if reference else 'Indica la referencia completa del contrato para consultar sus obligaciones.')
    if any(w in q for w in ('DOCUMENTO', 'MINUTA', 'ESTUDIOS PREVIOS')):
        return spec(operacion='documentos', referencia=reference)
    if reference:
        return spec(referencia=reference)
    year = re.search(r'\b20\d{2}\b', q)
    days = re.search(r'(\d{1,3})\s*DIAS', q)
    group = next((k for token, k in [('DEPENDENCIA', 'dependencia'), ('MODALIDAD', 'modalidad'), ('PROVEEDOR', 'proveedor'), ('ESTADO', 'estado'), ('ANO', 'anio'), ('TIPO', 'tipo')] if ('POR ' + token) in q), None)
    if not group and re.search(r'CONTRATOS DE\s+(?!20\d{2}\b|LA BASE\b|SERVICIOS\b)|DEL PROVEEDOR|DEL CONTRATISTA|DEPENDENCIA|MODALIDAD', q):
        return spec(operacion='aclarar', aclaracion='Usa los filtros de proveedor, dependencia o modalidad para aplicar exactamente esa condición mientras la IA está desactivada.')
    measure = 'pagado' if 'PAGAD' in q else 'valor' if any(w in q for w in ('VALOR', 'MONTO', 'SUMA')) else 'contratos'
    op = 'agrupar' if group else 'sumar' if measure != 'contratos' else 'contar' if any(w in q for w in ('CUANTOS', 'CANTIDAD', 'NUMERO DE CONTRATOS', 'TOTAL DE CONTRATOS')) else 'listar'
    if year or days or group or op != 'listar' or any(w in q for w in ('TODOS LOS CONTRATOS', 'LISTAR CONTRATOS', 'ULTIMOS CONTRATOS')):
        state = next((term for term in ('TERMINAD', 'EN EJECUCION', 'LIQUIDAD', 'MODIFICAD', 'CERRAD', 'ADJUDICAD') if term in q), None)
        return spec(operacion=op, anio=int(year.group()) if year else None, vence_dias=int(days.group(1)) if days else None,
                    agrupar_por=group, medida=measure, estado=state)
    return spec(operacion='aclarar', aclaracion='Sin IA activa, usa los filtros o indica una referencia, un año, un total o un plazo. Ejemplo: ¿Cuántos contratos hay en 2026?')


def validate(plan):
    if plan.anio is not None and not 2000 <= plan.anio <= 2100:
        raise ValueError('Indica un año entre 2000 y 2100.')
    if plan.vence_dias is not None and not 1 <= plan.vence_dias <= 366:
        raise ValueError('El plazo de consulta debe estar entre 1 y 366 días.')
    for field in ('referencia', 'texto', 'proveedor', 'estado', 'dependencia', 'modalidad'):
        value = getattr(plan, field)
        if value and len(value) > 200:
            raise ValueError('El filtro es demasiado largo.')
    if plan.operacion == 'agrupar' and not plan.agrupar_por:
        raise ValueError('Indica por qué campo deseas agrupar.')


def execute(rows, plan):
    validate(plan)
    con = duckdb.connect(':memory:')
    try:
        columns = list(FIELDS)
        types = {k: 'VARCHAR' for k in columns}
        types.update(valor='DECIMAL(24,2)', pagado='DECIMAL(24,2)', anio='INTEGER', inicio='DATE', fin='DATE', firma='DATE')
        con.execute('CREATE TABLE contratos (' + ','.join(f'"{k}" {types[k]}' for k in columns) + ')')
        con.executemany('INSERT INTO contratos VALUES (' + ','.join('?' for _ in columns) + ')', [[r[k] for k in columns] for r in rows])
        clauses, args = [], []
        if plan.referencia:
            key = re.sub(r'[\s-]+', '', plan.referencia).upper()
            clauses.append("(regexp_replace(upper(referencia), '[[:space:]-]+', '', 'g') = ? OR upper(id) = ?)")
            args.extend([key, plan.referencia.upper()])
        if plan.proveedor:
            # Todas las palabras completas, sin exigir adyacencia ni orden.
            # Así CAMILA LOZANO encuentra LOZANO, CAMILA ANDREA.
            terms = set(re.findall(r'[A-Z0-9]+', fold(plan.proveedor)))
            if not terms:
                raise ValueError('Escribe al menos una palabra del nombre del proveedor.')
            for term in sorted(terms):
                clauses.append("contains(' ' || regexp_replace(strip_accents(upper(proveedor)), '[^A-Z0-9]+', ' ', 'g') || ' ', ?)")
                args.append(' ' + term + ' ')
        for key in ('estado', 'dependencia', 'modalidad'):
            if value := getattr(plan, key):
                clauses.append(f'contains(strip_accents(upper("{key}")), ?)')
                args.append(fold(value))
        if plan.texto:
            for term in fold(plan.texto).split():
                clauses.append('contains(strip_accents(upper(objeto)), ?)')
                args.append(term)
        if plan.anio:
            clauses.append('anio = ?'); args.append(plan.anio)
        if plan.vence_dias:
            today = datetime.now(ZoneInfo('America/Bogota')).date()
            clauses.append('fin BETWEEN ? AND ?'); args.extend([today, today + timedelta(days=plan.vence_dias)])
        where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        count = con.execute('SELECT count(*) FROM contratos' + where, args).fetchone()[0]
        truncated = False
        missing = 0
        if plan.operacion in ('contar', 'sumar', 'agrupar'):
            metric = 'count(*)' if plan.medida == 'contratos' else f'sum("{plan.medida}")'
            if plan.medida != 'contratos':
                missing = con.execute(f'SELECT count(*) FROM contratos{where}' + (' AND ' if where else ' WHERE ') + f'"{plan.medida}" IS NULL', args).fetchone()[0]
            group = ('"proveedor"' if plan.operacion == 'contar' and plan.proveedor
                     else f'"{plan.agrupar_por}"' if plan.operacion == 'agrupar' else None)
            sql = f'SELECT {group + "," if group else ""}{metric} AS resultado FROM contratos{where}'
            if group:
                sql += f' GROUP BY {group} ORDER BY resultado DESC NULLS LAST, {group} LIMIT 101'
            cur = con.execute(sql, args)
        else:
            cur = con.execute('SELECT * FROM contratos' + where + ' ORDER BY anio DESC NULLS LAST, referencia LIMIT 101', args)
        names = [c[0] for c in cur.description]
        result = [dict(zip(names, r)) for r in cur.fetchall()]
        if len(result) > 100:
            truncated, result = True, result[:100]
        return {'rows': result, 'matching_contracts': count, 'truncated': truncated, 'missing_values': missing,
                'measure': plan.medida, 'operation': plan.operacion, 'filters': plan.model_dump(exclude_none=True)}
    finally:
        con.close()
