import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from supabase import AClient

from app.models.staff.time_off import TimeOffResponse, TimeOffUpsert
from app.utils.blocked_time import (
    HasOverlappingBlockedTimeArgs,
    _has_overlapping_blocked_times,
)
from app.utils.shift import IsWithinStaffShiftArgs, _is_within_staff_shift
from app.utils.time_off import (
    HasOverlappingTimeOffsArgs,
    _get_time_offs_by_outlet_and_date,
    _has_overlapping_time_offs,
)
from db.supabase import get_supabase_client

logger = logging.getLogger(__name__)

time_off_router = APIRouter(
    prefix="/api/time-offs",
    tags=["time-offs"],
)


@time_off_router.get("/outlet/{outlet_id}/{date}", response_model=List[TimeOffResponse])
async def get_time_offs_for_outlet_and_date(
    outlet_id: int, date: str, supabase: AClient = Depends(get_supabase_client)
):
    if outlet_id not in [1, 2]:  # TODO: Replace [1, 2] with your actual outlet IDs
        raise HTTPException(status_code=400, detail="Invalid outlet id")

    try:
        result = await _get_time_offs_by_outlet_and_date(outlet_id, date, supabase)
        return result

    except Exception as e:
        logger.error(
            f"Error fetching time offs for outlet {outlet_id} over date {date}: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to get outlet time offs")


@time_off_router.get("/{time_off_id}", response_model=TimeOffResponse)
async def get_single_time_off(
    time_off_id: int, supabase: AClient = Depends(get_supabase_client)
):
    try:
        time_off = (
            await supabase.from_("time_offs")
            .select("*")
            .eq("id", time_off_id)
            .maybe_single()
            .execute()
        )

        if not time_off.data:
            raise HTTPException(status_code=404, detail="Time off not found")

        return time_off.data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching time off {time_off_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get time off")


# Create
@time_off_router.put("", status_code=201)
async def create_time_off(
    time_off_data: TimeOffUpsert, supabase: AClient = Depends(get_supabase_client)
):
    return await _upsert_time_off(None, time_off_data, supabase)


# Update
@time_off_router.put("/{time_off_id}")
async def update_time_off(
    time_off_id: int,
    time_off_data: TimeOffUpsert,
    supabase: AClient = Depends(get_supabase_client),
):
    return await _upsert_time_off(time_off_id, time_off_data, supabase)


# Helper to handle both
async def _upsert_time_off(
    time_off_id: Optional[int], time_off_data: TimeOffUpsert, supabase: AClient
):
    # Construct payload
    payload = time_off_data.model_dump(exclude_unset=True, by_alias=False)

    if time_off_id is not None:
        payload["id"] = time_off_id

    # Extract important info
    staff_id = time_off_data.staff_id

    staff_response = (
        await supabase.from_("staffs").select("*").eq("id", staff_id).single().execute()
    )

    staff = staff_response.data
    if not staff:
        raise HTTPException(status_code=404, detail="Staff not found")

    date_string = time_off_data.start_date.isoformat()  # YYYY-MM-DD

    time_off_start = datetime.combine(
        time_off_data.start_date, time_off_data.start_time
    )
    is_weekday = time_off_start.weekday() >= 0 and time_off_start.weekday() <= 4

    time_off_start_time = time_off_data.start_time.strftime("%H:%M")
    time_off_end_time = time_off_data.end_time.strftime("%H:%M")

    """ 
        [Cross check error handling]
        1) If cross check fails, it raises a HTTPException
        2) Hence, we just propogate the HTTPException back up 
    """

    try:
        # [CROSS CHECK 1]: Time off falls within staff shift hours
        args = IsWithinStaffShiftArgs(
            staff_id=staff_id,
            staff=staff,
            date_string=date_string,
            target_start_time=time_off_start_time,
            target_end_time=time_off_end_time,
            is_weekday=is_weekday,
            type="Time off",
        )

        await _is_within_staff_shift(args, supabase)

        # [CROSS CHECK 2]: Time off does not clash with blocked times
        args = HasOverlappingBlockedTimeArgs(
            staff_id=staff_id,
            staff=staff,
            date_string=date_string,
            target_start_time=time_off_start_time,
            target_end_time=time_off_end_time,
            type="Time off",
        )

        await _has_overlapping_blocked_times(args, supabase)

        # [CROSS CHECK 3]: Time off does not clash with other time offs
        args = HasOverlappingTimeOffsArgs(
            staff_id=staff_id,
            staff=staff,
            date_string=date_string,
            target_start_time=time_off_start_time,
            target_end_time=time_off_end_time,
            type="Time off",
            time_off_id=time_off_id,  # Exclude itself
        )

        await _has_overlapping_time_offs(args, supabase)

        # After passing the cross checks
        # Then only do we perform the upsert
        payload["start_date"] = payload["start_date"].isoformat()

        if payload.get("ends_date"):
            payload["ends_date"] = payload["ends_date"].isoformat()

        if time_off_id:
            payload["updated_at"] = datetime.now().isoformat()

        response = await supabase.from_("time_offs").upsert(payload).execute()

        if time_off_id and not response.data:
            raise HTTPException(
                status_code=404, detail="Time off to be updated not found"
            )

        return (
            "Time off successfully updated"
            if time_off_id
            else "Time off successfully created"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error upserting time off: {str(e)}", exc_info=True)

        action = "update" if time_off_id else "create"
        raise HTTPException(
            status_code=500, detail=f"Failed to {action} single time off"
        )


@time_off_router.delete("/{time_off_id}")
async def delete_time_off(
    time_off_id: int, supabase: AClient = Depends(get_supabase_client)
):
    try:
        response = (
            await supabase.from_("time_offs").delete().eq("id", time_off_id).execute()
        )

        if not response.data:
            raise HTTPException(status_code=404, detail="Time off not found")

        return "Time off successfully deleted"

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting time off {time_off_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete single time off")
