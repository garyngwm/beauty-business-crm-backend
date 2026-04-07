from typing import Optional

from pydantic import Field

from app.models._admin import BaseSchema

"""
    Outlet IDs are auto-assigned by the database.
    Update your outlets via the Supabase dashboard or seed file.
"""


"""
    GET
    1) /api/outlets
"""


class OutletResponse(BaseSchema):
    id: int = Field(..., gt=0)
    name: str
    address: str
    phone: Optional[str] = None
    active: bool
