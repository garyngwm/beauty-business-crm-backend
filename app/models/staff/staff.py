from typing import List, Literal

from pydantic import Field

from app.models._admin import BaseSchema


class StaffBase(BaseSchema):
    first_name: str = Field(..., alias="firstName")
    last_name: str = Field(..., alias="lastName")
    email: str
    phone: str
    role: str

    # Filter fields
    active: bool
    bookable: bool


"""
    PUT
    1) /api/staffs/:staff_id?
"""


class StaffUpsert(StaffBase):
    # Locations
    locations: List[Literal[1, 2]] = Field(..., min_length=1)  # outlet_id


"""
    GET
    1) /api/staffs
    2) /api/staffs/:staff_id
"""


class StaffWithLocationsResponse(StaffUpsert):
    id: int = Field(..., gt=0)


"""
    GET
    1) /api/staffs/outlet/:outlet_id
"""


class StaffWithoutLocationsResponse(StaffBase):
    id: int = Field(..., gt=0)
