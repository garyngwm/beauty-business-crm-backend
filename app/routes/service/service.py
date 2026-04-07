import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from supabase import AClient

from app.models.service.service import (
    ServiceUpsert,
    ServiceWithLocationsResponse,
    ServiceWithoutLocationsResponse,
)
from db.supabase import get_supabase_client

logger = logging.getLogger(__name__)

service_router = APIRouter(
    prefix="/api/services",
    tags=["services"],
)


@service_router.get("", response_model=List[ServiceWithLocationsResponse])
async def get_all_services(supabase: AClient = Depends(get_supabase_client)):
    try:
        # LEFT JOIN with service_outlet FK table
        # GROUP BY service_id, then grab all the outlet_ids
        # Each row is annotated with "service_outlet": [{"outlet_id": x}, ...]
        response = (
            await supabase.from_("services")
            .select("*, service_outlet(outlet_id)")
            .execute()
        )

        # Process the response
        services = []
        for service in response.data:
            # Remove the annotation, replace with locations
            service["locations"] = [
                item["outlet_id"] for item in service.pop("service_outlet", [])
            ]
            services.append(service)

        return services

    except Exception as e:
        logger.error(f"Error fetching services: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get all services")


@service_router.get(
    "/outlet/{outlet_id}", response_model=List[ServiceWithoutLocationsResponse]
)
async def get_all_services_from_outlet(
    outlet_id: int, supabase: AClient = Depends(get_supabase_client)
):
    if outlet_id not in [1, 2]:  # TODO: Replace [1, 2] with your actual outlet IDs
        raise HTTPException(status_code=400, detail="Invalid outlet id")

    try:
        response = (
            await supabase.from_("service_outlet")
            .select("service_id, services(*)")
            .eq("outlet_id", outlet_id)
            .execute()
        )

        # Extract service data from the joined response
        services = [item["services"] for item in response.data]
        return services

    except Exception as e:
        logger.error(
            f"Error fetching services from outlet {outlet_id}: {str(e)}", exc_info=True
        )
        raise HTTPException(
            status_code=500, detail="Failed to get services from outlet"
        )


@service_router.get("/{service_id}", response_model=ServiceWithLocationsResponse)
async def get_single_service(
    service_id: int, supabase: AClient = Depends(get_supabase_client)
):
    try:
        response = (
            await supabase.from_("services")
            .select("*, service_outlet(outlet_id)")
            .eq("id", service_id)
            .single()
            .execute()
        )

        if not response.data:
            raise HTTPException(status_code=404, detail="Service not found")

        # Process the response
        target_service = response.data
        target_service["locations"] = [
            item["outlet_id"] for item in target_service.pop("service_outlet", [])
        ]

        return target_service

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching service {service_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get single service")


# Create
@service_router.put("", status_code=201)
async def create_service(
    service_data: ServiceUpsert, supabase: AClient = Depends(get_supabase_client)
):
    return await _upsert_service(None, service_data, supabase)


# Update
@service_router.put("/{service_id}")
async def update_service(
    service_id: int,
    service_data: ServiceUpsert,
    supabase: AClient = Depends(get_supabase_client),
):
    return await _upsert_service(service_id, service_data, supabase)

# Helper to handle both
async def _upsert_service(service_id: Optional[int], service_data: ServiceUpsert, supabase: AClient):
    payload = service_data.model_dump(exclude_unset=True, by_alias=False)

    if service_id is not None:
        payload["id"] = service_id

    locations: list[int] = payload.pop("locations", [])
    gst_outlet_ids: set[int] = set(payload.pop("gst_outlet_ids", []))

    gst_percent: float = float(payload.get("gst_percent", 0))

    try:
        response = await supabase.from_("services").upsert(payload).execute()

        if service_id and not response.data:
            raise HTTPException(status_code=404, detail="Service to be updated not found")

        target_service = response.data[0]
        target_id: int = target_service["id"]

        # Clear existing links (if any)
        await (
            supabase.from_("service_outlet")
            .delete()
            .eq("service_id", target_id)
            .execute()
        )

        # recreate links with gst_percentage
        rows = []
        for outlet_id in locations:
            rows.append({
                "service_id": target_id,
                "outlet_id": outlet_id,
                "gst_percentage": gst_percent if outlet_id in gst_outlet_ids else 0,
            })

        if rows:
            await supabase.from_("service_outlet").insert(rows).execute()

        return "Service successfully updated" if service_id else "Service successfully created"

    except Exception as e:
        logger.error(f"Error upserting service: {str(e)}", exc_info=True)
        ...

@service_router.delete("/{service_id}")
async def delete_service(
    service_id: int, supabase: AClient = Depends(get_supabase_client)
):
    try:
        response = (
            await supabase.from_("services").delete().eq("id", service_id).execute()
        )

        if not response.data:
            raise HTTPException(status_code=404, detail="Service not found")

        return "Service successfully deleted"

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting service {service_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete single service")
