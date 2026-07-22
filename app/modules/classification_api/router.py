"""
HS Genie — per-product HS code classification and verification endpoints.

Verify path  : records user acceptance of the existing HS code, no external call.
Genie path   : calls the external text-classification API, stores full audit trail.
Feedback     : proxies 👍/👎 to the external API and persists the signal.
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

class HsGenieRunOut(BaseModel):
    run_id: str
    path: str
    record_id: str | None
    input_text: str | None
    candidates: list | None
    chosen_code: str | None
    feedback_signal: str | None

    model_config = {"from_attributes": True}


class HsSelectRequest(BaseModel):
    run_id: str
    code: str


class HsFeedbackRequest(BaseModel):
    run_id: str
    is_correct: bool
    correct_code: str | None = None
    reason: str | None = None   # "wrong_material"|"wrong_process"|"wrong_dimension"|"other"


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

    model_config = {"from_attributes": True}


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


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/products/{product_id}/hs-verify", response_model=HsGenieRunOut)
async def hs_verify(
    product_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """
    PATH A — Verify: user accepts the existing HS code on the line item.
    No external API call is made. Records a HsGenieRun(path='verify').
    """
    p = await _load_product(product_id, current_user.org_id, db)
    if not p.existing_hs_code:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No existing HS code to verify",
        )

    now = datetime.now(timezone.utc)
    p.hs_verified = True
    p.hs_verified_at = now
    p.hs_verified_by = current_user.id

    run = HsGenieRun(
        product_id=product_id,
        org_id=current_user.org_id,
        path="verify",
        chosen_code=p.existing_hs_code,
        chosen_at=now,
        chosen_by=current_user.id,
        run_by=current_user.id,
    )
    db.add(run)
    await db.flush()
    p.active_genie_run_id = run.id
    await db.commit()

    return HsGenieRunOut(
        run_id=str(run.id),
        path="verify",
        record_id=None,
        input_text=None,
        candidates=None,
        chosen_code=run.chosen_code,
        feedback_signal=None,
    )


@router.post("/products/{product_id}/hs-classify", response_model=HsGenieRunOut)
async def hs_classify(
    product_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """
    PATH B — Ask the HS Genie: calls the external text-classification API.
    Stores full candidate list for audit trail.
    """
    p = await _load_product(product_id, current_user.org_id, db)
    text = _build_text(p)
    if not text.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Product has no description to classify",
        )

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                _GENIE_CLASSIFY_URL,
                headers={"accept": "application/json"},
                data={"text": text},
            )
            resp.raise_for_status()
            api_data = resp.json()
    except httpx.HTTPStatusError as e:
        logger.error("HS Genie API error %s: %s", e.response.status_code, e.response.text)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Classification API error")
    except Exception as e:
        logger.error("HS Genie request failed: %s", e)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Classification API unavailable")

    candidates = api_data.get("hs_codes") or []
    record_id = api_data.get("record_id")

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
        feedback_signal=None,
    )


@router.post("/products/{product_id}/hs-select", response_model=HsGenieRunOut)
async def hs_select(
    product_id: uuid.UUID,
    body: HsSelectRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """User picks one of the Genie candidates — updates product HS code and audit run."""
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
    Submit 👍/👎 feedback. Proxies to the external API when a record_id exists,
    and persists the signal + corrected code for training data.
    """
    run = await _load_run(uuid.UUID(body.run_id), db)

    now = datetime.now(timezone.utc)
    run.feedback_signal = "thumbs_up" if body.is_correct else "thumbs_down"
    run.corrected_code = body.correct_code if not body.is_correct else None
    run.correction_reason = body.reason if not body.is_correct else None
    run.feedback_at = now

    # Proxy to external API when we have a record_id from a genie run
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
            # Non-fatal — local record is saved regardless
            logger.warning("Could not proxy feedback to external API: %s", e)

    await db.commit()

    return HsGenieRunOut(
        run_id=str(run.id),
        path=run.path,
        record_id=run.record_id,
        input_text=run.input_text,
        candidates=run.candidates,
        chosen_code=run.chosen_code,
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
