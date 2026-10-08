import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from scene.config import Settings  # noqa: E402
from scene import security  # noqa: E402
from scene.main import create_app  # noqa: E402


@pytest.fixture(autouse=True)
def quick_hashes(monkeypatch):
    """Passwords hashed at a small fraction of the real strength: the tests make many accounts."""
    monkeypatch.setattr(security, "SCRYPT", {"n": 2 ** 10, "r": 8, "p": 1, "dklen": 32})


@pytest.fixture
def client(tmp_path):
    """The app with empty storage and a render server address nothing listens on."""
    settings = Settings(comfy_url="http://127.0.0.1:9", ollama_url="http://127.0.0.1:9", storage_dir=str(tmp_path), signup_credits=500, first_account_local=False,
                        workflows_dir=str(ROOT / "workflows"), frontend_dir=str(ROOT / "frontend"))
    with TestClient(create_app(settings)) as test_client:
        # The video workflow is a normal ComfyUI save: it is read with the node definitions a real server gave.
        test_client.app.state.catalog.saved = json.loads((BACKEND / "tests" / "fixtures" / "node_definitions.json").read_text(encoding="utf-8"))
        yield test_client
