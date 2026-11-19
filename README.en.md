[🇪🇸 Español](README.md) | 🇬🇧 English

# PostgreSQL Backup Pipeline

[![Static checks and simulated tests](https://github.com/lucasezekiel/postgres-backup-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/lucasezekiel/postgres-backup-pipeline/actions/workflows/ci.yml)

An Ansible lab that provisions a PostgreSQL database and schedules backups, retention cleanup, and a limited restore check. It is intended for a disposable test server, not for production use.

**Safety:** this playbook installs packages, configures PostgreSQL and systemd timers, and deletes backups according to its retention policy. The restore check creates and drops a temporary database. Review the code and target inventory before running it; do not use a production server or real data.

## What it does

**`postgresql` role**

- Installs PostgreSQL and its Python bindings
- Creates a database and an application user (password supplied via Ansible Vault)
- Loads a seed schema and sample data, idempotently (`INSERT ... ON CONFLICT DO NOTHING`)

**`backup` role**

- Daily automated `pg_dump`, compressed and timestamped
- Retention cleanup deletes matching old backups after a successful dump (the default `find -mtime +7` matches files at least eight complete 24-hour periods old)
- Weekly restore check: restores the latest backup into a newly created temporary database, compares the `inventory` row count against the live database, and removes the temporary database
- Both jobs are scheduled with **systemd timers** rather than cron

Retention and restore selection recognize only `<db>_YYYYMMDD_HHMMSS.sql.gz` (the original format) and `<db>_YYYYMMDD_HHMMSS.XXXXXX.sql.gz` (the current format, with six alphanumeric characters). Other names are ignored and never selected or deleted by these scripts. Review any older or custom backup names separately; the filename format alone does not prove a backup's origin or contents.

## Project structure

```
├── ansible.cfg                    # default inventory path + SSH pipelining
├── requirements.yml               # pinned Ansible collection
├── inventory/hosts.yml
├── group_vars/all/
│   ├── vars.yml                   # plain variables
│   └── vault.yml                  # encrypted: database password
├── roles/
│   ├── postgresql/
│   │   ├── tasks/main.yml
│   │   └── files/schema.sql
│   └── backup/
│       ├── tasks/main.yml
│       ├── templates/             # backup.sh, verify_restore.sh, *.service, *.timer
│       └── handlers/main.yml
├── .github/workflows/ci.yml       # static checks and simulated tests
├── scripts/                       # static check helpers
├── site.yml
└── tests/                         # simulated script tests
```

## Requirements

- Ansible ≥ 2.16 on the control node
- `community.postgresql` 4.2.0, declared in `requirements.yml` (install with `ansible-galaxy collection install -r requirements.yml`)
- A disposable target server reachable via SSH (tested on Ubuntu 22.04.5 LTS in a QEMU/libvirt lab; see the test scope below)
- A locally created Ansible Vault containing your own test database password (see below)

## Create your own lab Vault

The repository contains an encrypted Vault created for the original lab; its password is not provided. In a disposable working copy, move it out of `group_vars` and create your own. These commands change files in your local clone; they do not change GitHub. Before moving it, check that `vault.yml.reference` does not already exist; the `mv` command would otherwise overwrite it.

```bash
mv group_vars/all/vault.yml vault.yml.reference
ansible-vault create group_vars/all/vault.yml
```

Choose a new Vault password when prompted. In the encrypted file's editor, define `postgres_password` as a YAML string with a **new, disposable lab password**, for example `postgres_password: "your-lab-password"`. Save and close the editor. Keep the Vault password separate and do not commit your local Vault, passwords, or unencrypted secrets. The original `vault.yml` is tracked, so `.gitignore` alone cannot protect it from being committed: inspect `git status` and your staged changes carefully.

Review `inventory/hosts.yml` and the non-secret variables in `group_vars/all/vars.yml` for your own disposable target before running any commands below.

## Usage

```bash
# Verify connectivity (the encrypted group variables may require the Vault password)
ansible all -m ping --ask-vault-pass

# Preview supported changes (check mode has limitations)
ansible-playbook site.yml --check --diff --ask-vault-pass --ask-become-pass

# Apply for real
ansible-playbook site.yml --ask-vault-pass --ask-become-pass
```

## Secrets management

The database password is supplied through `group_vars/all/vault.yml`, encrypted with Ansible Vault. Vault decrypts it when needed, so protect the control node and its temporary files as well:

```bash
ansible-vault view group_vars/all/vault.yml    # inspect (prompts for the vault password)
ansible-vault edit group_vars/all/vault.yml    # edit in place
```

Vault encrypts the file at rest, but a committed encrypted file can still be attacked offline if its Vault password is weak. Use unique test credentials and keep your local Vault out of commits. The user-creation task uses `no_log` to reduce accidental disclosure in Ansible output; this does not replace secure credential handling.

## Verifying the pipeline manually

```bash
sudo systemctl start pg_backup.service
sudo -u postgres cat /var/backups/postgres/backup.log

sudo systemctl start pg_verify_restore.service
sudo -u postgres cat /var/backups/postgres/verify.log
```

A successful run of the pipeline produces a log entry like:

```
Verification OK: /var/backups/postgres/inventory_db_20260924_163243.a1b2c3.sql.gz (3 rows match)
```

That line records that the restore command completed and the row counts matched for this one table at that moment. It does **not** establish that all database contents are identical or that recovery meets production requirements.

## Local simulated tests

These tests require Python 3, Bash and standard GNU/Linux utilities. They use fake PostgreSQL commands and temporary files: no PostgreSQL server or real database is accessed.

```bash
python3 -m unittest discover -s tests -v
```

They cover successful and failed dumps, missing backups, restore errors, database creation errors, cleanup, the retention boundary of `find -mtime +7`, and rejection of invalid database names or retention values. They do not replace an integration test against a disposable PostgreSQL server.

## Continuous integration

The GitHub Actions workflow in `.github/workflows/ci.yml` runs on pushes and pull requests (see the badge above for the latest result). On its disposable GitHub-hosted runner it installs ShellCheck, the pinned Ansible tools and the collection, then runs the simulated tests, Bash syntax and ShellCheck against rendered scripts, Ansible syntax validation, and ansible-lint.

The same checks can be run locally when Python, Jinja2, Bash, ShellCheck, Ansible Core 2.22.0, ansible-lint 26.11.0 and the collection in `requirements.yml` are already installed:

```bash
python3 -m unittest discover -s tests -v
python3 scripts/check_templates.py
python3 scripts/check_ansible.py
```

The static Ansible helper uses a temporary copy of the roles and playbook with a synthetic inventory. It does not load the repository Vault or connect to a target. These checks do not replace the VM test below or verify PostgreSQL and timer behavior.

## Disposable VM test

On a disposable Ubuntu 22.04.5 LTS QEMU/libvirt VM, a temporary copy of the preceding working revision was applied with Ansible Core 2.22.0 and `community.postgresql` 4.2.0. The run completed with `ok=14`, `changed=11`, `unreachable=0`, and `failed=0`. Both systemd timers were enabled and listed.

The backup service was started manually and completed successfully, producing a compressed backup. The restore verification service was then started manually and completed successfully; its log reported that the `inventory` row counts matched (3 rows). Afterward, the source table still had 3 rows, and a query found no databases whose names began with `backup_verify_`.

A repeat playbook run in the same lab completed with `ok=13`, `changed=0`, `unreachable=0`, and `failed=0`, including the seed task. After the filename-selection change, a further run completed with `ok=13`, `changed=2`, `unreachable=0`, and `failed=0`, updating the two scripts. The updated restore service successfully verified the existing backup. It was run again after creating a newer empty decoy file with a similar database-name prefix; it ignored the decoy and restored the intended backup.

The decoy's modification time was then set to 20 days in the past. The updated backup service created a new backup and left the decoy in place. This checked that retention did not delete that similarly named file; deletion of an eligible old backup belonging to the same database was not tested in the VM. These are observed results for that state and toolchain, not guarantees for all versions or target states. Timer execution at the scheduled time, application-user access, and recovery after a server failure have not been tested in this VM.

## Design decisions

- **systemd timers instead of cron**: with `Persistent=true`, a timer catches up on a missed run (e.g. the VM was off at the scheduled time) instead of silently skipping it — a meaningful difference for something as important as a backup schedule.
- **`become_user: postgres` + SSH pipelining**: tasks that must run as the `postgres` system user (not root) require pipelining enabled in `ansible.cfg`; without it, Ansible's temp-file privilege handoff between the SSH user and the target user fails on this kind of setup.
- **Restrictive permissions on the backup directory (`0750`, owned by `postgres`)**: only the database owner can read backup contents — a deliberate least-privilege choice, not an oversight.
- **Ansible Vault for the database password**: the only secret in this project, and the only variable that needed it — everything else stays in plain `group_vars` for easy review.

## Known limitations

- **Chained tasks under `--check`**: enabling the systemd timers depends on the unit files existing for real, which `--check` never writes to disk. Check mode has not been tested on a clean VM for the current revision.
- **Seed data and change reporting**: the SQL seed uses `ON CONFLICT DO NOTHING`, and the repeat run reported no changes with the tested collection version. Behavior with other versions or database states has not been tested.
- **Application privileges not verified**: user creation and database privileges were applied on the lab VM using `community.postgresql` 4.2.0, but access as the application user was not tested. Database-level privileges do not automatically grant access to tables or sequences.
- **Local lab environment**: unlike a real always-on server, the libvirt lab VM must be started manually (`virsh start <vm>`) after the host machine reboots — a constraint of the local lab setup, not of the playbook itself. Timers with `Persistent=true` catch up on the missed run once the VM is running again.
- **Limited restore check**: row counts do not compare row contents, other tables, roles, or permissions. Changes to the live table after the backup can also cause a mismatch even if the backup restored correctly.
- **Cleanup after interruption**: normal failures trigger cleanup of the temporary database, but an uncatchable termination or machine failure can leave it behind. Review the PostgreSQL databases before manually removing anything.
- **Local backups only**: backups are not encrypted or copied off-host; a server or disk failure can affect both the database and its backups.
- **Lab-only database names**: the backup scripts accept only letters, digits and underscores in `db_name`.
- **Test scope**: the simulated tests do not exercise PostgreSQL or systemd; they do check the retention age boundary with fake files. The VM test covered first and repeat playbook runs, both updated services, selection with a newer similar-prefix decoy, and retaining that decoy when it was old. Scheduled execution, removal of an eligible old backup, and failure recovery still need testing against a real PostgreSQL server.

## Next improvements

- Off-site backup copy (rsync to another host, or object storage)
- Encrypt backups at rest
- Alert (email/Slack) on verification failure instead of only logging it
- Parameterize retention and schedule via extra-vars instead of hardcoded role defaults

## License

MIT — see [LICENSE](LICENSE)
