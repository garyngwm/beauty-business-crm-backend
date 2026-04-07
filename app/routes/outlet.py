import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from supabase import AClient

from app.models.outlet import OutletResponse
from db.supabase import get_supabase_client

logger = logging.getLogger(__name__)

outlet_router = APIRouter(
    prefix="/api/outlets",
    tags=["outlets"],
)


@outlet_router.get("", response_model=List[OutletResponse])
async def get_all_outlets(supabase: AClient = Depends(get_supabase_client)):
    try:
        outlets = await supabase.from_("outlets").select("*").execute()
        return outlets.data
    except Exception as e:
        # Log the error server-side
        # Give client a generic response (unless its something actionable)
        logger.error(f"Error fetching outlets: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get all outlets")
