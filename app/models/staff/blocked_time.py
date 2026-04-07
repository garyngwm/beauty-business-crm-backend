from datetime import date, datetime, time
from enum import Enum
from typing import Optional

from pydantic import Field, field_serializer

from app.models._admin import BaseSchema


class FrequencyType(str, Enum):
    NONE = "None"
    DAILY = "Daily"
    WEEKLY = "Weekly"
    MONTHLY = "Monthly"


class EndsType(str, Enum):
    NEVER = "Never"
    ON_DATE = "On date"
    AFTER_OCCURRENCES = "After"


"""
    PUT
    1) /api/blocked-times/:blocked_time_id?
"""


class BlockedTimeUpsert(BaseSchema):
    staff_id: int = Field(..., gt=0, alias="staffId")

    title: str = Field(..., max_length=255)
    start_date: date = Field(..., alias="startDate")
    from_time: time = Field(..., alias="fromTime")
    to_time: time = Field(..., alias="toTime")

    frequency: FrequencyType
    ends: Optional[EndsType] = None
    ends_on_date: Optional[date] = Field(None, alias="endsOnDate")
    ends_after_occurrences: Optional[int] = Field(
        None, gt=0, alias="endsAfterOccurences"
    )

    description: Optional[str] = Field(None, max_length=255)
    approved: bool = False

    @field_serializer("from_time", "to_time")
    def serialize_time(self, v: time) -> str:
        return v.strftime("%H:%M")


"""
    GET
    1) /api/blocked-times/:blocked_time_id
    2) /api/blocked-times/outlet/:outlet_id/:date
"""


class BlockedTimeResponse(BlockedTimeUpsert):
    id: int = Field(..., gt=0)
    created_at: datetime
    updated_at: datetime | None
