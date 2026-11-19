🇪🇸 Español | [🇬🇧 English](README.en.md)

# PostgreSQL Backup Pipeline

[![Static checks and simulated tests](https://github.com/lucasezekiel/postgres-backup-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/lucasezekiel/postgres-backup-pipeline/actions/workflows/ci.yml)

Laboratorio con Ansible que instala PostgreSQL y programa copias de seguridad, limpieza por retención y una verificación de restauración acotada. Está pensado para un servidor de pruebas desechable, no para producción.

> **Seguridad:** el playbook instala paquetes, configura PostgreSQL y timers de systemd, y borra backups según la política de retención. La verificación de restauración crea y elimina una base temporal. Revisá el código y el inventario antes de ejecutarlo; no lo uses contra un servidor de producción ni con datos reales.

## Qué hace

**Rol `postgresql`**

- Instala PostgreSQL y sus bindings de Python.
- Crea una base de datos y un usuario de aplicación (contraseña provista con Ansible Vault), con privilegios de datos sobre las tablas y secuencias del esquema `public`.
- Carga un esquema y datos de ejemplo de forma idempotente (`INSERT ... ON CONFLICT DO NOTHING`).

**Rol `backup`**

- `pg_dump` diario automatizado, comprimido y con marca de tiempo.
- Limpieza por retención después de un dump exitoso. Por defecto `find -mtime +7` borra archivos con **al menos ocho** períodos completos de 24 horas.
- Verificación semanal: restaura el último backup en una base temporal nueva, compara la cantidad de filas de `inventory` con la base en vivo y elimina la base temporal.
- Ambos trabajos se programan con **timers de systemd** en lugar de cron.

La retención y la selección del backup a restaurar solo reconocen dos formatos de nombre:

- `<db>_AAAAMMDD_HHMMSS.sql.gz` (formato original)
- `<db>_AAAAMMDD_HHMMSS.XXXXXX.sql.gz` (formato actual, con seis caracteres alfanuméricos)

Cualquier otro nombre se ignora: nunca se selecciona ni se borra. El formato del nombre por sí solo no prueba el origen ni el contenido de un archivo.

```text
            systemd timer (diario)                 systemd timer (semanal)
                    │                                       │
                    ▼                                       ▼
   pg_dump ─▶ gzip ─▶ archivo temporal oculto      último backup válido
                    │                                       │
                    ▼                                       ▼
        publicación atómica (ln)                 createdb backup_verify_*
                    │                                       │
                    ▼                                       ▼
   retención: find -mtime +N -delete            restauración con ON_ERROR_STOP
                    │                                       │
                    ▼                                       ▼
              backup.log                       comparar filas ─▶ dropdb ─▶ verify.log
```

## Estructura

```text
├── ansible.cfg                    # inventario por defecto + pipelining SSH
├── requirements.yml               # colección de Ansible con versión fija
├── inventory/hosts.yml
├── group_vars/all/
│   ├── vars.yml                   # variables en texto plano
│   └── vault.yml                  # cifrado: contraseña de la base
├── roles/
│   ├── postgresql/                # instalación, usuario, esquema
│   └── backup/                    # scripts, *.service, *.timer, handlers
├── scripts/                       # ayudantes de chequeo estático
├── tests/                         # pruebas simuladas de los scripts
├── .github/workflows/ci.yml       # chequeos estáticos y pruebas simuladas
└── site.yml
```

## Requisitos

- Ansible ≥ 2.16 en el nodo de control.
- `community.postgresql` 4.2.0, declarada en `requirements.yml`:
  `ansible-galaxy collection install -r requirements.yml`
- Un servidor de pruebas desechable accesible por SSH (probado con Ubuntu 22.04.5 y 24.04.5 LTS en QEMU/libvirt).
- Un Ansible Vault propio con una contraseña de prueba (ver abajo).

## Crear tu propio Vault de laboratorio

El repositorio incluye un Vault cifrado del laboratorio original; su contraseña no se publica. En una copia de trabajo, movelo fuera de `group_vars` y creá el tuyo. Antes, comprobá que `vault.yml.reference` no exista, porque `mv` lo sobrescribiría.

```bash
mv group_vars/all/vault.yml vault.yml.reference
ansible-vault create group_vars/all/vault.yml
```

Elegí una contraseña de Vault nueva. En el editor definí `postgres_password` con una **contraseña de prueba nueva y descartable**, por ejemplo `postgres_password: "tu-clave-de-lab"`. Guardá la contraseña del Vault aparte y no subas tu Vault local ni secretos sin cifrar. Como el `vault.yml` original está versionado, `.gitignore` no lo protege: revisá `git status` y lo que vayas a commitear.

Revisá también `inventory/hosts.yml` y `group_vars/all/vars.yml` antes de ejecutar nada.

## Uso

```bash
# Verificar conectividad (las variables cifradas pueden pedir la contraseña del Vault)
ansible all -m ping --ask-vault-pass

# Previsualizar cambios (el modo check tiene limitaciones, ver abajo)
ansible-playbook site.yml --check --diff --ask-vault-pass --ask-become-pass

# Aplicar
ansible-playbook site.yml --ask-vault-pass --ask-become-pass
```

## Verificación manual del pipeline

```bash
sudo systemctl start pg_backup.service
sudo -u postgres cat /var/backups/postgres/backup.log

sudo systemctl start pg_verify_restore.service
sudo -u postgres cat /var/backups/postgres/verify.log

systemctl list-timers 'pg_*'
```

Una ejecución exitosa deja una línea como:

```text
Verification OK: /var/backups/postgres/inventory_db_20260924_163243.a1b2c3.sql.gz (3 rows match)
```

Esa línea indica que la restauración terminó y que las filas de esa tabla coincidían en ese momento. **No** prueba que todo el contenido sea idéntico ni que la recuperación cumpla requisitos de producción.

## Gestión de secretos

La contraseña de la base viaja en `group_vars/all/vault.yml`, cifrado con Ansible Vault:

```bash
ansible-vault view group_vars/all/vault.yml
ansible-vault edit group_vars/all/vault.yml
```

El cifrado protege el archivo en reposo, pero un Vault publicado se puede atacar offline si su contraseña es débil. La tarea que crea el usuario usa `no_log` para no mostrar la contraseña en la salida de Ansible.

## Pruebas

### Pruebas simuladas locales

Requieren Python 3, Bash y utilidades GNU estándar. Usan comandos falsos de PostgreSQL y archivos temporales; no se conectan a ningún servidor.

```bash
python3 -m unittest discover -s tests -v
```

Cubren:

- dumps exitosos y fallidos;
- ausencia de backups;
- errores de restauración y de creación de la base;
- limpieza de la base temporal;
- formato de nombres y bases con prefijo parecido;
- el límite de edad de la retención (`-mtime +7`: se conserva a los 7,5 días y se borra a los 8,5);
- el rechazo de nombres de base o valores de retención inválidos.

### Integración continua

GitHub Actions corre en cada push y pull request (el badge muestra el último resultado). El workflow:

- instala ShellCheck, `ansible-core` 2.22.0, `ansible-lint` 26.11.0 y la colección;
- ejecuta las pruebas simuladas;
- renderiza los templates y les pasa `bash -n` y ShellCheck;
- valida la sintaxis del playbook y ejecuta `ansible-lint`.

Los mismos chequeos se pueden correr localmente:

```bash
python3 -m unittest discover -s tests -v
python3 scripts/check_templates.py
python3 scripts/check_ansible.py
```

### Prueba en VM desechable

Probado en VMs QEMU/libvirt con Ansible Core 2.22.0 y `community.postgresql` 4.2.0.

**Ubuntu 24.04.5 LTS, PostgreSQL 16 (2026-11-19):**

| Prueba | Resultado |
|---|---|
| Primera ejecución | `ok=14 changed=11 unreachable=0 failed=0` |
| Repetición | `ok=13 changed=0` (idempotente, incluido el seed) |
| Acceso como `app_user` | ❌ `permission denied for table inventory`, **corregido** en esta revisión |
| Ejecución con el fix | `changed=2` (solo los `GRANT`); la siguiente, `changed=0` |
| `app_user` tras el fix | lee y actualiza; no puede crear tablas |
| Backup y verificación manuales | backup `0600`, `Verification OK (3 rows match)`, sin bases temporales |
| Retención | borra el backup elegible de 20 días; conserva el de 7 días y los de nombre ajeno |
| Backup desactualizado | la verificación falla (`original=4 restored=3`) y el servicio queda en error |

**Ubuntu 22.04.5 LTS (revisión anterior):**

- Primera ejecución: `ok=14 changed=11`; repetición: `ok=13 changed=0`.
- Backup y verificación manuales correctos.
- Un señuelo más nuevo con prefijo parecido fue ignorado al restaurar y conservado por la retención.

📸 Capturas y salidas completas en [`evidencias/`](evidencias/README.md).

Son resultados observados para esos estados y versiones, no garantías. Falta probar la ejecución de los timers a la hora programada y la recuperación tras una falla del servidor.

## Decisiones de diseño

- **Timers de systemd en vez de cron:** con `Persistent=true`, si la VM estaba apagada a la hora programada el timer recupera la ejecución perdida en lugar de saltearla.
- **`become_user: postgres` + pipelining SSH:** las tareas que corren como el usuario `postgres` necesitan pipelining en `ansible.cfg`; sin él falla el traspaso de archivos temporales entre usuarios.
- **Directorio de backups `0750`, propiedad de `postgres`:** solo el dueño de la base puede leer los backups (mínimo privilegio).
- **Vault solo para la contraseña:** es el único secreto; el resto queda en `group_vars` en texto plano para facilitar la revisión.

## Limitaciones conocidas

- **Tareas encadenadas con `--check`:** habilitar los timers depende de que existan los unit files, que `--check` no escribe.
- **Privilegios de la aplicación:** el usuario recibe `SELECT/INSERT/UPDATE/DELETE` sobre las tablas existentes de `public` y uso de sus secuencias. Las tablas que se creen **después** no quedan cubiertas hasta volver a ejecutar el playbook (no se configuran `DEFAULT PRIVILEGES`).
- **Entorno de laboratorio:** la VM de libvirt hay que encenderla a mano (`virsh start <vm>`) tras reiniciar el host. Con `Persistent=true`, los timers recuperan la ejecución perdida al volver.
- **Verificación acotada:** comparar cantidad de filas no compara contenido, otras tablas, roles ni permisos. Cambios en la tabla posteriores al backup también pueden causar una diferencia.
- **Limpieza tras una interrupción:** una terminación no capturable o una caída del equipo puede dejar la base temporal. Revisá antes de borrar a mano.
- **Backups solo locales:** sin cifrado ni copia fuera del host.
- **Nombres de base:** los scripts solo aceptan letras, dígitos y guion bajo en `db_name`.

## Próximas mejoras

- Copia fuera del host (rsync u object storage).
- Cifrado de backups en reposo.
- Alertas (correo o Slack) cuando falla la verificación.
- Parametrizar retención y horario con extra-vars.
- Prueba de integración en CI contra un contenedor de PostgreSQL.

## Licencia

MIT. Ver [LICENSE](LICENSE).
