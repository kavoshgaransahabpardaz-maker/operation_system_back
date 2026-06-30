import uuid
from datetime import datetime

from pydantic import BaseModel

from app.modules.shipment_identification.models import ReferenceType, ShipmentStatus


class ShipmentReferenceOut(BaseModel):
    id: uuid.UUID
    ref_type: ReferenceType
    ref_value: str

    model_config = {"from_attributes": True}


class ShipmentOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    status: ShipmentStatus
    created_at: datetime
    updated_at: datetime
    references: list[ShipmentReferenceOut] = []

    model_config = {"from_attributes": True}


class ReassociateRequest(BaseModel):
    shipment_id: uuid.UUID


class ShipmentUpdate(BaseModel):
    status: ShipmentStatus
