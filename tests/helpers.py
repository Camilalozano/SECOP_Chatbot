import csv
import io
from src.catalog import FIELDS

URL = 'https://objectstorage.us-ashburn-1.oraclecloud.com/p/test/n/n/b/b/o/base.csv'


def fixture(extra=None):
    rows = []
    for cid, ref, year, value, paid, state, supplier, department in [
        ('CO1.PCCNTR.100', 'ATENEA-003-2025', '2025', '1000000', '500000', 'Terminado', 'UNIVERSIDAD PRUEBA', 'Posmedia'),
        ('CO1.PCCNTR.200', 'ATENEA-582-2025', '2025', '2000000', '', 'En ejecución', 'UNIVERSIDAD PRUEBA', 'Posmedia'),
        ('CO1.PCCNTR.300', 'ATENEA-003-2026', '2026', '3000000', '1000000', 'En ejecución', 'EMPRESA PRUEBA', 'Administrativa'),
        ('CO1.PCCNTR.400', 'ATENEA-004-2026', '2026', '', '0', 'Modificado', 'OTRA EMPRESA', 'Administrativa'),
    ]:
        row = {col: '' for col in FIELDS.values()}
        row.update({FIELDS['id']: cid, FIELDS['referencia']: ref, FIELDS['anio']: year, FIELDS['valor']: value,
                    FIELDS['pagado']: paid, FIELDS['estado']: state, FIELDS['proveedor']: supplier,
                    FIELDS['dependencia']: department, FIELDS['tipo']: 'Prestación de servicios',
                    FIELDS['modalidad']: 'Contratación directa', FIELDS['objeto']: 'Apoyo al análisis de información',
                    FIELDS['inicio']: f'{year}-01-10', FIELDS['fin']: f'{year}-12-30',
                    FIELDS['url_secop']: 'https://community.secop.gov.co/Public/Tendering/OpportunityDetail/Index?noticeUID=CO1.NTC.42',
                    'documento_proveedor (contratos_electronicos)': '1013640777',
                    'n_mero_de_documento_supervisor (contratos_electronicos)': '79157459'})
        rows.append(row)
    if extra:
        extra(rows)
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=list(rows[0]))
    writer.writeheader(); writer.writerows(rows)
    return output.getvalue().encode('utf-8-sig')
