@echo off
rem Start Scene.ai on Windows. The first run creates a Python environment in .venv.
cd /d "%~dp0.."
if not exist .venv\Scripts\python.exe (
    py -3 -m venv .venv 2>nul || python -m venv .venv || goto :fail
)
.venv\Scripts\python.exe -m pip install -q --disable-pip-version-check -r backend\requirements.txt || goto :fail
if not exist config.json copy config.example.json config.json >nul
rem Motion graphics need Node.js. Without it the studio still runs; that section just says what is missing.
where node >nul 2>nul && if not exist motion\node_modules\hyperframes ( pushd motion & call npm install --no-audit --no-fund & popd )
cd backend
..\.venv\Scripts\python.exe -m scene
:fail
pause
