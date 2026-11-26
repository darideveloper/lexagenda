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
