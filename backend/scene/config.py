"""Application settings: defaults, then config.json in the project root, then SCENE_* environment variables."""

import json
import os
from dataclasses import dataclass, fields
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Settings:
    comfy_url: str = "http://127.0.0.1:8188"
    ollama_url: str = "http://127.0.0.1:11434"  # the language model server the agent uses
    agent_model: str = ""         # the model the agent uses unless the user picks another; empty = the first one there is
    # Hosted models beside the local ones. Each service is offered once its key is set. Keep keys in config.json
    # (which git ignores) or in SCENE_API_KEY / SCENE_GEMINI_KEY, never in a file that is committed.
    api_name: str = "Kimi"        # what the first service is called in the model picker
    api_url: str = ""             # any service that speaks the OpenAI chat API; for Kimi: https://api.moonshot.ai/v1
    api_key: str = ""
    api_models: str = ""          # model names, comma separated, for example "kimi-k2.6"; empty = ask the service
    gemini_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    gemini_key: str = ""          # a Google Gemini API key, from aistudio.google.com
    gemini_models: str = ""       # for example "gemini-3.8-flash"; empty = ask Google and offer its Pro and Flash models
    host: str = "0.0.0.0"
    port: int = 8080
    workflows_dir: str = "workflows"
    storage_dir: str = "storage"
    output_dir: str = ""          # where finished images and videos are kept; empty = "outputs" inside storage_dir
    frontend_dir: str = "frontend"
    node_path: str = ""           # the Node.js program that renders motion graphics; empty = the one that is installed
    default_workflow: str = ""
    allow_signup: bool = True
    session_days: int = 30
    secure_cookies: bool = False  # set true when the app is served over https
    signup_credits: int = 1000    # credits a new account starts with
    signups_per_day: int = 3      # new accounts one visitor address may make in a day; 0 = no limit

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
