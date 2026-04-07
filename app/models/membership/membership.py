from datetime import datetime
from typing import Optional

from pydantic import Field

from app.models._admin import BaseSchema

# ---------- Upsert (POST/PUT) ----------
class MembershipUpsert(BaseSchema):
    title: Optional[str] = Field(None, alias="title")
    subtitle: Optional[str] = Field(None, alias="subtitle")

    amount: int = Field(..., ge=0, alias="amount")

    # how many sessions/credits granted, non-negative
    credits: int = Field(..., ge=0, alias="credits")


# ---------- Read (GET) ----------
class MembershipResponse(MembershipUpsert):
    id: int = Field(..., gt=0)
    created_at: datetime
