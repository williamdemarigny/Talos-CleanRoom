"""FastAPI application entry point for Talos CleanRoom Deployment Web UI."""

from fastapi import FastAPI, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from pathlib import Path

import talos_common
from app.config import get_settings, Settings
from app.routers import auth, deployment, config, websocket
from talos_common.routers.exchange import router as exchange_router
from talos_common.routers.oidc import router as oidc_router
from app.auth import get_current_user_optional

# Initialize talos_common with our settings getter so shared modules
# (auth dependencies, routers) can resolve settings via Depends().
talos_common.init(get_settings)

# Application root directory
APP_DIR = Path(__file__).parent
STATIC_DIR = APP_DIR.parent / "static"
TEMPLATES_DIR = APP_DIR.parent / "templates"

app = FastAPI(
    title="Talos CleanRoom Deployment",
    description="Web UI for deploying Talos Kubernetes clusters",
    version="1.0.0"
)

# Mount static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Setup templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Include routers
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(exchange_router, prefix="/api/auth", tags=["Authentication"])
app.include_router(oidc_router, tags=["OIDC"])
app.include_router(deployment.router, prefix="/api/deployment", tags=["Deployment"])
app.include_router(config.router, prefix="/api/config", tags=["Configuration"])
app.include_router(websocket.router, tags=["WebSocket"])


@app.get("/")
async def index(request: Request, user: dict = Depends(get_current_user_optional)):
    """Render the dashboard or redirect to login."""
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user,
        "page": "dashboard"
    })


@app.get("/login")
async def login_page(request: Request):
    """Render the login page."""
    settings = get_settings()
    return templates.TemplateResponse("login.html", {
        "request": request,
        "oidc_enabled": bool(settings.oidc_issuer_url),
    })


@app.get("/config")
async def config_page(request: Request, user: dict = Depends(get_current_user_optional)):
    """Render the configuration editor page."""
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse("config.html", {
        "request": request,
        "user": user,
        "page": "config"
    })


@app.get("/deployment")
async def deployment_page(request: Request, user: dict = Depends(get_current_user_optional)):
    """Render the deployment monitor page."""
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse("deployment.html", {
        "request": request,
        "user": user,
        "page": "deployment"
    })


@app.get("/logs")
async def logs_page(request: Request, user: dict = Depends(get_current_user_optional)):
    """Render the logs viewer page."""
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse("logs.html", {
        "request": request,
        "user": user,
        "page": "logs"
    })


@app.get("/api/system/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/api/system/dependencies")
async def check_dependencies(settings: Settings = Depends(get_settings)):
    """Check if required system dependencies are installed."""
    import shutil
    results = []
    for dep in settings.dependencies:
        path = shutil.which(dep)
        results.append({
            "name": dep,
            "installed": path is not None,
            "path": path
        })
    all_installed = all(r["installed"] for r in results)
    return {
        "all_installed": all_installed,
        "dependencies": results
    }
