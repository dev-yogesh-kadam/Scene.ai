import json
import os
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


# Set to a PostgreSQL database that may be emptied (postgresql://scene_test:...@localhost:5432/scene_test) to run the
# tests against PostgreSQL instead of SQLite. Every test starts with that database empty.
POSTGRES = os.environ.get("SCENE_TEST_DATABASE_URL", "")


def empty_postgres():
    import psycopg
    with psycopg.connect(POSTGRES, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")


@pytest.fixture
def client(tmp_path):
    """The app with empty storage and a render server address nothing listens on."""
    if POSTGRES:
        empty_postgres()
    settings = Settings(database_url=POSTGRES, comfy_url="http://127.0.0.1:9", ollama_url="http://127.0.0.1:9", storage_dir=str(tmp_path), signup_credits=500, first_account_local=False,
                        workflows_dir=str(ROOT / "workflows"), frontend_dir=str(ROOT / "frontend"))
    with TestClient(create_app(settings)) as test_client:
        # The video workflow is a normal ComfyUI save: it is read with the node definitions a real server gave.
        test_client.app.state.catalog.saved = json.loads((BACKEND / "tests" / "fixtures" / "node_definitions.json").read_text(encoding="utf-8"))
        yield test_client
