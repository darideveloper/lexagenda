# Spec

## Canal

`POST /webhooks/gowa` verifica `X-Hub-Signature-256` (HMAC-SHA256 sobre el cuerpo crudo),
descarta lo que no es un evento `message`, los mensajes propios, grupos y estados, los medios,
el device distinto de `GOWA_DEVICE_A` y los JIDs distintos de `LAWYER_JID`, deduplica por wamid
y siempre responde 200. Persiste `Message` (rol `user`) y un `Job(kind=inbound)`.

`manage.py work` reclama el Job con `select_for_update(skip_locked=True)`, corre el agente,
envía la respuesta por gowa (device A) y sella `Message.replied_at`; un mensaje ya respondido
no se reenvía, y un Job con error reintenta hasta tres veces antes de quedar `failed`.

## Modelo

Los modelos de dominio migran: `core.BaseLocation`, `core.Client`, `core.Case`, `agenda.Appointment`,
`agenda.Deadline`, `agenda.TravelBlock`, `assistant.Thread`, `assistant.Message`, `assistant.Job`,
`assistant.AuditLog`.

## Acceso

`/login/` pide usuario, contraseña y código TOTP o de recuperación; `setup_lawyer` crea el
usuario, su `TOTPDevice` y diez códigos de recuperación de un solo uso. `/` (la agenda de hoy)
exige sesión verificada. `/admin/` usa `OTPAdminSite`: sin TOTP no se entra, y un usuario que
no es staff se rechaza aunque su código sea válido.

## Agente

`apps/assistant/agent.py` da hasta cuatro pasos contra OpenRouter con tres herramientas de
lectura: `agenda_today`, `case_search` y `case_summary`. Cada llamada deja una fila en
`AuditLog`; una herramienta desconocida se audita como fallo y no impide responder.

## Propuestas

Una herramienta de escritura no toca la base: valida sus argumentos y guarda una `Proposal`
(`steps`, `summary` — exactamente lo que se le mostró al abogado, `expires_at`) con estado
`proposed`. Una segunda propuesta marca la anterior como `superseded` y lo dice en una línea; solo
puede haber una `proposed` por hilo (restricción parcial en la base).

El abogado responde en palabras y el modelo solo puede llamar `confirm(proposal_id)`,
`cancel(proposal_id)` o `undo(proposal_id)`: ningún otro argumento se acepta, y lo que se aplica es
lo guardado en la fila. `confirm` toma la fila con `select_for_update()` dentro de
`transaction.atomic()`, aplica los pasos en orden, sella `committed_at` y deja en `result.undo` el
paso inverso; una confirmación repetida contesta "Ya estaba hecho." sin volver a escribir. Una
pregunta no confirma nada. Una propuesta caducada (`min(inicio de la cita, ahora + 12 h)`) se
rechaza al confirmar y `manage.py sweep` la marca `expired`. `undo` aplica el paso inverso como
propuesta compensatoria dentro de 24 h y deja la original en `undone`.

Si el modelo barato no llama herramienta teniendo una propuesta abierta, devuelve JSON roto, una
herramienta desconocida o un argumento rechazado, el bucle reintenta una vez con
`LLM_FALLBACK_MODEL` y `AuditLog.model` guarda cuál modelo contestó. `canaries.yaml` fija las 20
peticiones que deben enrutar a su herramienta y las 20 respuestas que deben decidir
confirmar/cancelar/nada.

## Plazos

`config/calendars/` guarda cuatro calendarios YAML: `federal`, `oaj`, `hidalgo` y `custom`.
Cada fecha lleva su `source` y su `verified_on`, vacío hasta que alguien la confirma; una
entrada sin fuente no carga. Los periodos vacacionales de Hidalgo (16–31 jul y 17 dic–8 ene)
se expanden en días inhábiles, y el 5 feb y el 20 nov de `oaj` van con `laborable: true`: la
oficina abre, el término no corre. El calendario por defecto es la unión
`federal ∪ oaj ∪ hidalgo`; `custom` y cualquier otro entran solo por nombre, y la versión
(`2026.1`) se sella al verificar.

`apps/agenda/business_days.py` calcula el plazo: el conteo en días hábiles empieza el día
siguiente a la notificación, la prórroga mueve el último día inhábil al siguiente hábil, y
`meses` usa meses de calendario con fin de mes y la misma prórroga. `dias_naturales` ignora el
calendario salvo para la prórroga.

`Deadline` guarda `notified_on`, `term_value`, `term_unit`, `calendar_overrides` y
`reminder_days`; con término calcula `due_date` y marca `computed`, y sin término la fecha se
captura a mano con `computed` en falso.

