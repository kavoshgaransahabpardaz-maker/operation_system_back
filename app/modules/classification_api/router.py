"""
HS Genie — per-product classification, verification, and field-editing endpoints.

Verify path  : calls the external text-classification API (path='verify').
               If the existing HS code is in the candidates the frontend auto-confirms it.
Genie path   : same API call (path='genie') — used when the product has no code yet.
Feedback     : proxies thumbs-up/down to the external API and persists the signal.
"""
import logging
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import get_current_user
from app.modules.classification_api.models import DocumentProduct, HsGenieRun
from app.modules.user_management.models import User

logger = logging.getLogger(__name__)

router = APIRouter(tags=["HS Genie"])

_GENIE_CLASSIFY_URL = "https://api.stage.veritariffai.co/api/v1/classification/classify/text"
_GENIE_FEEDBACK_URL = "https://api.stage.veritariffai.co/api/v1/classification/classifications/{record_id}/feedback"
_TIMEOUT = 60.0


# ── Pydantic I/O models ───────────────────────────────────────────────────────

class DocumentProductOut(BaseModel):
    id: str
    document_id: str
    shipment_id: str | None
    org_id: str
    product_name: str | None
    material: str | None
    intended_use: str | None
    description: str | None
    quantity: str | None
    unit_price: str | None
    line_total: str | None
    currency: str | None
    ship_from: str | None
    origin_country: str | None
    destination_country: str | None
    existing_hs_code: str | None
    existing_national_code: str | None
    existing_national_code_jurisdiction: str | None
    lot_number: str | None
    expiry_date: str | None
    net_weight: str | None
    gross_weight: str | None
    missing_required_fields: list | None
    is_ready_to_classify: bool
    hs_verified: bool
    hs_verified_at: str | None
    hs_verified_by: str | None
    active_genie_run_id: str | None
    created_at: str


def _product_to_out(p: DocumentProduct) -> DocumentProductOut:
    return DocumentProductOut(
        id=str(p.id),
        document_id=str(p.document_id),
        shipment_id=str(p.shipment_id) if p.shipment_id else None,
        org_id=str(p.org_id),
        product_name=p.product_name,
        material=p.material,
        intended_use=p.intended_use,
        description=p.description,
        quantity=p.quantity,
        unit_price=p.unit_price,
        line_total=p.line_total,
        currency=p.currency,
        ship_from=p.ship_from,
        origin_country=p.origin_country,
        destination_country=p.destination_country,
        existing_hs_code=p.existing_hs_code,
        existing_national_code=p.existing_national_code,
        existing_national_code_jurisdiction=p.existing_national_code_jurisdiction,
        lot_number=p.lot_number,
        expiry_date=p.expiry_date,
        net_weight=p.net_weight,
        gross_weight=p.gross_weight,
        missing_required_fields=p.missing_required_fields,
        is_ready_to_classify=p.is_ready_to_classify,
        hs_verified=p.hs_verified,
        hs_verified_at=p.hs_verified_at.isoformat() if p.hs_verified_at else None,
        hs_verified_by=str(p.hs_verified_by) if p.hs_verified_by else None,
        active_genie_run_id=str(p.active_genie_run_id) if p.active_genie_run_id else None,
        created_at=p.created_at.isoformat(),
    )


class ProductUpdateRequest(BaseModel):
    product_name: str | None = None
    material: str | None = None
    intended_use: str | None = None
    description: str | None = None
    quantity: str | None = None
    unit_price: str | None = None
    line_total: str | None = None
    currency: str | None = None
    ship_from: str | None = None
    origin_country: str | None = None
    destination_country: str | None = None
    existing_hs_code: str | None = None
    existing_national_code: str | None = None
    lot_number: str | None = None
    expiry_date: str | None = None
    net_weight: str | None = None
    gross_weight: str | None = None


class HsGenieRunOut(BaseModel):
    run_id: str
    path: str
    record_id: str | None
    input_text: str | None
    candidates: list | None
    chosen_code: str | None
    existing_hs_code: str | None
    feedback_signal: str | None


class HsSelectRequest(BaseModel):
    run_id: str
    code: str


class HsFeedbackRequest(BaseModel):
    run_id: str
    is_correct: bool
    correct_code: str | None = None
    reason: str | None = None


