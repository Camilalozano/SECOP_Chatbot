# Consulta contractual · Piloto público

Aplicativo Streamlit independiente para consultar la exportación contractual de
Oracle y las obligaciones de documentos oficiales de SECOP. Acceso público, sin
autenticación ni licencias individuales de IA. No modifica las fuentes.

## Uso

Escriba una pregunta o utilice **Buscar y calcular con filtros**. Sin IA se
reconocen referencias, conteos y sumas por año, agrupaciones y vencimientos. Para
otros filtros use el formulario; el aplicativo pide aclaraciones en lugar de
ignorar restricciones o inventar cálculos.

Ejemplos: «¿Cuántos contratos hay en 2026?», «Valor por dependencia», «Contratos que
terminan en 60 días», «Obligaciones de ATENEA-582-2025».

La dependencia corresponde a la solicitante del PAA. Los valores son los montos
reportados en COP; no se reconstruye el valor inicial o vigente ni se certifica
cumplimiento. Los registros marcados `no_secop` se incluyen en las cifras, pero
no se les atribuyen documentos SECOP II. Los valores monetarios ausentes se
excluyen de sumas, no se convierten en cero. IDs repetidos invalidan la nueva
versión para evitar doble conteo.

## Actualización y documentos

Cada pregunta comprueba el PAR por GET condicional con ETag. Si la versión no
cambia, se conserva la tabla procesada; si cambia, se valida y reemplaza de forma
atómica. Sin ETag se descarga y compara SHA-256. Si una actualización falla, se
avisa expresamente que se utiliza una copia anterior. Tras reiniciar el servidor
la caché desaparece: no se ofrece una copia inexistente ni se guarda el CSV en Git.

El origen documental incluye los históricos oficiales 2026, 2025, 2024, 2023,
2022 y hasta 2021, paginación, deduplicación y proceso vinculado. Se excluyen los
archivos ligados a otros contratos. Los PDF de procesos compartidos requieren
comprobar la referencia contractual en el texto. El piloto revisa hasta tres PDF
candidatos por pregunta y 20 MB por PDF; los contenedores ZIP están acotados a
50 MB, 500 miembros y 100 MB descomprimidos. No encontrar la sección no demuestra
que el contrato carezca de obligaciones. Se conserva archivo, página, enlace y
SHA-256. Los PDF escaneados requieren OCR previo. Datos Abiertos puede tener rezago.

## Privacidad

La tabla pública se construye con una lista de campos permitidos. Nunca contiene
las columnas de identificaciones de proveedores, supervisores o representantes,
datos bancarios ni observaciones libres. También se limpian preguntas y texto
documental antes de mostrarlos o enviarlos al LLM. Se bloquean solicitudes de
identificaciones, secretos y descarga completa. Se muestran enlaces oficiales,
no copias binarias ni CSV de la fuente. Las descargas contienen únicamente el
resultado público mostrado (máximo 100 filas por consulta).

No se registran preguntas ni documentos. Las conversaciones se conservan solo en
la sesión del visitante (últimos ocho resultados), y pueden borrarse. Los
identificadores de cuota son aleatorios y no identifican personas. El proveedor
de IA conserva los datos que correspondan según sus términos: `store=false` no
equivale a retención cero de registros operativos. La minimización automática no
es una certificación de anonimización para cualquier documento futuro; revisar
los cambios de fuente y las pruebas antes de ampliar la información publicada.

## Ejecutar y desplegar

Python 3.12. Instale `requirements.txt` y ejecute `streamlit run app.py`.
En Streamlit Community Cloud: repositorio `Camilalozano/SECOP_Chatbot`, rama
`main`, archivo `app.py`. Copie `.streamlit/secrets.toml.example` en Settings →
Secrets y configure el PAR allí. Nunca publique `.streamlit/secrets.toml`, claves,
archivos CSV ni documentos descargados. El repositorio no contiene el PAR real.
El usuario responsable confirmó que las consultas y transferencias Oracle del
piloto están cubiertas por recursos existentes. El alojamiento elegido es
Streamlit Community Cloud, sujeto a sus límites gratuitos; no se habilitan otros
servicios pagos.

## Activación de IA: cerrada por defecto

No basta con tener ChatGPT, suscripción o clave. La API permanece desactivada si
falta cualquiera de estas condiciones administradas exclusivamente desde Secrets:

1. Créditos de API incluidos efectivamente disponibles y con vencimiento conocido.
2. Verificar en la organización/proyecto que no hay saldo comprado, recarga
   automática ni otra financiación que pueda consumirse al agotarse los créditos.
   Los límites de gasto del panel pueden ser alertas, no barreras de cobro: no
   sustituyen esta verificación. Si no puede garantizarlo, mantenga la IA apagada.
3. Configurar las verificaciones, clave, vencimiento UTC y una reserva de ejecución
   menor que los créditos disponibles, considerando otros usos de la cuenta.
4. Activar `AI_ENABLED` únicamente después de esa comprobación. Usar una identidad
   de servicio/proyecto de mínimo privilegio; nunca una clave de administrador.

El aplicativo no consulta ni cambia facturación, tarjetas o compras. No hay una
API pública universal que esta aplicación use para certificar el saldo elegible:
los indicadores son una declaración administrativa, no una auditoría automática.
Al vencer la verificación, faltar saldo o producirse un error de cuota, la IA se
detiene y permanecen disponibles los filtros convencionales.

Hasta cinco preguntas con IA por sesión en una ventana móvil de una hora; una
consulta activa por sesión y dos por proceso. El presupuesto local reserva por
adelantado `AI_TURN_RESERVE_USD` por pregunta completa. Es un control preventivo,
no la facturación real ni una garantía de costo por modelo. Cuotas y reservas
se reinician con el servidor y una persona puede abrir otra sesión. La protección
financiera final depende de la ausencia verificada de financiación pagada.

Responses API usa `store=false`, salidas estructuradas para el plan de consulta,
sin SQL ni código arbitrario, y sin herramientas alojadas de pago. El modelo por
defecto es `gpt-5-mini`, configurable. Si el resumen incluye números o citas no
sustentados, se descarta; las tablas siempre provienen del motor de consultas.

## Pruebas

`python -m unittest discover -v`

Incluye 30 preguntas de aceptación en `tests/cases.json`, pruebas de interfaz,
privacidad, actualización, duplicados, totales independientes, llamadas de API
simuladas, archivos ZIP, errores documentales y límites. Las pruebas automáticas
no requieren una clave real ni gastan créditos. La validación en vivo del piloto
se realiza con el PAR configurado fuera del repositorio.