`/plazos/` lista los plazos no cumplidos con la etiqueta «calculado — verifica» y su
aritmética («20 días hábiles desde notificación 30 oct»); `POST /plazos/<id>/verificar/` sella
`verified_by`, `verified_at` y `verified_with_calendar` sin borrar la etiqueta, y un plazo
verificado con otra versión muestra «calendario actualizado — re-verifica». `manage.py sweep`
pasa a `missed` los plazos `open` con `due_date` anterior a hoy.
## Calendar mirror

`apps/agenda/services.py` es el único que mueve `ics_sequence`: crear, mover, cancelar o
cambiar la dirección sube exactamente uno y manda un correo con el `.ics` adjunto (`REQUEST`, o
`CANCEL` con `STATUS:CANCELLED` al cancelar) al abogado; un recálculo de traslados no toca ni la
secuencia ni el correo, y una operación sin cambio real tampoco. El `UID` es
`appointment.ics_uid`, así que un cambio actualiza el evento en lugar de duplicarlo, y el correo
del cliente nunca es destinatario. Los eventos son los tres de PLAN §7.2: cita con `LOCATION` y
`TRANSP:OPAQUE`, traslado `Traslado → <destino>` transparente y plazo de día completo con
avisos a 7/3/1 días y «calculado — verifica». `GET /calendar/<ICS_TOKEN>.ics` sirve citas no
canceladas, sus traslados y los plazos abiertos con CRLF y plegado a 75 octetos, responde 404 a
cualquier otro token (y a todos si `ICS_TOKEN` está vacío) y manda `X-Robots-Tag: noindex`; el
token se lee en cada petición, así que rotarlo invalida la URL anterior sin caché de por medio;
en un contenedor desplegado el cambio de `ICS_TOKEN` surte efecto al reiniciarlo, porque
`docker-compose` congela el entorno al arrancar.
## Dashboard

`/clients/`, `/clients/<id>` y `/cases/<id>` piden sesión con TOTP y leen los modelos reales;
sólo se escriben teléfono, correo y notas del cliente, y el estado del caso (PLAN §11). `/ops/`
es sólo para `is_staff`: muestra mensajes, auditoría, propuestas y trabajos, reencola un trabajo
`failed` y
restablece el 2FA del abogado — auditado en `AuditLog(tool=2fa_reset)` y avisado por correo. Los
tres temporizadores (`work`, `sweep`, `brief`) hacen ping a healthchecks.io
(`HEALTHCHECK_<NAME>_URL`) y un ping caído nunca rompe la corrida.

## Documentos

Un archivo reenviado por WhatsApp se guarda en `media/inbound/<año>/<mes>/<sha256>.<ext>`
(hasta 25 MB; lo que pasa se rechaza sin crear fila); archivarlo copia el blob a
`media/documents/<expediente>/<sha256[:2]>/<sha256>.<ext>` y crea un `Document` con el texto
extraído de pdf/docx/xlsx/txt. Un PDF escaneado se acepta con `no_text_layer` y se muestra
«sin texto». `document_search` y `/documents/` corren la misma consulta `ts_headline` (español)
con realce por `pg_trgm` sobre expediente y cliente; el disparador mantiene el `tsvector` y el
GIN lo indexa. `sweep` purga a los 90 días el media entrante sin archivar y sólo borra un blob
cuando ningún `Document` activo ni `InboundMedia` sin purgar lo referencia; el panel avisa al
80 % de los 500 MB.

## Visitas

`plan_visit` resuelve la dirección del abogado con una sola búsqueda de Places —una ficha, o un
enlace de Maps con `address_source=link` y sin coordenadas, nunca un pin adivinado— y reutiliza
la última cita ya resuelta del cliente antes de gastar esa búsqueda. La propuesta solo se escribe
al confirmar: `apps/agenda/planner.py` deja un bloque de traslado de `starts_at - buffer_min -
travel_min` a `starts_at - buffer_min` para cada visita con coordenadas, y sin coordenadas la
visita queda con `travel_min=0`, sin bloque y con un «sin dirección» en el brief. Mover la cita,
cambiar su dirección o el brief de las 08:00 recalculan el bloque.

## Avisos al cliente

`client_update` guarda el texto exacto del aviso y al confirmar lo manda byte por byte desde el
número del abogado (device B), nunca desde el de control, y sólo a un JID que ya esté en la
agenda: cualquier otro número se rechaza con una frase. Cada envío deja una fila en `SendLog`
con el texto, y las caps —20 por hora, 60 al día, 2 s entre mensajes— cuentan esas filas y
contestan en español cuando ya no dejan salir. `delivery_mode` se lee de `config.yaml` en cada
envío, así que `draft` convierte la confirmación en un borrador sin reiniciar nada. `client_create`
no escribe nada hasta confirmar la tarjeta, que muestra el nombre con el que aparece en WhatsApp;
una tarjeta de contacto reenviada llega a la misma propuesta.
