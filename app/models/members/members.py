from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

class MemberUpsert(BaseModel):
    customer_id: int = Field(..., gt=0, alias="customer_id")
    membership_id: int = Field(..., gt=0, alias="membership_id")

    starts_at: datetime = Field(..., alias="starts_at")
    ends_at: datetime = Field(..., alias="ends_at")

    canceled_at: Optional[datetime] = Field(None, alias="canceled_at")
    notes: Optional[str] = Field(None, alias="notes")

class MemberResponse(MemberUpsert):
    id: int = Field(..., gt=0)
    created_at: datetime = Field(..., alias="created_at")