from typing import List, Literal, Optional, Annotated
from pydantic import BaseModel, Field
from datetime import datetime
from supabase import AClient

from app.models.appointment.appointment import AppointmentResponse

""" 
    [Date format]
    1) Dates are expected to be in YYYY-MM-DD format
"""

"""
    [Abstraction]
    1) Query builder with optional filters
    2) Ensure's that each query is constructed fresh

"""
class RescheduleSlotPayload(BaseModel):
    appointmentIds: Annotated[list[int], Field(min_length=1)]
    newStartTime: datetime
    newStaffId: Optional[int] = None

class ChangeStaffSlotPayload(BaseModel):
    appointmentIds: List[int] = Field(..., min_items=1)
    newStaffId: int

async def _get_appointments_by_date(
    supabase: AClient,
    date: str,
    staff_id: Optional[int] = None,
    customer_id: Optional[int] = None,
    outlet_id: Optional[int] = None,
) -> List[AppointmentResponse]:
    start_of_day = f"{date}T00:00:00"
    end_of_day = f"{date}T23:59:59"

    query = (
        supabase.from_("appointments")
        .select("*")
        .gte("start_time", start_of_day)
        .lte("start_time", end_of_day)
        .neq("status", "Cancelled")
    )

    # Apply filters based on what's provided
    if staff_id is not None:
        query = query.eq("staff_id", staff_id)
    if customer_id is not None:
        query = query.eq("customer_id", customer_id)
    if outlet_id is not None:
        query = query.eq("outlet_id", outlet_id)

    # Only await the execute() call
    result = await query.execute()
    return result.data


async def _get_appointments_by_staff_and_date(
    staff_id: int, date: str, supabase: AClient
) -> List[AppointmentResponse]:
    return await _get_appointments_by_date(supabase, date, staff_id=staff_id)


async def _get_appointments_by_customer_and_date(
    customer_id: int, date: str, supabase: AClient
) -> List[AppointmentResponse]:
    return await _get_appointments_by_date(supabase, date, customer_id=customer_id)


async def _get_appointments_by_outlet_and_date(
    outlet_id: int, date: str, supabase: AClient
) -> List[AppointmentResponse]:
    return await _get_appointments_by_date(supabase, date, outlet_id=outlet_id)


CalendarForms = Literal["Appointment", "Blocked time", "Time off", "Shift"]


# class HasOverlappingStaffAppointmentsArgs(BaseModel):
#     # Only required when appointment checking against itself
#     appointment_id: Optional[int] = None
#     staff_id: int
#     staff: StaffBase
#     date_string: str  # YYYY-MM-DD
#     target_start_time: str  # HH:mm
#     target_end_time: str  # HH:mm
#     type: CalendarForms


# async def _has_overlapping_staff_appointments(
#     args: HasOverlappingStaffAppointmentsArgs, supabase: AClient
# ) -> None:
#     # Get apointments for the staff on the given date
#     appointments = await _get_appointments_by_staff_and_date(
#         args.staff_id, args.date_string, supabase
#     )

#     # Filter out the current appointment if appointment_id is provided
#     staff_appointments = [
#         appt
#         for appt in appointments
#         if not args.appointment_id or appt["id"] != args.appointment_id
#     ]

#     # Check for overlaps
#     has_overlapping = any(
#         has_overlap(
#             datetime.fromisoformat(appt["start_time"]).strftime("%H:%M"),
#             datetime.fromisoformat(appt["end_time"]).strftime("%H:%M"),
#             args.target_start_time,
#             args.target_end_time,
#         )
#         for appt in staff_appointments
#     )

#     if has_overlapping:
#         raise HTTPException(
#             status_code=400,
#             detail=f"{args.type} {args.target_start_time}-{args.target_end_time} "
#             f"by staff {args.staff.first_name} has clashing appointments.",
#         )


# class HasOverlappingCustomerAppointmentsArgs(BaseModel):
#     # This is SOLELY USED by appointment to check against others
#     appointment_id: Optional[int]
#     customer_id: int
#     customer: CustomerResponse
#     date_string: str  # YYYY-MM-DD
#     target_start_time: str  # HH:mm
#     target_end_time: str  # HH:mm


# async def _has_overlapping_customer_appointments(
#     args: HasOverlappingCustomerAppointmentsArgs, supabase: AClient
# ) -> None:
#     # Get all appointments for the customer on the given date
#     appointments = await _get_appointments_by_customer_and_date(
#         args.customer_id, args.date_string, supabase
#     )

#     # Filter for customer appointments, excluding current appointment
#     customer_appointments = [
#         appt
#         for appt in appointments
#         if appt["customer_id"] == args.customer_id
#         and (not args.appointment_id or appt["id"] != args.appointment_id)
#     ]

#     # Check for overlaps
#     has_overlapping = any(
#         has_overlap(
#             datetime.fromisoformat(appt["start_time"]).strftime("%H:%M"),
#             datetime.fromisoformat(appt["end_time"]).strftime("%H:%M"),
#             args.target_start_time,
#             args.target_end_time,
#         )
#         for appt in customer_appointments
#     )

#     if has_overlapping:
#         raise HTTPException(
#             status_code=400,
#             detail=f"Appointment {args.target_start_time}-{args.target_end_time} "
#             f"by customer {args.customer.first_name} has clashing appointments.",
#         )
