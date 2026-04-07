from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import List, Literal, Optional

from dateutil.relativedelta import relativedelta
from fastapi import HTTPException
from pydantic import BaseModel
from supabase import AClient

from app.models.staff.blocked_time import BlockedTimeResponse, EndsType, FrequencyType
from app.models.staff.staff import StaffBase
from app.utils.general import has_overlap

""" 
    [Date format]
    1) Dates are expected to be in YYYY-MM-DD format
"""


async def _get_blocked_times_by_staff_and_date(
    staff_id: int, date: str, supabase: AClient
) -> List[BlockedTimeResponse]:
    all_blocked_times = (
        await supabase.from_("blocked_times")
        .select("*")
        .eq("staff_id", staff_id)
        .execute()
    ).data

    return _filter_by_frequency_and_ends_type(all_blocked_times, date)


async def _get_blocked_times_by_outlet_and_date(
    outlet_id: int, date: str, supabase: AClient
) -> List[BlockedTimeResponse]:
    # First, get staff IDs for the outlet
    staff_ids_response = (
        await supabase.from_("staff_outlet")
        .select("staff_id")
        .eq("outlet_id", outlet_id)
        .execute()
    ).data

    staff_ids = [item["staff_id"] for item in staff_ids_response]

    # Then, get blocked times for those staff
    all_blocked_times = (
        await supabase.from_("blocked_times")
        .select("*")
        .in_("staff_id", staff_ids)
        .execute()
    ).data

    return _filter_by_frequency_and_ends_type(all_blocked_times, date)


def _filter_by_frequency_and_ends_type(
    all_blocked_times: List[BlockedTimeResponse], date: str
):
    # Filter based on frequency and ends type
    valid_blocked_times = []
    target_date = datetime.fromisoformat(date).date()

    for bt in all_blocked_times:
        # Non-repeating blocked time
        if bt["frequency"] == "None":
            if bt["start_date"] == date:
                valid_blocked_times.append(bt)
            continue

        # Repeating blocked time
        start_date = datetime.fromisoformat(bt["start_date"]).date()

        if target_date < start_date:
            continue

        repeat_type: FrequencyType = bt["frequency"]
        ends_type: EndsType = bt["ends"]

        # Check based on end type
        if ends_type == "Never":
            if _is_date_in_infinite_range(target_date, start_date, repeat_type):
                valid_blocked_times.append(bt)

        elif ends_type == "On date":
            end_date = datetime.fromisoformat(bt["ends_on_date"]).date()

            if _is_date_in_range(target_date, start_date, end_date, repeat_type):
                valid_blocked_times.append(bt)

        elif ends_type == "After":
            occurrences = bt["ends_after_occurrences"]

            if _is_date_in_occurrence_range(
                target_date, start_date, repeat_type, occurrences
            ):
                valid_blocked_times.append(bt)

    return valid_blocked_times


def _is_date_in_infinite_range(
    target_date: date, start_date: date, repeat_type: FrequencyType
):
    if repeat_type == "Daily":
        return True

    elif repeat_type == "Weekly":
        return target_date.weekday() == start_date.weekday()

    else:
        # Monthly
        target_day = target_date.day
        start_day = start_date.day

        """
            [Edge case for months]
            1) Suppose the start day exceeds then number of days in the target day's month
            2) Then, the start day should match the last day of the target day's month!!
        """

        max_days = monthrange(target_date.year, target_date.month)[1]
        effective_day = min(start_day, max_days)

        return target_day == effective_day


def _is_date_in_range(
    target_date: date, start_date: date, end_date: date, repeat_type: FrequencyType
):
    if target_date < start_date or target_date > end_date:
        return False

    return _is_date_in_infinite_range(target_date, start_date, repeat_type)


def _is_date_in_occurrence_range(
    target_date: date, start_date: date, repeat_type: FrequencyType, occurrences: int
):
    if repeat_type == "Daily":
        end_date = start_date + timedelta(days=occurrences - 1)

    elif repeat_type == "Weekly":
        end_date = start_date + timedelta(weeks=occurrences - 1)

    else:
        # Monthly
        end_date = start_date + relativedelta(months=occurrences - 1)

    return _is_date_in_range(target_date, start_date, end_date, repeat_type)


CalendarForms = Literal["Appointment", "Blocked time", "Time off", "Shift"]


class HasOverlappingBlockedTimeArgs(BaseModel):
    # Only required when blocked time checking against itself
    blocked_time_id: Optional[int] = None
    staff_id: int
    staff: StaffBase
    date_string: str  # YYYY-MM-DD
    target_start_time: str  # HH:mm
    target_end_time: str  # HH:mm
    type: CalendarForms


async def _has_overlapping_blocked_times(
    args: HasOverlappingBlockedTimeArgs, supabase: AClient
) -> None:
    # Get blocked times for the staff on the given date
    blocked_times = await _get_blocked_times_by_staff_and_date(
        args.staff_id, args.date_string, supabase
    )

    # Filter out the current blocked time if blocked_time_id is provided
    staff_blocked_times = [
        blocked_time
        for blocked_time in blocked_times
        if not args.blocked_time_id or blocked_time["id"] != args.blocked_time_id
    ]

    # Check for overlaps
    has_overlapping = any(
        has_overlap(
            blocked_time["from_time"][:5],  # Cut away the seconds
            blocked_time["to_time"][:5],  # Cut away the seconds
            args.target_start_time,
            args.target_end_time,
        )
        for blocked_time in staff_blocked_times
    )

    if has_overlapping:
        raise HTTPException(
            status_code=400,
            detail=f"{args.type} {args.target_start_time}-{args.target_end_time} "
            f"by staff {args.staff.first_name} has clashing blocked times.",
        )
