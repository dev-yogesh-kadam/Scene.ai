"""Application settings: defaults, then config.json in the project root, then SCENE_* environment variables."""

import json
import os
from dataclasses import dataclass, fields
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Settings:
    comfy_url: str = "http://127.0.0.1:8188"
    host: str = "0.0.0.0"
    port: int = 8080
    workflows_dir: str = "workflows"
    storage_dir: str = "storage"
    frontend_dir: str = "frontend"
    default_workflow: str = ""
    allow_signup: bool = True
    session_days: int = 30
    secure_cookies: bool = False  # set true when the app is served over https
    signup_credits: int = 500     # credits a new account starts with
    credits_per_minute: float = 10.0  # cost of one estimated GPU minute
    credits_unknown: int = 20     # cost per clip when a workflow has no time estimate yet

    def path(self, name):
        path = Path(getattr(self, name)).expanduser()
        return path if path.is_absolute() else ROOT / path


def load_settings(config_file=None):
    settings = Settings()
    config_file = Path(config_file or os.environ.get("SCENE_CONFIG") or ROOT / "config.json")
    saved = json.loads(config_file.read_text(encoding="utf-8")) if config_file.is_file() else {}
    for field in fields(Settings):
        value = os.environ.get("SCENE_" + field.name.upper(), saved.get(field.name))
        if value is None:
            continue
        if field.type is bool and isinstance(value, str):
            value = value.lower() in ("1", "true", "yes", "on")
        setattr(settings, field.name, field.type(value))
    return settings
