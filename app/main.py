from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.storage import ensure_bucket
from app.modules.user_management.router import router as auth_router
from app.modules.document_storage.router import router as document_router
from app.modules.document_classification.router import router as classification_router
from app.modules.email_integration.router import router as email_router
from app.modules.shipment_identification.router import router as shipment_router
from app.modules.shipment_workspace.router import router as workspace_router
from app.modules.field_extraction.router import router as field_extraction_router
from app.modules.flags.router import router as flags_router
from app.modules.org_settings.router import router as org_settings_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_bucket()
    yield


app = FastAPI(
    title="BrokerAI API",
    description="Intelligent Customs Brokerage Document Platform",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_PREFIX = "/api/v1"

app.include_router(auth_router, prefix=API_PREFIX)
app.include_router(document_router, prefix=API_PREFIX)
app.include_router(classification_router, prefix=API_PREFIX)
app.include_router(email_router, prefix=API_PREFIX)
app.include_router(shipment_router, prefix=API_PREFIX)
app.include_router(workspace_router, prefix=API_PREFIX)
app.include_router(field_extraction_router, prefix=API_PREFIX)
app.include_router(flags_router, prefix=API_PREFIX)
app.include_router(org_settings_router, prefix=API_PREFIX)


@app.get("/health")
async def health():
    return {"status": "ok"}
