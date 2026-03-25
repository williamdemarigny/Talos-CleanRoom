"""FastAPI application entry point for Talos CleanRoom Scanning Console."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from pathlib import Path

import talos_common
from talos_common.auth import get_current_user_optional
from talos_common.routers.auth import router as auth_router
from talos_common.routers.exchange import router as exchange_router

from app.config import get_settings
from app.db.engine import init_db, close_db
from app.routers import scan, ioc_scan, reports, export
from app.middleware.security import SecurityHeadersMiddleware
from app.middleware.rate_limit import RateLimitMiddleware

# Initialize talos_common with our settings getter
talos_common.init(get_settings)

# Application root directory
APP_DIR = Path(__file__).parent
STATIC_DIR = APP_DIR.parent / "static"
TEMPLATES_DIR = APP_DIR.parent / "templates"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage database connection pool and enrichment service lifecycle."""
    await init_db()
    yield
    # Shutdown enrichment service HTTP client
    try:
        from app.services.enrichment_service import get_enrichment_service
        await get_enrichment_service().close()
    except Exception:
        pass
    await close_db()


app = FastAPI(
    title="Talos CleanRoom Scanning Console",
    description="Security scanning, vulnerability management, and reporting",
    version="1.0.0",
    lifespan=lifespan,
)

# Security middleware
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://cleanroom.knowledgeondemand.net",  # Portal
        "https://10.83.3.190:8000",                  # Deployment Console (LXC)
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Setup templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Include routers
app.include_router(auth_router, prefix="/api/auth", tags=["Authentication"])
app.include_router(exchange_router, prefix="/api/auth", tags=["Authentication"])
app.include_router(scan.router, prefix="/api/scan", tags=["Scan"])
app.include_router(ioc_scan.router, prefix="/api/ioc-scan", tags=["IOC Scan"])
app.include_router(reports.router, prefix="/api/reports", tags=["Reports"])
app.include_router(export.router, prefix="/api/export", tags=["Export"])


# --- Page routes ---

@app.get("/")
async def index(request: Request, user: dict = Depends(get_current_user_optional)):
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return RedirectResponse(url="/scan", status_code=302)


@app.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {
        "request": request,
        "app_subtitle": "Scanning Console",
    })


@app.get("/scan")
async def scan_page(request: Request, user: dict = Depends(get_current_user_optional)):
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse("scan.html", {
        "request": request, "user": user, "page": "scan"
    })


@app.get("/ioc-scan")
async def ioc_scan_page(request: Request, user: dict = Depends(get_current_user_optional)):
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse("ioc_scan.html", {
        "request": request, "user": user, "page": "ioc_scan"
    })


@app.get("/reports")
async def reports_page(request: Request, user: dict = Depends(get_current_user_optional)):
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse("reports.html", {
        "request": request, "user": user, "page": "reports"
    })


@app.get("/reports/hosts")
async def reports_hosts_page(request: Request, user: dict = Depends(get_current_user_optional)):
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse("reports_hosts.html", {
        "request": request, "user": user, "page": "reports"
    })


@app.get("/reports/vulns")
async def reports_vulns_page(request: Request, user: dict = Depends(get_current_user_optional)):
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse("reports_vulns.html", {
        "request": request, "user": user, "page": "reports"
    })


@app.get("/reports/scan/{scan_id}")
async def reports_scan_detail_page(
    scan_id: str, request: Request,
    user: dict = Depends(get_current_user_optional),
):
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse("reports_scan_detail.html", {
        "request": request, "user": user, "page": "reports", "scan_id": scan_id
    })


@app.get("/reports/compare")
async def reports_compare_page(request: Request, user: dict = Depends(get_current_user_optional)):
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse("reports_compare.html", {
        "request": request, "user": user, "page": "reports"
    })


@app.get("/reports/audit")
async def reports_audit_page(request: Request, user: dict = Depends(get_current_user_optional)):
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse("reports_audit.html", {
        "request": request, "user": user, "page": "reports"
    })


# --- System endpoints ---

@app.get("/api/system/health")
async def health_check():
    return {"status": "healthy"}
