"""Exercise rendered scripts with fake PostgreSQL commands; no database is used."""

import gzip
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "roles" / "backup" / "templates"

FAKE_COMMAND = r'''#!/bin/bash
set -eu
command=${0##*/}
printf '%s %s\n' "$command" "$*" >> "$CALLS"
case "$command" in
  pg_dump)
    printf 'sample SQL\n'
    exit "${FAIL_DUMP:-0}"
    ;;
  createdb) exit "${FAIL_CREATE:-0}" ;;
  dropdb) exit "${FAIL_DROP:-0}" ;;
  psql)
    case " $* " in
      *" -c "*)
        case " $* " in
          *" -d inventory_db "*) printf '%s\n' "${LIVE_COUNT:-3}" ;;
          *) printf '%s\n' "${RESTORED_COUNT:-3}" ;;
        esac
        ;;
      *) cat > "$RESTORE_CAPTURE"; exit "${FAIL_RESTORE:-0}" ;;
    esac
    ;;
esac
'''


class BackupScriptsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.backups = self.root / "backups"
        self.backups.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.calls = self.root / "calls"
        for name in ("pg_dump", "createdb", "dropdb", "psql"):
            command = self.bin / name
            command.write_text(FAKE_COMMAND)
            command.chmod(0o755)

    def run_script(self, template, **overrides):
        text = (TEMPLATES / template).read_text()
        for key, value in {
            "backup_dir": str(self.backups),
            "db_name": "inventory_db",
            "backup_retention_days": "7",
        }.items():
            text = text.replace("{{ " + key + " }}", value)
        script = self.root / "script.sh"
        script.write_text(text)
        env = os.environ.copy()
        env.update(
            PATH=f"{self.bin}:{env['PATH']}",
            CALLS=str(self.calls),
            RESTORE_CAPTURE=str(self.root / "restore.sql"),
            **overrides,
        )
        return subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True)

    def calls_text(self):
        return self.calls.read_text() if self.calls.exists() else ""

    def create_backup(self):
        with gzip.open(self.backups / "inventory_db_20260924_163243.sql.gz", "wt") as backup:
            backup.write("sample SQL\n")

    def test_successful_dump_is_published(self):
        result = self.run_script("pg_backup.sh.j2")
        self.assertEqual(result.returncode, 0, result.stderr)
        files = list(self.backups.glob("inventory_db_*.sql.gz"))
        self.assertEqual(len(files), 1)
        with gzip.open(files[0], "rt") as backup:
            self.assertEqual(backup.read(), "sample SQL\n")
        self.assertFalse(list(self.backups.glob(".*")))

    def test_failed_dump_leaves_no_backup_or_temp_file(self):
        result = self.run_script("pg_backup.sh.j2", FAIL_DUMP="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(self.backups.iterdir()), [])

    def test_failed_dump_does_not_run_retention(self):
        self.create_backup()
        backup = self.backups / "inventory_db_20260924_163243.sql.gz"
        old = time.time() - 20 * 24 * 60 * 60
        os.utime(backup, (old, old))
        result = self.run_script("pg_backup.sh.j2", FAIL_DUMP="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(backup.exists())

    def test_missing_backup_does_not_touch_databases(self):
        result = self.run_script("pg_verify_restore.sh.j2")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls_text(), "")
        self.assertIn("No backup found", (self.backups / "verify.log").read_text())

    def test_restore_uses_error_stop_and_cleans_up_created_database(self):
        self.create_backup()
        result = self.run_script("pg_verify_restore.sh.j2")
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls_text().splitlines()
        created_name = calls[0].split()[-1]
        self.assertTrue(created_name.startswith("backup_verify_"))
        self.assertIn("ON_ERROR_STOP=1", calls[1])
        self.assertEqual(calls[-1], f"dropdb -- {created_name}")

    def test_failed_restore_cleans_up_created_database(self):
        self.create_backup()
        result = self.run_script("pg_verify_restore.sh.j2", FAIL_RESTORE="1")
        self.assertNotEqual(result.returncode, 0)
        calls = self.calls_text().splitlines()
        self.assertEqual(calls[-1], f"dropdb -- {calls[0].split()[-1]}")

    def test_count_mismatch_is_reported_and_database_removed(self):
        self.create_backup()
        result = self.run_script("pg_verify_restore.sh.j2", LIVE_COUNT="4")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("VERIFICATION FAILED", (self.backups / "verify.log").read_text())
        calls = self.calls_text().splitlines()
        self.assertEqual(calls[-1], f"dropdb -- {calls[0].split()[-1]}")

    def test_corrupt_archive_fails_and_database_is_removed(self):
        (self.backups / "inventory_db_20260924_163243.sql.gz").write_bytes(b"not gzip")
        result = self.run_script("pg_verify_restore.sh.j2")
        self.assertNotEqual(result.returncode, 0)
        calls = self.calls_text().splitlines()
        self.assertEqual(calls[-1], f"dropdb -- {calls[0].split()[-1]}")

    def test_restore_ignores_newer_backup_from_similar_database(self):
        self.create_backup()
        other = self.backups / "inventory_db_archive_20261113_113004.sql.gz"
        with gzip.open(other, "wt") as backup:
            backup.write("wrong database\n")
        future = time.time() + 60
        os.utime(other, (future, future))
        result = self.run_script("pg_verify_restore.sh.j2")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / "restore.sql").read_text(), "sample SQL\n")

    def test_only_similar_database_backup_is_treated_as_missing(self):
        other = self.backups / "inventory_db_archive_20261113_113004.aB123c.sql.gz"
        with gzip.open(other, "wt") as backup:
            backup.write("wrong database\n")
        result = self.run_script("pg_verify_restore.sh.j2")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls_text(), "")
        self.assertIn("No backup found", (self.backups / "verify.log").read_text())

    def test_restore_accepts_current_backup_format(self):
        current = self.backups / "inventory_db_20261113_113004.aB123c.sql.gz"
        with gzip.open(current, "wt") as backup:
            backup.write("current backup\n")
        result = self.run_script("pg_verify_restore.sh.j2")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / "restore.sql").read_text(), "current backup\n")

    def test_retention_keeps_backups_of_similar_database(self):
        self.create_backup()
        legacy = self.backups / "inventory_db_20260924_163243.sql.gz"
        current = self.backups / "inventory_db_20260924_163244.aB123c.sql.gz"
        other = self.backups / "inventory_db_archive_20260924_163243.sql.gz"
        custom = self.backups / "inventory_db_custom.sql.gz"
        current.write_bytes(b"old lab backup")
        other.write_bytes(b"other database backup")
        custom.write_bytes(b"nonstandard backup")
        old = time.time() - 20 * 24 * 60 * 60
        for path in (legacy, current, other, custom):
            os.utime(path, (old, old))
        result = self.run_script("pg_backup.sh.j2")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(legacy.exists())
        self.assertFalse(current.exists())
        self.assertTrue(other.exists())
        self.assertTrue(custom.exists())

    def test_failed_creation_never_drops_a_database(self):
        self.create_backup()
        result = self.run_script("pg_verify_restore.sh.j2", FAIL_CREATE="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("dropdb", self.calls_text())

    def test_cleanup_failure_is_reported(self):
        self.create_backup()
        result = self.run_script("pg_verify_restore.sh.j2", FAIL_DROP="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Failed to remove temporary database", result.stderr)


if __name__ == "__main__":
    unittest.main()
