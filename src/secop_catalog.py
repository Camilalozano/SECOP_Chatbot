"""Inventario paginado por contrato y proceso, con históricos documentales SECOP."""
import re
from concurrent.futures import ThreadPoolExecutor

DOCUMENT_DATASETS = {
    'dmgg-8hin': 'Histórico 2026', 'h4m3-b4e2': 'Histórico 2025',
    'nbae-kzan': 'Histórico 2024', '3skv-9na7': 'Histórico 2023',
    'kgcd-kt7i': 'Histórico 2022', 'f8va-cf4m': 'Histórico hasta 2021',
}


def lookup_documents(contract_id, query, opener):
    from .documents import DocumentError as SecopDocumentError, document_url
    if not re.fullmatch(r'CO1\.PCCNTR\.\d+', contract_id, re.I):
        raise SecopDocumentError('El contrato no tiene un ID SECOP válido.')
    contract_id = contract_id.upper()
    rows, warnings, seen = [], [], set()

    def listing(dataset, process=None):
        found = []
        for offset in range(0, 5000, 500):
            params = {'proceso': process} if process else {'n_mero_de_contrato': contract_id}
            page = query(f'https://www.datos.gov.co/resource/{dataset}.json',
                         {**params, '$limit': 500, '$offset': offset, '$order': 'id_documento'}, opener)
            for row in page:
                owner = str(row.get('n_mero_de_contrato') or '').upper()
                if process:
                    if row.get('proceso') != process:
                        raise SecopDocumentError('SECOP devolvió documentos de otro proceso.')
                    if owner and owner != contract_id:
                        continue
                elif owner != contract_id:
                    raise SecopDocumentError('SECOP devolvió documentos de otro contrato.')
                found.append({**row, '_dataset': dataset,
                              '_asociacion': 'contrato' if owner else 'proceso'})
            if len(page) < 500:
                return found
        raise SecopDocumentError('La consulta supera 5.000 documentos por fuente.')

    def collect(process=None):
        with ThreadPoolExecutor(max_workers=6) as pool:
            jobs = [(ds, pool.submit(listing, ds, process)) for ds in DOCUMENT_DATASETS]
            for ds, job in jobs:
                try:
                    for row in job.result():
                        key = str(row.get('id_documento') or document_url(row))
                        if key and key not in seen:
                            rows.append(row)
                            seen.add(key)
                except SecopDocumentError as error:
                    warnings.append(f'{DOCUMENT_DATASETS[ds]}: {error} Consulta incompleta.')

    collect()
    processes = {r.get('proceso') for r in rows
                 if re.fullmatch(r'CO1\.BDOS\.\d+', str(r.get('proceso', '')))}
    if not processes:
        try:
            contracts = query('https://www.datos.gov.co/resource/jbjy-vk9h.json',
                              {'id_contrato': contract_id, '$select': 'id_contrato,proceso_de_compra', '$limit': 2}, opener)
            processes = {r.get('proceso_de_compra') for r in contracts if r.get('id_contrato') == contract_id
                         and re.fullmatch(r'CO1\.BDOS\.\d+', str(r.get('proceso_de_compra', '')))}
        except SecopDocumentError as error:
            warnings.append(str(error) + ' No se pudo identificar el proceso vinculado.')
    if len(processes) == 1:
        collect(next(iter(processes)))
    elif len(processes) > 1:
        warnings.append('Hay varios procesos vinculados: no se añadieron documentos sin ID contractual.')
    else:
        warnings.append('No se identificó el proceso vinculado; el inventario puede estar incompleto.')
    return rows, warnings
