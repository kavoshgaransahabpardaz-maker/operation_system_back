import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.modules.flags.models import FlagSeverity, FlagStatus, FlagType, ResolutionDecision


class FlagOut(BaseModel):
    id: uuid.UUID
    shipment_id: uuid.UUID
    org_id: uuid.UUID | None
    flag_type: FlagType
    severity: FlagSeverity
    title: str
    description: str | None
    conflicting_values: list[Any] | None
    status: FlagStatus
    created_at: datetime
    resolved_at: datetime | None

    model_config = {"from_attributes": True}


class FlagResolveRequest(BaseModel):
    decision: ResolutionDecision
    chosen_value: str | None = None
    note: str | None = None
