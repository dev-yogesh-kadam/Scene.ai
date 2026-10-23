"""Run the app:  python -m scene  (from the backend folder).

One server listens on two ports: the studio's, and the admin console's (main.Doors sends each request to its site).
"""

import socket
import sys

import uvicorn

from .config import load_settings
from .main import Doors, create_app


def listen(host, port):
    try:
        return socket.create_server((host, port), family=socket.AF_INET6 if ":" in host else socket.AF_INET)
    except OSError as e:
        sys.exit("Scene.ai can't listen on {}:{} ({}). Is it running already?".format(host, port, e.strerror or e))


settings = load_settings()
app = create_app(settings)
sockets = [listen(settings.host, settings.port)]
print("Scene.ai is running at http://localhost:{}".format(settings.port))
if app.state.console is not None:
    sockets.append(listen(settings.console_host, settings.console_port))
    shown = "localhost" if settings.console_host in ("127.0.0.1", "::1", "0.0.0.0", "::") else settings.console_host
    print("The admin console is at http://{}:{}".format(shown, settings.console_port))
uvicorn.Server(uvicorn.Config(Doors(app), log_level="warning")).run(sockets=sockets)
