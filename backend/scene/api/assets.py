"""The file of a NeuralCore entry (a row of assets). Assets are kept only in a project's NeuralCore (see kit.py and
api/kit.py, which add, change and remove them); there are no saved assets of their own any more."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from .deps import current_user

router = APIRouter(prefix="/api/assets", tags=["assets"])


def _folder(request, user):
    folder = request.app.state.assets_dir / str(user["id"])
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _own(request, user, asset_id):
    row = request.app.state.db.one("SELECT * FROM assets WHERE id = ? AND user_id = ?", (asset_id, user["id"]))
    if row is None:
        raise HTTPException(404, "No such asset.")
    return row


@router.get("/{asset_id}/file")
async def get_file(asset_id: int, request: Request, user: dict = Depends(current_user)):
    row = _own(request, user, asset_id)
    path = _folder(request, user) / row["filename"]
    if not path.is_file():
        raise HTTPException(404, "The file is missing from storage.")
    return FileResponse(path)
