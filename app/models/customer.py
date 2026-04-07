from datetime import date, datetime
from enum import Enum
from typing import List, Optional

from pydantic import EmailStr, Field

from app.models._admin import BaseSchema


class ReminderEnum(str, Enum):
    EMAIL_SMS = "Email + SMS"
    SMS_ONLY = "SMS only"
    EMAIL_ONLY = "Email only"


class MembershipStatusEnum(str, Enum):
    ACTIVE = "Active"
    INACTIVE = "Inactive"


"""
    PUT
    1) /api/customers/:customer_id? 
"""


class CustomerUpsert(BaseSchema):
    # The ... says that the field is required
    first_name: str = Field(..., max_length=100, alias="firstName")
    last_name: str = Field(..., max_length=100, alias="lastName")
    email: EmailStr = Field(..., max_length=255)
    phone: str = Field(..., max_length=20)
    birthday: Optional[date] = Field(None)
    credit_balance: int = Field(..., ge=0, alias="creditBalance")


"""
    GET
    1) /api/customers
    2) /api/customers/search
    3) /api/customers/:customer_id
"""


class CustomerResponse(CustomerUpsert):
    id: int = Field(..., gt=0)

    membership_type: Optional[str] = Field(None, max_length=50, alias="membershipType")
    membership_status: MembershipStatusEnum = Field(alias="membershipStatus")

    # Preferences
    preferred_therapist_id: Optional[int] = Field(
        None, alias="preferredTherapistId", gt=0
    )
    preferred_outlet_id: Optional[int] = Field(None, alias="preferredOutletId", gt=0)
    allergies: List[str]
    reminders: ReminderEnum

    credit_balance: int = Field(..., ge=0)
    created_at: datetime
