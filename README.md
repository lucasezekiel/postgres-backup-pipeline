# PostgreSQL Backup Pipeline

An Ansible project that provisions a PostgreSQL database and automates its backup lifecycle end to end: scheduled dumps, retention cleanup, and — critically — automated restore verification, so a backup's integrity is confirmed before it's ever actually needed.

## What it does

**`postgresql` role**

- Installs PostgreSQL and its Python bindings
- Creates a database and an application user (password supplied via Ansible Vault)
- Loads a seed schema and sample data, idempotently (`INSERT ... ON CONFLICT DO NOTHING`)

**`backup` role**

- Daily automated `pg_dump`, compressed and timestamped
- Retention cleanup: backups older than 7 days are deleted automatically
- Weekly restore verification: restores the latest backup into a disposable database, compares row counts against the live database via SQL, and logs the result — then drops the test database
- Both jobs are scheduled with **systemd timers** rather than cron

## Project structure

```
├── ansible.cfg                    # default inventory path + SSH pipelining
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
└── site.yml
```

## Requirements

- Ansible ≥ 2.16 on the control node
- `community.postgresql` collection: `ansible-galaxy collection install community.postgresql`
- A target server reachable via SSH (tested against Ubuntu 22.04 LTS via Multipass)
- The Vault password (set at creation time, required for every run)

## Usage

```bash
# Verify connectivity
ansible all -m ping

# Simulate changes without applying them
ansible-playbook site.yml --check --diff --ask-vault-pass

# Apply for real
ansible-playbook site.yml --ask-vault-pass
```

## Secrets management

The database password is never stored in plain text. It lives in `group_vars/all/vault.yml`, encrypted with Ansible Vault:

```bash
ansible-vault view group_vars/all/vault.yml    # inspect (prompts for the vault password)
ansible-vault edit group_vars/all/vault.yml    # edit in place
```

The encrypted file is safe to commit — anyone browsing the repository sees ciphertext, never the credential.

## Verifying the pipeline manually

```bash
sudo systemctl start pg_backup.service
sudo -u postgres cat /var/backups/postgres/backup.log

sudo systemctl start pg_verify_restore.service
sudo -u postgres cat /var/backups/postgres/verify.log
```

A successful run of the pipeline produces a log entry like:

```
Verification OK: /var/backups/postgres/inventory_db_20260924_163243.sql.gz (3 rows match)
```

That line is the actual proof the backup is restorable — not just that a file exists.

## Design decisions

- **systemd timers instead of cron**: with `Persistent=true`, a timer catches up on a missed run (e.g. the VM was off at the scheduled time) instead of silently skipping it — a meaningful difference for something as important as a backup schedule.
- **`become_user: postgres` + SSH pipelining**: tasks that must run as the `postgres` system user (not root) require pipelining enabled in `ansible.cfg`; without it, Ansible's temp-file privilege handoff between the SSH user and the target user fails on this kind of setup.
- **Restrictive permissions on the backup directory (`0750`, owned by `postgres`)**: only the database owner can read backup contents — a deliberate least-privilege choice, not an oversight.
- **Ansible Vault for the database password**: the only secret in this project, and the only variable that needed it — everything else stays in plain `group_vars` for easy review.

## Known limitations

- **Chained tasks under `--check`**: enabling the systemd timers depends on the unit files existing for real, which `--check` never writes to disk — a now-familiar pattern from earlier in this project series. The real run applies cleanly.
- **`postgresql_query` always reports `changed`**: the module has no way to inspect whether an arbitrary SQL script actually changed anything, so it reports `changed` on every run even when the seed data is already present. Idempotency is still enforced at the SQL level (`ON CONFLICT DO NOTHING`); Ansible just can't *report* it as `ok` in this case.
- **`priv` parameter deprecation**: `community.postgresql.postgresql_user`'s `priv` parameter is deprecated and scheduled for removal in v4.0.0 of the collection. Functional today; worth migrating before upgrading the collection.
- **Local lab environment**: unlike a real always-on server, the Multipass VM must be started manually (`multipass start postgres-target`) after the host machine reboots or resumes from suspend — a constraint of the local lab setup, not of the playbook itself.

## Next improvements

- Off-site backup copy (rsync to another host, or object storage)
- Encrypt backups at rest
- Alert (email/Slack) on verification failure instead of only logging it
- Parameterize retention and schedule via extra-vars instead of hardcoded role defaults

## License

MIT — see [LICENSE](LICENSE)