class HsGenieRunFull(BaseModel):
    run_id: str
    path: str
    record_id: str | None
    input_text: str | None
    candidates: list | None
    chosen_code: str | None
    feedback_signal: str | None
    corrected_code: str | None
    correction_reason: str | None
    created_at: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_text(p: DocumentProduct) -> str:
    parts: list[str] = []
    if p.product_name:
        parts.append(p.product_name)
    if p.description and p.description != p.product_name:
        parts.append(p.description)
    if p.material:
        parts.append(p.material)
    if p.intended_use:
        parts.append(f"intended use: {p.intended_use}")
    if p.origin_country and p.destination_country:
        parts.append(f"from {p.origin_country} to {p.destination_country}")
    elif p.destination_country:
        parts.append(f"to {p.destination_country}")
    return ", ".join(filter(None, parts))


async def _load_product(product_id: uuid.UUID, org_id: uuid.UUID, db: AsyncSession) -> DocumentProduct:
    res = await db.execute(
        select(DocumentProduct).where(
            DocumentProduct.id == product_id,
            DocumentProduct.org_id == org_id,
        )
    )
    p = res.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return p


async def _load_run(run_id: uuid.UUID, db: AsyncSession) -> HsGenieRun:
    res = await db.execute(select(HsGenieRun).where(HsGenieRun.id == run_id))
    run = res.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Genie run not found")
    return run


async def _call_classify_api(text: str) -> tuple[str | None, list]:
    """Call classify/text API and return (record_id, candidates)."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            _GENIE_CLASSIFY_URL,
            headers={"accept": "application/json"},
            data={"text": text},
        )
        resp.raise_for_status()
        api_data = resp.json()
    return api_data.get("record_id"), api_data.get("hs_codes") or []


# ── Product CRUD ──────────────────────────────────────────────────────────────

@router.get("/products/{product_id}", response_model=DocumentProductOut)
async def get_product(
    product_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Return a single product by ID."""
    p = await _load_product(product_id, current_user.org_id, db)
    return _product_to_out(p)


