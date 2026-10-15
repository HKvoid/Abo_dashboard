# Mejoras del dashboard Abo

## Bienvenidas y despedidas

Ahora se pueden cargar imágenes desde el dispositivo, previsualizarlas y quitarlas. Se aceptan PNG, JPG/JPEG, GIF y WebP hasta 5 MB; el servidor valida el formato, la integridad y las dimensiones. Las imágenes se almacenan en PostgreSQL en la tabla `dashboard_uploads`, creada automáticamente con la primera carga, para persistir entre reinicios. Las claves existentes `welcome_image_url` y `leave_image_url` se conservan, así como el soporte para URLs de imágenes ya configuradas.

## Tickets

El dashboard incorpora un editor de panel con título, descripción y hasta 10 botones configurables con emoji y texto, además de su vista previa. También muestra métricas de tickets abiertos, asignados, cerrados y totales, permite filtrar y buscar, y presenta solicitante, canal, staff asignado y detalles al abrir un ticket.

La configuración del editor se persiste en `guild_settings` con las claves `ticket_panel_title`, `ticket_panel_description` y `ticket_panel_buttons`.

## Despliegue e integración

`Pillow` se agregó a `requirements.txt`; el `buildCommand` existente de Render instalará esa dependencia. En Render, las URLs de imagen se construyen con `RENDER_EXTERNAL_URL`; para otro hosting se puede definir `PUBLIC_BASE_URL` con el origen HTTPS público del dashboard, sin `/` final. El usuario de PostgreSQL necesita permiso para crear `dashboard_uploads` durante la primera carga.

**Límite del ZIP recibido:** contiene el dashboard Flask y su API, pero no el código del bot de Discord. Por eso el editor guarda las opciones y permite previsualizarlas, pero no publica ni actualiza el mensaje de Discord por sí solo. Para activar esas opciones en Discord, el bot debe leer las tres claves `ticket_panel_*` y crear o editar el mensaje. Las claves existentes de bienvenida/despedida se conservan para la integración actual.
