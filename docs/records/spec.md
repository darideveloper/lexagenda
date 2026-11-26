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

Ocho modelos migran: `core.BaseLocation`, `core.Client`, `core.Case`, `agenda.Appointment`,
`assistant.Thread`, `assistant.Message`, `assistant.Job`, `assistant.AuditLog`.

## Acceso

`/login/` pide usuario, contraseña y código TOTP o de recuperación; `setup_lawyer` crea el
usuario, su `TOTPDevice` y diez códigos de recuperación de un solo uso. `/` (la agenda de hoy)
exige sesión verificada. `/admin/` usa `OTPAdminSite`: sin TOTP no se entra, y un usuario que
no es staff se rechaza aunque su código sea válido.

## Agente

`apps/assistant/agent.py` da hasta cuatro pasos contra OpenRouter con tres herramientas de
lectura: `agenda_today`, `case_search` y `case_summary`. Cada llamada deja una fila en
`AuditLog`; una herramienta desconocida se audita como fallo y no impide responder.
