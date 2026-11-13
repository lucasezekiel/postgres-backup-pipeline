"""Render the lab scripts with sample values and run static shell checks."""

from pathlib import Path
import subprocess
import tempfile

from jinja2 import Environment, FileSystemLoader, StrictUndefined


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT / "roles" / "backup" / "templates"
ENVIRONMENT = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR),
    undefined=StrictUndefined,
    autoescape=False,
    keep_trailing_newline=True,
)
VALUES = {
    "backup_dir": "/var/backups/example",
    "db_name": "example_db",
    "backup_retention_days": 7,
}


def main():
    with tempfile.TemporaryDirectory(prefix="postgres-template-check-") as tmp:
        scripts = []
        for name in ("pg_backup.sh.j2", "pg_verify_restore.sh.j2"):
            script = Path(tmp) / name.removesuffix(".j2")
            script.write_text(ENVIRONMENT.get_template(name).render(**VALUES), encoding="utf-8")
            subprocess.run(["bash", "-n", str(script)], check=True)
            scripts.append(str(script))
        subprocess.run(["shellcheck", "-s", "bash", *scripts], check=True)
    print("Rendered Bash syntax and ShellCheck passed.")


if __name__ == "__main__":
    main()
