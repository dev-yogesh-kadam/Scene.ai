"""The state of the user's long runs (runs.py): read, write, list and check, for the agent and for the Agent tab."""

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import runs
from .deps import current_user

router = APIRouter(prefix="/api", tags=["runs"])


def _guarded(work):
    try:
        return work()
    except runs.RunError as error:
        raise HTTPException(400, str(error))


@router.get("/runs")
async def list_runs(request: Request, user: dict = Depends(current_user)):
    return {"runs": runs.listing(request.app.state.db, user["id"])}


@router.get("/runs/{run}/state")
async def read_state(run: str, request: Request, path: str, offset: int = 0, limit: int = runs.PAGE, user: dict = Depends(current_user)):
    return _guarded(lambda: runs.read(request.app.state.db, user["id"], run, path, offset, limit))


@router.put("/runs/{run}/state")
async def write_state(run: str, body: dict, request: Request, user: dict = Depends(current_user)):
    """Body: {"path", "value", "writer"?}; "append": true adds the value as one line of the list at the path."""
    db = request.app.state.db
    if "value" not in body:
        raise HTTPException(400, "Give the value to keep.")
    if body.get("append") is True:
        return _guarded(lambda: runs.append(db, user["id"], run, body.get("path"), body["value"], body.get("writer")))
    return _guarded(lambda: runs.write(db, user["id"], run, body.get("path"), body["value"], body.get("writer")))


@router.delete("/runs/{run}/state")
async def delete_state(run: str, request: Request, path: str, user: dict = Depends(current_user)):
    return {"deleted": _guarded(lambda: runs.delete(request.app.state.db, user["id"], run, path))}


@router.get("/runs/{run}/budget")
async def read_budget(run: str, request: Request, user: dict = Depends(current_user)):
    return _guarded(lambda: runs.budget(request.app.state.db, user["id"], run))


@router.put("/runs/{run}/budget")
async def write_budget(run: str, body: dict, request: Request, user: dict = Depends(current_user)):
    """{"credits": a whole number, or null for no limit}. The agent cannot set it: its tools refuse the path."""
    return _guarded(lambda: runs.set_budget(request.app.state.db, user["id"], run, body.get("credits")))


@router.get("/runs/{run}/coverage")
async def check_coverage(run: str, request: Request, path: str, against: str, user: dict = Depends(current_user)):
    """Whether every name under `against` has one under `path`: {"ok", "missing", "extra", "count"}."""
    return _guarded(lambda: runs.coverage(request.app.state.db, user["id"], run, path, against))
