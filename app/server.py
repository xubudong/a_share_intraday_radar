from __future__ import annotations

from contextlib import asynccontextmanager
import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import ROOT_DIR
from .instance import APP_ID, root_fingerprint
from .notes import sector_note_store
from .service import radar_service


@asynccontextmanager
async def lifespan(_: FastAPI):
    radar_service.start_refresh(force_history=False)
    yield


app = FastAPI(title="A Share Intraday Radar", version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT_DIR / "static"), name="static")


class ToggleStarRequest(BaseModel):
    code: str


class SectorNoteRequest(BaseModel):
    scope: str
    content: str


@app.get("/")
def index() -> FileResponse:
    return FileResponse(ROOT_DIR / "static" / "index.html")


@app.get("/api/instance")
def instance() -> dict:
    return {
        "app_id": APP_ID,
        "pid": os.getpid(),
        "root_fingerprint": root_fingerprint(ROOT_DIR),
    }


@app.get("/api/dashboard")
def dashboard() -> dict:
    return radar_service.dashboard()


@app.get("/api/stocks")
def stocks() -> dict:
    return radar_service.stocks_payload()


@app.post("/api/refresh")
def refresh(force_history: bool = False) -> dict:
    return radar_service.start_refresh(force_history=force_history)


@app.post("/api/toggle-star")
def toggle_star(req: ToggleStarRequest) -> dict:
    new_state = radar_service.toggle_star(req.code)
    return {"code": req.code, "star": new_state}


@app.get("/api/snapshots")
def list_snapshots() -> list:
    return radar_service.list_snapshots()


@app.get("/api/snapshots/{snapshot_id}")
def get_snapshot(snapshot_id: str) -> dict:
    data = radar_service.load_snapshot(snapshot_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return data


@app.delete("/api/snapshots/{snapshot_id}")
def delete_snapshot(snapshot_id: str) -> dict:
    if not radar_service.delete_snapshot(snapshot_id):
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return {"id": snapshot_id, "deleted": True}


@app.get("/api/sector-notes")
def list_sector_notes(scope: str) -> list:
    try:
        return sector_note_store.list_notes(scope)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.put("/api/sector-notes/{note_date}")
def save_sector_note(note_date: str, req: SectorNoteRequest) -> dict:
    try:
        return sector_note_store.upsert_note(req.scope, note_date, req.content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.delete("/api/sector-notes/{note_date}")
def delete_sector_note(note_date: str, scope: str) -> dict:
    try:
        deleted = sector_note_store.delete_note(scope, note_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Sector note not found")
    return {"scope": scope, "date": note_date, "deleted": True}


@app.get("/api/health")
def health() -> dict:
    return radar_service.health()
