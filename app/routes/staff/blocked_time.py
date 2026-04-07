import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from supabase import AClient

from app.models.staff.blocked_time import BlockedTimeResponse, BlockedTimeUpsert
from app.utils.blocked_time import (
    HasOverlappingBlockedTimeArgs,
    _get_blocked_times_by_outlet_and_date,
    _has_overlapping_blocked_times,
)
from app.utils.shift import IsWithinStaffShiftArgs, _is_within_staff_shift
from app.utils.time_off import HasOverlappingTimeOffsArgs, _has_overlapping_time_offs
from db.supabase import get_supabase_client

logger = logging.getLogger(__name__)

blocked_time_router = APIRouter(
    prefix="/api/blocked-times",
    tags=["blocked-times"],
)


@blocked_time_router.get(
    "/outlet/{outlet_id}/{date}", response_model=List[BlockedTimeResponse]
)
async def get_blocked_times_for_outlet_and_date(
    outlet_id: int, date: str, supabase: AClient = Depends(get_supabase_client)
):
    if outlet_id not in [1, 2]:  # TODO: Replace [1, 2] with your actual outlet IDs
        raise HTTPException(status_code=400, detail="Invalid outlet id")

    try:
        result = await _get_blocked_times_by_outlet_and_date(outlet_id, date, supabase)
        return result

    except Exception as e:
        logger.error(
            f"Error fetching blocked times for outlet {outlet_id} over date {date}: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail="Failed to get outlet blocked times"
        )


@blocked_time_router.get("/{blocked_time_id}", response_model=BlockedTimeResponse)
async def get_single_blocked_time(
    blocked_time_id: int, supabase: AClient = Depends(get_supabase_client)
):
    try:
        blocked_time = (
            await supabase.from_("blocked_times")
            .select("*")
            .eq("id", blocked_time_id)
            .single()
            .execute()
        )

        if not blocked_time.data:
            raise HTTPException(status_code=404, detail="Blocked time not found")

        return blocked_time.data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error fetching blocked time {blocked_time_id}: {str(e)}", exc_info=True
        )
        raise HTTPException(status_code=500, detail="Failed to get blocked time")


# Create
@blocked_time_router.put("", status_code=201)
async def create_blocked_time(
    blocked_time_data: BlockedTimeUpsert,
    supabase: AClient = Depends(get_supabase_client),
):
    return await _upsert_blocked_time(None, blocked_time_data, supabase)


# Update
@blocked_time_router.put("/{blocked_time_id}")
async def update_blocked_time(
    blocked_time_id: int,
    blocked_time_data: BlockedTimeUpsert,
    supabase: AClient = Depends(get_supabase_client),
):
    return await _upsert_blocked_time(blocked_time_id, blocked_time_data, supabase)


# Helper to handle both
async def _upsert_blocked_time(
    blocked_time_id: Optional[int],
    blocked_time_data: BlockedTimeUpsert,
    supabase: AClient,
):
    # Construct payload
    payload = blocked_time_data.model_dump(exclude_unset=True, by_alias=False)

    if blocked_time_id is not None:
        payload["id"] = blocked_time_id

    # Extract important info
    staff_id = blocked_time_data.staff_id

    staff_response = (
        await supabase.from_("staffs").select("*").eq("id", staff_id).single().execute()
    )

    staff = staff_response.data
    if not staff:
        raise HTTPException(status_code=404, detail="Staff not found")

    date_string = blocked_time_data.start_date.isoformat()  # YYYY-MM-DD

    blocked_time_start = datetime.combine(
        blocked_time_data.start_date, blocked_time_data.from_time
    )
    is_weekday = blocked_time_start.weekday() >= 0 and blocked_time_start.weekday() <= 4

    blocked_time_start_time = blocked_time_data.from_time.strftime("%H:%M")
    blocked_time_end_time = blocked_time_data.to_time.strftime("%H:%M")

    """ 
        [Cross check error handling]
        1) If cross check fails, it raises a HTTPException
        2) Hence, we just propogate the HTTPException back up 
    """

    try:
        # [CROSS CHECK 1]: Blocked time falls within staff shift hours
        args = IsWithinStaffShiftArgs(
            staff_id=staff_id,
            staff=staff,
            date_string=date_string,
            target_start_time=blocked_time_start_time,
            target_end_time=blocked_time_end_time,
            is_weekday=is_weekday,
            type="Blocked time",
        )

        await _is_within_staff_shift(args, supabase)

        # [CROSS CHECK 2]: Blocked time does not clash with other blocked times
        args = HasOverlappingBlockedTimeArgs(
            staff_id=staff_id,
            staff=staff,
            date_string=date_string,
            target_start_time=blocked_time_start_time,
            target_end_time=blocked_time_end_time,
            type="Blocked time",
            blocked_time_id=blocked_time_id,  # Exclude itself
        )

        await _has_overlapping_blocked_times(args, supabase)

        # [CROSS CHECK 3]: Blocked time does not clash with time offs
        args = HasOverlappingTimeOffsArgs(
            staff_id=staff_id,
            staff=staff,
            date_string=date_string,
            target_start_time=blocked_time_start_time,
            target_end_time=blocked_time_end_time,
            type="Blocked time",
        )

        await _has_overlapping_time_offs(args, supabase)

        # After passing the cross checks
        # Then only do we perform the upsert
        payload["start_date"] = payload["start_date"].isoformat()

        if payload.get("ends_on_date"):
            payload["ends_on_date"] = payload["ends_on_date"].isoformat()

        if blocked_time_id:
            payload["updated_at"] = datetime.now().isoformat()

        response = await supabase.from_("blocked_times").upsert(payload).execute()

        if blocked_time_id and not response.data:
            raise HTTPException(
                status_code=404, detail="Blocked time to be updated not found"
            )

        return (
            "Blocked time successfully updated"
            if blocked_time_id
            else "Blocked time successfully created"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error upserting blocked time: {str(e)}", exc_info=True)

        action = "update" if blocked_time_id else "create"
        raise HTTPException(
            status_code=500, detail=f"Failed to {action} single blocked time"
        )


@blocked_time_router.delete("/{blocked_time_id}")
async def delete_blocked_time(
    blocked_time_id: int, supabase: AClient = Depends(get_supabase_client)
):
    try:
        response = (
            await supabase.from_("blocked_times")
            .delete()
            .eq("id", blocked_time_id)
            .execute()
        )

        if not response.data:
            raise HTTPException(status_code=404, detail="Blocked time not found")

        return "Blocked time successfully deleted"

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error deleting blocked time {blocked_time_id}: {str(e)}", exc_info=True
        )
        raise HTTPException(
            status_code=500, detail="Failed to delete single blocked time"
        )
