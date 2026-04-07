from datetime import datetime, timezone
import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from supabase import AClient

from app.models.members.members import MemberResponse
from db.supabase import get_supabase_client

logger = logging.getLogger(__name__)

members_router = APIRouter(
    prefix="/api/members",
    tags=["members"],
)

@members_router.get("", response_model=List[MemberResponse])
async def get_all_members(supabase: AClient = Depends(get_supabase_client)):
    try:
        response = await supabase.from_("members").select("*").execute()
        return response.data
    except Exception as e:
        logger.error(f"Error fetching members: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get all members")

@members_router.get("/{member_id}", response_model=MemberResponse)
async def get_member_by_id(
    member_id: int, supabase: AClient = Depends(get_supabase_client)
):
    try:
        response = (
            await supabase.from_("members").select("*").eq("id", member_id).execute()
        )
        if not response.data:
            raise HTTPException(status_code=404, detail="Member not found")
        return response.data[0]
    except Exception as e:
        logger.error(f"Error fetching member by id: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get member by id")

# Clearer path + correct param + dependency:
@members_router.get("/is_member/{customer_id}", response_model=bool)
async def is_member(
    customer_id: int,
    supabase: AClient = Depends(get_supabase_client),
) -> bool:
    now_iso = datetime.now(timezone.utc).isoformat()

    q = (
        supabase.table("members")
        .select("id")
        .eq("customer_id", customer_id)
        .is_("canceled_at", None)
        .gt("ends_at", now_iso)
        .limit(1)
    )
    res = await q.execute()
    return bool(res.data)
