"""FastAPI application entry point for Talos CleanRoom Scanning Console."""

import asyncio
import logging
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
from app.routers import scan, ioc_scan, reports, export, enrichment, target_lab
from app.middleware.security import SecurityHeadersMiddleware
from app.middleware.rate_limit import RateLimitMiddleware

logger = logging.getLogger(__name__)

# Initialize talos_common with our settings getter
talos_common.init(get_settings)

# Application root directory
APP_DIR = Path(__file__).parent
STATIC_DIR = APP_DIR.parent / "static"
TEMPLATES_DIR = APP_DIR.parent / "templates"


async def _target_lab_cleanup_loop():
    """Background task: destroy expired VMs and reconcile orphaned deploys."""
    from app.services.target_lab_service import get_target_lab_service
    while True:
        try:
            await asyncio.sleep(300)  # Check every 5 minutes
            svc = get_target_lab_service()
            if svc.enabled:
                await svc.cleanup_expired()
                await svc.reconcile_orphaned()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning("Target Lab cleanup error: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage database connection pool, enrichment, and target lab lifecycle."""
    await init_db()
    # Reconcile any VMs orphaned from previous pod lifecycle
    try:
        from app.services.target_lab_service import get_target_lab_service
        svc = get_target_lab_service()
        if svc.enabled:
            await svc.reconcile_orphaned()
    except Exception as e:
        logger.warning("Target Lab startup reconciliation failed: %s", e)
    cleanup_task = asyncio.create_task(_target_lab_cleanup_loop())
    yield
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    # Shutdown target lab client
    try:
        from app.services.target_lab_service import get_target_lab_service
        await get_target_lab_service().close()
    except Exception:
        pass
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
app.include_router(enrichment.router, prefix="/api/enrichment", tags=["Enrichment"])
app.include_router(target_lab.router, prefix="/api/target-lab", tags=["Target Lab"])


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


@app.get("/target-lab")
async def target_lab_page(request: Request, user: dict = Depends(get_current_user_optional)):
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse("target_lab.html", {
        "request": request, "user": user, "page": "target_lab"
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
