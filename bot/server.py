"""API e painel servidos na mesma origem via Caddy."""
import asyncio
import os
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.staticfiles import StaticFiles

from .runtime import SimulationRuntime
from .workspace import router as workspace_router
from .monitor import router as monitor_router
from .monitor_scheduler import router as schedule_router, scheduler_loop

runtime = SimulationRuntime()


@asynccontextmanager
async def lifespan(_app):
    task = asyncio.create_task(scheduler_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await runtime.stop()


app = FastAPI(title="Ticket Orchestrator - homologação", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


def check_api_key(x_api_key: str | None = Header(default=None)):
    configured = os.getenv("API_KEY", "")
    if not configured or configured.startswith("SUBSTITUA_") or len(configured) < 32:
        raise HTTPException(status_code=503, detail="API_KEY não configurada corretamente")
    if x_api_key is None or not secrets.compare_digest(x_api_key, configured):
        raise HTTPException(status_code=403, detail="Acesso não autorizado")


@app.get("/health")
async def health():
    return {"status": "ok", "time": time.time(), "mode": "simulation"}


@app.get("/api/status", dependencies=[Depends(check_api_key)])
async def status():
    return runtime.status()


@app.post("/api/start", dependencies=[Depends(check_api_key)])
async def start():
    return await runtime.start()


@app.post("/api/stop", dependencies=[Depends(check_api_key)])
async def stop():
    return await runtime.stop()


# Na VPS o volume do dashboard é montado em /dashboard.
# Localmente, o servidor usa dashboard/ na raiz do projeto.
dashboard_dir = Path(os.getenv("DASHBOARD_DIR", "/dashboard"))
if not dashboard_dir.is_dir():
    dashboard_dir = Path(__file__).resolve().parents[1] / "dashboard"
app.include_router(workspace_router, dependencies=[Depends(check_api_key)])
app.include_router(monitor_router, dependencies=[Depends(check_api_key)])
app.include_router(schedule_router, dependencies=[Depends(check_api_key)])

app.mount("/", StaticFiles(directory=dashboard_dir, html=True), name="dashboard")
