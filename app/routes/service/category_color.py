import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from supabase import AClient

from app.models.service.category_color import CategoryColorResponse
from db.supabase import get_supabase_client

logger = logging.getLogger(__name__)

category_color_router = APIRouter(
    prefix="/api/category-colors",
    tags=["category-colors"],
)


@category_color_router.get("", response_model=List[CategoryColorResponse])
async def get_all_category_colors(supabase: AClient = Depends(get_supabase_client)):
    try:
        category_colors = (
            await supabase.from_("service_categories_colors").select("*").execute()
        )
        return category_colors.data
    except Exception as e:
        logger.error(f"Error fetching category colors: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get all category colors")
