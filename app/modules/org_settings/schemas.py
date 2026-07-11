import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class OrgSettingsOut(BaseModel):
    id: uuid.UUID | None = None
    org_id: uuid.UUID
    weight_qty_tolerance_pct: float
    value_tolerance_pct: float
    name_match_threshold: float
    doc_organization_by: str = "shipment"
    auto_fix_threshold: float = 0.95
    email_critical_alerts: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class OrgSettingsPatch(BaseModel):
    weight_qty_tolerance_pct: float | None = Field(None, ge=0.0, le=100.0)
    value_tolerance_pct: float | None = Field(None, ge=0.0, le=100.0)
    name_match_threshold: float | None = Field(None, ge=0.0, le=1.0)
    doc_organization_by: str | None = Field(None, pattern="^(shipment|client|lane|date)$")
    auto_fix_threshold: float | None = Field(None, ge=0.5, le=1.0)
    email_critical_alerts: bool | None = None
