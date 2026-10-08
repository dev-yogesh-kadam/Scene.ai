"""Run the app:  python -m scene  (from the backend folder)."""

import uvicorn

from .config import load_settings
from .main import create_app

settings = load_settings()
print("Scene.ai is running at http://localhost:{}".format(settings.port))
uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="warning")
