import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from supabase import AClient

from app.models.staff.shift import ShiftResponse, ShiftUpsert
from app.utils.appointment import _get_appointments_by_staff_and_date
from app.utils.blocked_time import _get_blocked_times_by_staff_and_date
from app.utils.time_off import _get_time_offs_by_staff_and_date
from db.supabase import get_supabase_client

logger = logging.getLogger(__name__)

shift_router = APIRouter(
    prefix="/api/shifts",
    tags=["shifts"],
)


""" 
    [Date format]
    1) Dates are expected to be in YYYY-MM-DD format
"""


@shift_router.get("/staff/{staff_id}/{date}", response_model=ShiftResponse)
async def get_shifts_by_staff_and_date(
    staff_id: int, date: str, supabase: AClient = Depends(get_supabase_client)
):
    try:
        shift = (
            await supabase.from_("shifts")
            .select("*")
            .eq("staff_id", staff_id)
            .eq("shift_date", date)
            .maybe_single()  # One or none
            .execute()
        )

        if not shift:
            raise HTTPException(status_code=404, detail="Staff shift not found")

        return shift.data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error fetching shift for staff {staff_id} over date {date}: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to get staff shift")


@shift_router.get("/outlet/{outlet_id}/{date}", response_model=List[ShiftResponse])
async def get_shifts_by_outlet_and_date(
    outlet_id: int, date: str, supabase: AClient = Depends(get_supabase_client)
):
    if outlet_id not in [1, 2]:  # TODO: Replace [1, 2] with your actual outlet IDs
        raise HTTPException(status_code=400, detail="Invalid outlet id")

    try:
        # First get staff IDs for the outlet
        staff_response = (
            await supabase.from_("staff_outlet")
            .select("staff_id")
            .eq("outlet_id", outlet_id)
            .execute()
        )
        staff_ids = [s["staff_id"] for s in staff_response.data]

        # Then get shifts for those staff on the date
        shifts = (
            await supabase.from_("shifts")
            .select("*")
            .in_("staff_id", staff_ids)
            .eq("shift_date", date)
            .execute()
        )

        return shifts.data

    except Exception as e:
        logger.error(
            f"Error fetching shifts for outlet {outlet_id} over date {date}: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to get outlet shifts")


# Create
@shift_router.put("", status_code=201)
async def create_shift(
    shift_data: ShiftUpsert, supabase: AClient = Depends(get_supabase_client)
):
    return await _upsert_shift(None, shift_data, supabase)


# Update
@shift_router.put("/{shift_id}")
async def update_shift(
    shift_id: int,
    shift_data: ShiftUpsert,
    supabase: AClient = Depends(get_supabase_client),
):
    return await _upsert_shift(shift_id, shift_data, supabase)


# Helper to handle both
async def _upsert_shift(
    shift_id: Optional[int], shift_data: ShiftUpsert, supabase: AClient
):
    # Construct payload
    payload = shift_data.model_dump(exclude_unset=True, by_alias=False)

    if shift_id is not None:
        payload["id"] = shift_id

    # Extract important info
    shift_date = shift_data.shift_date.isoformat()
    shift_staff_id = shift_data.staff_id

    shift_start_time = shift_data.start_time
    shift_end_time = shift_data.end_time

    try:
        # [CROSS CHECK 1]: Shift does not cause any staff appointments to fall out of range
        staff_appointments = await _get_appointments_by_staff_and_date(
            shift_staff_id, shift_date, supabase
        )

        is_all_within_range = all(
            datetime.fromisoformat(appt["start_time"]).time() >= shift_start_time
            and datetime.fromisoformat(appt["end_time"]).time() <= shift_end_time
            for appt in staff_appointments
        )

        if not is_all_within_range:
            raise HTTPException(
                status_code=400, detail="Existing appointments fall outside new hours"
            )

        # [CROSS CHECK 2]: Shift does not cause any staff time offs to fall out of range
        staff_time_offs = await _get_time_offs_by_staff_and_date(
            shift_staff_id, shift_date, supabase
        )

        is_all_within_range = all(
            time_off["start_time"] >= shift_start_time.strftime("%H:%M")
            and time_off["end_time"] <= shift_end_time.strftime("%H:%M")
            for time_off in staff_time_offs
        )

        if not is_all_within_range:
            raise HTTPException(
                status_code=400, detail="Existing time offs fall outside new hours"
            )

        # [CROSS CHECK 3]: Shift does not cause any staff blocked time to fall out of range
        staff_blocked_times = await _get_blocked_times_by_staff_and_date(
            shift_staff_id, shift_date, supabase
        )

        is_all_within_range = all(
            blocked_time["from_time"] >= shift_start_time.strftime("%H:%M")
            and blocked_time["to_time"] <= shift_end_time.strftime("%H:%M")
            for blocked_time in staff_blocked_times
        )

        if not is_all_within_range:
            raise HTTPException(
                status_code=400, detail="Existing blocked times fall outside new hours"
            )

        # After passing the cross checks
        # Then only do we perform the upsert
        payload["shift_date"] = payload["shift_date"].isoformat()
        response = await supabase.from_("shifts").upsert(payload).execute()

        if shift_id and not response.data:
            raise HTTPException(status_code=404, detail="Shift to be updated not found")

        return (
            "Shift successfully updated" if shift_id else "Shift successfully created"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error upserting shift: {str(e)}", exc_info=True)

        action = "update" if shift_id else "create"
        raise HTTPException(status_code=500, detail=f"Failed to {action} single shift")
