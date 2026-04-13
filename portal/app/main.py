"""FastAPI application entry point for Talos CleanRoom Unified Portal."""

from fastapi import FastAPI, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from pathlib import Path

import talos_common
from talos_common.auth import get_current_user_optional
from talos_common.routers.auth import router as auth_router

from app.config import get_settings
from app.routers import portal, credentials

# Initialize talos_common with our settings getter
talos_common.init(get_settings)

# Application root directory
APP_DIR = Path(__file__).parent
STATIC_DIR = APP_DIR.parent / "static"
TEMPLATES_DIR = APP_DIR.parent / "templates"

app = FastAPI(
    title="Talos CleanRoom Portal",
    description="Unified landing page for Talos CleanRoom applications",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# Mount static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Mount user guide documentation (pre-built MkDocs site)
DOCS_DIR = APP_DIR.parent / "docs-site"
if DOCS_DIR.exists():
    app.mount("/docs", StaticFiles(directory=str(DOCS_DIR), html=True), name="docs")

# Setup templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Include routers
app.include_router(auth_router, prefix="/api/auth", tags=["Authentication"])
app.include_router(portal.router, prefix="/api/portal", tags=["Portal"])
app.include_router(credentials.router, prefix="/api/credentials", tags=["Credentials"])


# --- Page routes ---

@app.get("/")
async def index(request: Request, user: dict = Depends(get_current_user_optional)):
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    settings = get_settings()
    return templates.TemplateResponse("landing.html", {
        "request": request,
        "user": user,
        "page": "home",
        "deployment_console_url": settings.deployment_console_url,
        "scanning_console_url": settings.scanning_console_url,
    })


@app.get("/credentials")
async def credentials_page(request: Request, user: dict = Depends(get_current_user_optional)):
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse("credentials.html", {
        "request": request,
        "user": user,
        "page": "credentials",
    })


@app.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {
        "request": request,
        "app_subtitle": "Portal",
    })


# --- System endpoints ---

@app.get("/api/system/health")
async def health_check():
    return {"status": "healthy"}
