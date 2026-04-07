from typing import List, Literal, Optional

from fastapi import HTTPException
from pydantic import BaseModel
from supabase import AClient

from app.models.staff.staff import StaffBase
from app.models.staff.time_off import TimeOffResponse
from app.utils.general import has_overlap

""" 
    [Date format]
    1) Dates are expected to be in YYYY-MM-DD format
"""


async def _get_time_offs_by_staff_and_date(
    staff_id: int, date: str, supabase: AClient
) -> List[TimeOffResponse]:
    all_time_offs = (
        await supabase.from_("time_offs").select("*").eq("staff_id", staff_id).execute()
    ).data

    return _filter_by_frequency(all_time_offs, date)


async def _get_time_offs_by_outlet_and_date(
    outlet_id: int, date: str, supabase: AClient
) -> List[TimeOffResponse]:
    # First, get staff IDs for the outlet
    staff_response = (
        await supabase.from_("staff_outlet")
        .select("staff_id")
        .eq("outlet_id", outlet_id)
        .execute()
    )
    staff_ids = [s["staff_id"] for s in staff_response.data]

    # Then, get time offs for those staff
    all_time_offs = (
        await supabase.from_("time_offs")
        .select("*")
        .in_("staff_id", staff_ids)
        .execute()
    ).data

    return _filter_by_frequency(all_time_offs, date)


def _filter_by_frequency(
    all_time_offs: List[TimeOffResponse], date: str
) -> List[TimeOffResponse]:
    # Filter based on frequency type
    valid_time_offs = []
    for time_off in all_time_offs:
        if time_off["frequency"] == "None":
            if time_off["start_date"] == date:
                valid_time_offs.append(time_off)
        else:
            # Repeat
            if time_off["start_date"] <= date <= time_off["ends_date"]:
                valid_time_offs.append(time_off)

    return valid_time_offs


CalendarForms = Literal["Appointment", "Blocked time", "Time off", "Shift"]


class HasOverlappingTimeOffsArgs(BaseModel):
    # Only required when time off checking against itself
    time_off_id: Optional[int] = None
    staff_id: int
    staff: StaffBase
    date_string: str  # YYYY-MM-DD
    target_start_time: str  # HH:mm
    target_end_time: str  # HH:mm
    type: CalendarForms


async def _has_overlapping_time_offs(
    args: HasOverlappingTimeOffsArgs, supabase: AClient
) -> None:
    # Get time offs for the staff on the given date
    time_offs = await _get_time_offs_by_staff_and_date(
        args.staff_id, args.date_string, supabase
    )

    # Filter out the current time off if time_off_id is provided
    staff_time_offs = [
        time_off
        for time_off in time_offs
        if not args.time_off_id or time_off["id"] != args.time_off_id
    ]

    # Check for overlaps
    has_overlapping = any(
        has_overlap(
            time_off["start_time"][:5],  # Cut away the seconds
            time_off["end_time"][:5],  # Cut away the seconds
            args.target_start_time,
            args.target_end_time,
        )
        for time_off in staff_time_offs
    )

    if has_overlapping:
        raise HTTPException(
            status_code=400,
            detail=f"{args.type} {args.target_start_time}-{args.target_end_time} "
            f"by staff {args.staff.first_name} has clashing time offs.",
        )
