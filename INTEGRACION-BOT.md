# Enlace con Abo bot

Este proyecto es el dashboard independiente. Se conecta directamente a la misma base PostgreSQL/Neon del bot.

- Usa el mismo `DATABASE_URL` que el bot.
- Ejecuta `dashboard_schema.sql` al iniciar para que pueda arrancar aunque el bot todavía no haya arrancado.
- La interfaz usa la URL del propio dashboard por defecto; no necesita una API externa.
- Usa el mismo Guild ID del servidor de Discord y `DASHBOARD_SECRET` para autenticar las operaciones.

No copies archivos Python entre ambos proyectos: el contrato de integración es la base compartida.

## Múltiples paneles

En la sección Tickets puedes crear, editar, seleccionar y eliminar paneles. Cada diseño se guarda en `ticket_panels`; para publicarlo, usa `/ticket_panel` en Discord y selecciona el panel por nombre.
