from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import Field

from app.models._admin import BaseSchema


class AppointmentStatus(str, Enum):
    BOOKED = "Booked"
    CONFIRMED = "Confirmed"
    SHOW_UP = "Show Up"
    RESCHEDULE = "Reschedule"
    NO_SHOW = "No show"
    CANCELLED = "Cancelled"


class PaymentMethod(str, Enum):
    CREDITS = "Credits"
    CARD = "Card"
    CASH = "Cash"


class PaymentStatus(str, Enum):
    PENDING = "Pending"
    PAID = "Paid"
    FAILED = "Failed"
    REFUNDED = "Refunded"


"""
    PUT
    1) /api/appointments/:appointment_id?
"""


class AppointmentUpsert(BaseSchema):
    customer_id: int = Field(..., gt=0, alias="customerId")
    staff_id: int = Field(..., gt=0, alias="staffId")
    service_id: int = Field(..., gt=0, alias="serviceId")
    outlet_id: int = Field(..., gt=0, alias="outletId")

    start_time: datetime = Field(..., alias="startTime")
    end_time: datetime = Field(..., alias="endTime")

    payment_method: PaymentMethod = Field(..., alias="paymentMethod")
    payment_status: PaymentStatus = Field(..., alias="paymentStatus")

    # Payment fields
    credits_paid: int = Field(..., ge=0, alias="creditsPaid")
    cash_paid: int = Field(..., ge=0, alias="cashPaid")

    notes: Optional[str] = None
    status: AppointmentStatus


"""
    GET
    1) /api/appointments
    2) /api/appointments/:appointment_id
    3) /api/appointments/outlet/:outlet_id/:date
    4) /api/customers/:customer_id/appointments
"""


class AppointmentResponse(AppointmentUpsert):
    id: int = Field(..., gt=0)
    created_at: datetime

class AppointmentSaleResponse(BaseSchema):
    id: int = Field(..., gt=0)

    customer_id: int = Field(..., gt=0)
    customerName: str | None = Field(default=None)

    service_id: int = Field(..., gt=0)
    serviceName: str | None = Field(default=None)

    outlet_id: Optional[int] = Field(default=None)
    outletName: Optional[str] = Field(default=None)

    start_time: datetime
    created_at: datetime

    payment_method: PaymentMethod
    payment_status: PaymentStatus

    credits_paid: int
    cash_paid: float
    
    stripeFee: float = 0.0
    gst_percent: float = Field(0, alias="gstPercent")

