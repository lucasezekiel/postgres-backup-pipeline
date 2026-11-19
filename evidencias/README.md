# Evidencias

Capturas y salidas de una ejecución real sobre una VM descartable. Cada `.png` tiene al lado un `.txt` con la misma salida en texto plano.

## Entorno (2026-11-19)

| Componente | Versión |
|---|---|
| Nodo de control | Debian GNU/Linux 13 (trixie), Ansible Core 2.22.0, ansible-lint 26.11.0, `community.postgresql` 4.2.0 |
| Virtualización | QEMU/KVM + libvirt 11.3.0, red NAT `default` |
| Destino | Ubuntu 24.04.5 LTS, 2 vCPU, 2 GB RAM, restaurada desde un snapshot limpio antes de la prueba |
| Instalado por el playbook | PostgreSQL 16.15, systemd 255 |

- El inventario `inventory/lab.yml` de las capturas es local y no se versiona.
- Se usó un Vault de prueba propio con una contraseña aleatoria descartable; el `vault.yml` del repositorio no se modificó.
- Al terminar, la VM se restauró al snapshot previo.

## Capturas

| # | Archivo | Qué demuestra |
|---|---|---|
| 01 | [01-pruebas-y-chequeos](01-pruebas-y-chequeos.png) | 17 pruebas simuladas, `bash -n` + ShellCheck de los scripts renderizados y `ansible-lint` sin fallas |
| 02 | [02-primera-ejecucion](02-primera-ejecucion.png) | Primera ejecución: `ok=14 changed=11 failed=0` |
| 03 | [03-segunda-ejecucion-idempotente](03-segunda-ejecucion-idempotente.png) | Repetición: `ok=13 changed=0`, es decir, idempotente |
| 04 | [04-bug-acceso-app-user](04-bug-acceso-app-user.png) | **Hallazgo:** `app_user` se conecta, pero no puede leer `inventory` (sin privilegios de tabla) |
| 05 | [05-ejecucion-con-fix](05-ejecucion-con-fix.png) | Con el fix solo cambian las dos tareas de `GRANT` (`changed=2`); la siguiente corrida vuelve a `changed=0` |
| 06 | [06-acceso-app-user-corregido](06-acceso-app-user-corregido.png) | `app_user` lee y actualiza datos, pero no puede crear tablas (mínimo privilegio) |
| 07 | [07-timers-systemd](07-timers-systemd.png) | Timers diario y semanal programados, con `Persistent=true` |
| 08 | [08-backup-manual](08-backup-manual.png) | Backup comprimido con permisos `0600` y entrada en `backup.log` |
| 09 | [09-verificacion-restauracion](09-verificacion-restauracion.png) | `Verification OK (3 rows match)` y ninguna base `backup_verify_*` residual |
| 10 | [10-retencion](10-retencion.png) | Se borra el backup elegible de 20 días; se conservan el de 7 días, el de otra base con prefijo parecido y el de nombre no estándar |
| 11 | [11-deteccion-diferencia](11-deteccion-diferencia.png) | Con un backup desactualizado, la verificación falla (`original=4 restored=3`), el servicio queda en `Result=exit-code` y limpia la base temporal |

## Observaciones

- La VM queda en UTC porque este playbook no configura la zona horaria; los timers usan `OnCalendar=daily` en esa zona.
- Los archivos de la prueba 10 son vacíos y se crearon con `touch -d`. Prueban la selección por nombre y antigüedad, no el contenido de los backups.
- La prueba 11 reproduce una limitación documentada: un cambio en la tabla posterior al backup produce una diferencia aunque la restauración haya funcionado.
