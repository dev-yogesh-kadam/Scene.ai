import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from scene.config import Settings  # noqa: E402
from scene.main import create_app  # noqa: E402


@pytest.fixture
def client(tmp_path):
    """The app with empty storage and a render server address nothing listens on."""
    settings = Settings(comfy_url="http://127.0.0.1:9", storage_dir=str(tmp_path),
                        workflows_dir=str(ROOT / "workflows"), frontend_dir=str(ROOT / "frontend"))
    with TestClient(create_app(settings)) as test_client:
        yield test_client
