from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import Field

from app.models._admin import BaseSchema

class CreditTransactionType(str, Enum):
    USAGE = "usage"
    REFUND = "refund"
    PURCHASE = "purchase"
    STRIPE_RECURRING = "stripe_recurring"

class SalesRecordResponse(BaseSchema):
    id: int = Field(None, gt=0)
    customer_id: int = Field(..., gt=0, alias="customerId")
    customer_name: str = Field(..., alias="customerName")
    appointment_id: int = Field(None, gt=0, alias="appointmentId")
    outlet_id: Optional[int] = Field(None, alias="outletId")
    outlet_name: Optional[str] = Field(None, alias="outletName")
    amount: float
    type: CreditTransactionType
    description: Optional[str] = None
    created_at: datetime = Field(..., alias="createdAt")
    membershipTitle: Optional[str] = None
    stripe_status: Optional[str] = Field(None, alias="stripeStatus")
    stripe_invoice_id: Optional[str] = Field(None, alias="stripeInvoiceId")
    stripe_subscription_id: Optional[str] = Field(None, alias="stripeSubscriptionId")
    stripeFee: Optional[float] = None
    gstFee: Optional[float] = None
    

    
