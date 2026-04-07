import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from supabase import AClient

from app.models.staff.staff import (
    StaffUpsert,
    StaffWithLocationsResponse,
    StaffWithoutLocationsResponse,
)
from db.supabase import get_supabase_client

logger = logging.getLogger(__name__)

staff_router = APIRouter(
    prefix="/api/staffs",
    tags=["staffs"],
)


@staff_router.get("", response_model=List[StaffWithLocationsResponse])
async def get_all_staffs(supabase: AClient = Depends(get_supabase_client)):
    try:
        # LEFT JOIN with staff_outlet FK table
        # GROUP BY staff_id, then grab all the outlet_ids
        # Each row is annotated with "staff_outlet": [{"outlet_id": x}, ...]
        response = (
            await supabase.from_("staffs").select("*, staff_outlet(outlet_id)").execute()
        )

        # Process the response
        staffs = []
        for staff in response.data:
            # Remove the annotation, replace with locations
            staff["locations"] = [
                item["outlet_id"] for item in staff.pop("staff_outlet", [])
            ]
            staffs.append(staff)

        return staffs

    except Exception as e:
        logger.error(f"Error fetching staffs: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get all staffs")


@staff_router.get(
    "/outlet/{outlet_id}", response_model=List[StaffWithoutLocationsResponse]
)
async def get_all_staffs_from_outlet(
    outlet_id: int, supabase: AClient = Depends(get_supabase_client)
):
    if outlet_id not in [1, 2]:  # TODO: Replace [1, 2] with your actual outlet IDs
        raise HTTPException(status_code=400, detail="Invalid outlet id")

    try:
        response = (
            await supabase.from_("staff_outlet")
            .select("staff_id, staffs(*)")
            .eq("outlet_id", outlet_id)
            .execute()
        )

        # Extract staff data from the joined response
        staffs = [item["staffs"] for item in response.data]
        return staffs

    except Exception as e:
        logger.error(
            f"Error fetching staffs from outlet {outlet_id}: {str(e)}", exc_info=True
        )
        raise HTTPException(status_code=500, detail="Failed to get staffs from outlet")


@staff_router.get("/stats")
async def get_staff_stats(supabase: AClient = Depends(get_supabase_client)):
    try:
        response = await supabase.from_("staffs").select("active").execute()
        staff_statuses = response.data

        # Extract the active and inactive counts
        active_count = 0
        inactive_count = 0

        for staff_status in staff_statuses:
            status = staff_status["active"]
            if status:
                active_count += 1
            else:
                inactive_count += 1

        return {"active": active_count, "inactive": inactive_count}

    except Exception as e:
        logger.error(f"Error fetching staff statistics: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get staff statistics")


@staff_router.get("/{staff_id}", response_model=StaffWithLocationsResponse)
async def get_single_staff(staff_id: int, supabase: AClient = Depends(get_supabase_client)):
    try:
        response = (
            await supabase.from_("staffs")
            .select("*, staff_outlet(outlet_id)")
            .eq("id", staff_id)
            .single()
            .execute()
        )

        if not response.data:
            raise HTTPException(status_code=404, detail="Staff not found")

        # Process the response
        target_staff = response.data
        target_staff["locations"] = [
            item["outlet_id"] for item in target_staff.pop("staff_outlet", [])
        ]

        return target_staff

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching staff {staff_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get single staff")


# Create
@staff_router.put("", status_code=201)
async def create_staff(
    staff_data: StaffUpsert, supabase: AClient = Depends(get_supabase_client)
):
    return await _upsert_staff(None, staff_data, supabase)


# Update
@staff_router.put("/{staff_id}")
async def update_staff(
    staff_id: int,
    staff_data: StaffUpsert,
    supabase: AClient = Depends(get_supabase_client),
):
    return await _upsert_staff(staff_id, staff_data, supabase)


# Helper to handle both
async def _upsert_staff(staff_id: Optional[int], staff_data: StaffUpsert, supabase: AClient):
    # Construct payload
    payload = staff_data.model_dump(exclude_unset=True, by_alias=False)

    if staff_id is not None:
        payload["id"] = staff_id

    locations: List[int] = payload.pop("locations")

    try:
        response = await supabase.from_("staffs").upsert(payload).execute()

        if staff_id and not response.data:
            raise HTTPException(status_code=404, detail="Staff to be updated not found")

        # Clear existing links (if any)
        if staff_id is not None:
            await supabase.from_("staff_outlet").delete().eq("staff_id", staff_id).execute()

        # Update the staff-outlet link table
        target_staff = response.data[0]
        target_id: int = target_staff["id"]

        for outlet_id in locations:
            await supabase.from_("staff_outlet").insert(
                {"staff_id": target_id, "outlet_id": outlet_id}
            ).execute()

        return (
            "Staff successfully updated" if staff_id else "Staff successfully created"
        )

    except Exception as e:
        logger.error(f"Error upserting staff: {str(e)}", exc_info=True)

        action = "update" if staff_id else "create"
        raise HTTPException(status_code=500, detail=f"Failed to {action} single staff")


@staff_router.delete("/{staff_id}")
async def delete_staff(staff_id: int, supabase: AClient = Depends(get_supabase_client)):
    try:
        response = await supabase.from_("staffs").delete().eq("id", staff_id).execute()

        if not response.data:
            raise HTTPException(status_code=404, detail="Staff not found")

        return "Staff successfully deleted"

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting staff {staff_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete single staff")