@router.patch("/products/{product_id}", response_model=DocumentProductOut)
async def update_product(
    product_id: uuid.UUID,
    body: ProductUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Partial update of editable product fields. Only provided fields are written."""
    p = await _load_product(product_id, current_user.org_id, db)

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(p, field, value)

    # Re-evaluate readiness
    required = ["product_name", "existing_hs_code", "origin_country", "destination_country"]
    p.is_ready_to_classify = all(getattr(p, f) for f in required)

    await db.commit()
    await db.refresh(p)
    return _product_to_out(p)


# ── HS classification ─────────────────────────────────────────────────────────

@router.post("/products/{product_id}/hs-verify", response_model=HsGenieRunOut)
async def hs_verify(
    product_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """
    PATH A — Verify: build description from product fields, call the external
    classify/text API, and return candidates.  The frontend auto-highlights
    the existing HS code when it appears in the candidate list, allowing the
    user to confirm with one click (thumbs-up) or override (thumbs-down + correction).
    """
    p = await _load_product(product_id, current_user.org_id, db)
    text = _build_text(p)
    if not text.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Product has no description to classify",
        )

    try:
        record_id, candidates = await _call_classify_api(text)
    except httpx.HTTPStatusError as e:
        logger.error("Classify API error %s: %s", e.response.status_code, e.response.text)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Classification API error")
    except Exception as e:
        logger.error("Classify API request failed: %s", e)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Classification API unavailable")

    existing_code = p.existing_hs_code
    run = HsGenieRun(
        product_id=product_id,
        org_id=current_user.org_id,
        path="verify",
        record_id=record_id,
        candidates=candidates,
        input_text=text,
        run_by=current_user.id,
    )
    db.add(run)
    await db.flush()
    p.active_genie_run_id = run.id
    await db.commit()

    return HsGenieRunOut(
        run_id=str(run.id),
        path="verify",
        record_id=record_id,
        input_text=text,
        candidates=candidates,
        chosen_code=None,
        existing_hs_code=existing_code,
        feedback_signal=None,
    )


@router.post("/products/{product_id}/hs-classify", response_model=HsGenieRunOut)
async def hs_classify(
    product_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """
    PATH B — Ask the HS Genie: build description from product fields, call
    the external classify/text API, and return candidates. Used when the
    product has no existing HS code or the user wants fresh suggestions.
    """
    p = await _load_product(product_id, current_user.org_id, db)
    text = _build_text(p)
    if not text.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Product has no description to classify",
        )

    try:
        record_id, candidates = await _call_classify_api(text)
    except httpx.HTTPStatusError as e:
        logger.error("Classify API error %s: %s", e.response.status_code, e.response.text)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Classification API error")
    except Exception as e:
        logger.error("Classify API request failed: %s", e)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Classification API unavailable")

    existing_code = p.existing_hs_code
    run = HsGenieRun(
        product_id=product_id,
        org_id=current_user.org_id,
        path="genie",
        record_id=record_id,
        candidates=candidates,
        input_text=text,
        run_by=current_user.id,
    )
    db.add(run)
    await db.flush()
    p.active_genie_run_id = run.id
    await db.commit()

    return HsGenieRunOut(
        run_id=str(run.id),
        path="genie",
        record_id=record_id,
        input_text=text,
        candidates=candidates,
        chosen_code=None,
        existing_hs_code=existing_code,
        feedback_signal=None,
    )


@router.post("/products/{product_id}/hs-select", response_model=HsGenieRunOut)
async def hs_select(
    product_id: uuid.UUID,
    body: HsSelectRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """User picks one of the candidates — updates product HS code and audit run."""
    p = await _load_product(product_id, current_user.org_id, db)
    run = await _load_run(uuid.UUID(body.run_id), db)

    now = datetime.now(timezone.utc)
    p.existing_hs_code = body.code
    p.hs_verified = True
    p.hs_verified_at = now
    p.hs_verified_by = current_user.id

    run.chosen_code = body.code
    run.chosen_at = now
    run.chosen_by = current_user.id

    await db.commit()

    return HsGenieRunOut(
        run_id=str(run.id),
        path=run.path,
        record_id=run.record_id,
        input_text=run.input_text,
        candidates=run.candidates,
        chosen_code=run.chosen_code,
        existing_hs_code=p.existing_hs_code,
        feedback_signal=run.feedback_signal,
    )


@router.post("/products/{product_id}/hs-feedback", response_model=HsGenieRunOut)
async def hs_feedback(
    product_id: uuid.UUID,
    body: HsFeedbackRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Submit thumbs-up/down feedback. Proxies to the external API when a
    record_id exists, and persists the signal + corrected code for training.

    is_correct=True  → call external API with is_correct: true
    is_correct=False → call external API with is_correct: false, correct_code, comment
    """
    p = await _load_product(product_id, current_user.org_id, db)
    run = await _load_run(uuid.UUID(body.run_id), db)

    now = datetime.now(timezone.utc)
    run.feedback_signal = "thumbs_up" if body.is_correct else "thumbs_down"
    run.corrected_code = body.correct_code if not body.is_correct else None
    run.correction_reason = body.reason if not body.is_correct else None
    run.feedback_at = now

    if run.record_id:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                await client.post(
                    _GENIE_FEEDBACK_URL.format(record_id=run.record_id),
                    headers={"Content-Type": "application/json"},
                    json={
                        "is_correct": body.is_correct,
                        "correct_code": body.correct_code,
                        "comment": body.reason,
                    },
                )
        except Exception as e:
            logger.warning("Could not proxy feedback to external API: %s", e)

    await db.commit()

    return HsGenieRunOut(
        run_id=str(run.id),
        path=run.path,
        record_id=run.record_id,
        input_text=run.input_text,
        candidates=run.candidates,
        chosen_code=run.chosen_code,
        existing_hs_code=p.existing_hs_code,
        feedback_signal=run.feedback_signal,
    )


@router.get("/products/{product_id}/hs-runs", response_model=list[HsGenieRunFull])
async def list_hs_runs(
    product_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Return full audit trail of all Genie runs and Verify actions for a product."""
    res = await db.execute(
        select(HsGenieRun)
        .where(HsGenieRun.product_id == product_id)
        .order_by(HsGenieRun.created_at.desc())
    )
    runs = list(res.scalars())
    return [
        HsGenieRunFull(
            run_id=str(r.id),
            path=r.path,
            record_id=r.record_id,
            input_text=r.input_text,
            candidates=r.candidates,
            chosen_code=r.chosen_code,
            feedback_signal=r.feedback_signal,
            corrected_code=r.corrected_code,
            correction_reason=r.correction_reason,
            created_at=r.created_at.isoformat(),
        )
        for r in runs
    ]
