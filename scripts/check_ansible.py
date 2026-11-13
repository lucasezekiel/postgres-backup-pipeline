"""Run static Ansible checks without loading a real inventory or Vault."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix="postgres-ansible-check-") as tmp:
        lab = Path(tmp)
        shutil.copytree(ROOT / "roles", lab / "roles")
        shutil.copy2(ROOT / "site.yml", lab / "site.yml")
        config = lab / "ansible.cfg"
        config.write_text("[defaults]\n", encoding="utf-8")
        env = os.environ.copy()
        env.update(
            ANSIBLE_CONFIG=str(config),
            ANSIBLE_LOCAL_TEMP=str(lab / "ansible-tmp"),
            XDG_CACHE_HOME=str(lab / "cache"),
        )
        subprocess.run(
            ["ansible-playbook", "-i", "localhost,", "site.yml", "--syntax-check"],
            cwd=lab,
            env=env,
            check=True,
        )
        subprocess.run(
            ["ansible-lint", "--offline", "--nocolor", "site.yml"],
            cwd=lab,
            env=env,
            check=True,
        )


if __name__ == "__main__":
    main()
