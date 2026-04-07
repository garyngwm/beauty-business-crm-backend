from typing import Optional

from pydantic import Field

from app.models._admin import BaseSchema

"""
    PUT
    1) /api/service-categories/:category_id?
"""


class ServiceCategoryUpsert(BaseSchema):
    title: str = Field(..., max_length=100)
    color: str = Field(..., max_length=100)  # Color name
    description: Optional[str] = None


"""
    GET
    1) /api/service-categories/:category_id
"""


class ServiceCategoryResponse(ServiceCategoryUpsert):
    id: int = Field(..., gt=0)


"""
    GET
    1) /api/service-categories
"""


class ServiceCategoryWithCountResponse(ServiceCategoryResponse):
    service_count: int = Field(..., ge=0)
