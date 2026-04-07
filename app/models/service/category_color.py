from pydantic import Field, field_validator

from app.models._admin import BaseSchema

""" 
    Currently hardcoded
    With sufficient variety and similar color palette to Fresha 

    GET 
    1) /api/category-colors
"""


class CategoryColorResponse(BaseSchema):
    id: int = Field(..., gt=0)
    name: str = Field(..., max_length=100)
    hex: str

    @field_validator("hex")
    @classmethod
    def validate_hex_format(cls, v: str) -> str:
        import re

        # Matches #RRGGBB or #RRGGBBAA
        if not re.match(r"^#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$", v):
            raise ValueError("Hex must be in format #RRGGBB or #RRGGBBAA")
        return v.upper()
