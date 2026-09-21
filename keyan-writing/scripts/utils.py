"""Small packaging helpers shared by integrations and examples."""
from pathlib import Path


def skill_root() -> Path:
    """Return the installed skill directory from this file's location."""
    return Path(__file__).resolve().parent.parent


def cli_path() -> Path:
    """Return the canonical CLI path used by the package entrypoint."""
    return skill_root() / "scripts" / "main.py"
