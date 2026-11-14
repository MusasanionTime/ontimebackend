from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.routes.admin import router as admin_router
from app.api.v1.routes.admin_audit import router as admin_audit_router
from app.api.v1.routes.admin_bigisub import router as admin_bigisub_router
from app.api.v1.routes.admin_changenow import router as admin_changenow_router
from app.api.v1.routes.admin_monnify import router as admin_monnify_router
from app.api.v1.routes.admin_platform_wallet import (
    router as admin_platform_wallet_router,
)
from app.api.v1.routes.admin_referral import router as admin_referral_router
from app.api.v1.routes.auth import router as auth_router
from app.api.v1.routes.bigisub import router as bigisub_router
from app.api.v1.routes.changenow import router as changenow_router
from app.api.v1.routes.login import router as login_router
from app.api.v1.routes.monnify import router as monnify_router
from app.api.v1.routes.monnify_deposits import router as monnify_deposits_router
from app.api.v1.routes.referral import router as referral_router
from app.api.v1.routes.topify import router as topify_router
from app.api.v1.routes.wallet import router as wallet_router
from app.core.config import settings

# =========================================================
# APPLICATION
# =========================================================

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.APP_VERSION,
    description="ONTIME SUBDATA LTD VTU, Digital Wallet and Reseller API",
)


# =========================================================
# CORS CONFIGURATION
# =========================================================

ALLOWED_ORIGINS = [
    # Local development
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    # Production frontend
    "https://ontimesub.com",
    "https://www.ontimesub.com",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
    max_age=600,
)


# =========================================================
# AUTHENTICATION
# =========================================================

app.include_router(auth_router, prefix="/api/v1")
app.include_router(login_router, prefix="/api/v1")


# =========================================================
# WALLET AND REFERRALS
# =========================================================

app.include_router(wallet_router, prefix="/api/v1")
app.include_router(referral_router, prefix="/api/v1")


# =========================================================
# MONNIFY
# =========================================================

app.include_router(monnify_router, prefix="/api/v1")
app.include_router(monnify_deposits_router, prefix="/api/v1")
app.include_router(topify_router, prefix="/api/v1")


# =========================================================
# CHANGENOW
# =========================================================

app.include_router(changenow_router, prefix="/api/v1")


# =========================================================
# BIGISUB
# =========================================================

app.include_router(bigisub_router, prefix="/api/v1")


# =========================================================
# ADMIN
# =========================================================

app.include_router(admin_router, prefix="/api/v1")
app.include_router(admin_platform_wallet_router, prefix="/api/v1")
app.include_router(admin_referral_router, prefix="/api/v1")

app.include_router(admin_monnify_router, prefix="/api/v1")
app.include_router(admin_changenow_router, prefix="/api/v1")
app.include_router(admin_bigisub_router, prefix="/api/v1")
app.include_router(admin_audit_router, prefix="/api/v1")


# =========================================================
# ROOT
# =========================================================


@app.get("/")
async def home():
    return {
        "project": settings.PROJECT_NAME,
        "version": settings.APP_VERSION,
        "status": "running",
    }


# =========================================================
# HEALTH
# =========================================================


@app.get("/health")
async def health():
    return {
        "status": "healthy",
    }
