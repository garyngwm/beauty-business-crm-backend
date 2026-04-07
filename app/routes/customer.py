import logging
import re
from pydantic import BaseModel
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from supabase import AClient

from app.models.appointment.appointment import AppointmentResponse
from app.models.customer import CustomerResponse, CustomerUpsert
from db.supabase import get_supabase_client

logger = logging.getLogger(__name__)

customer_router = APIRouter(
    prefix="/api/customers",
    tags=["customers"],
)

class PaginatedCustomers(BaseModel):
    data: List[CustomerResponse]
    page: int
    limit: int
    total: int
    totalPages: int

@customer_router.get("", response_model=List[CustomerResponse])
async def get_all_customers(supabase: AClient = Depends(get_supabase_client)):
    try:
        customers = await supabase.from_("customers").select("*").execute()
        return customers.data
    except Exception as e:
        logger.error(f"Error fetching customers: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get all customers")
    
@customer_router.get("/list", response_model=PaginatedCustomers)
async def list_customers(
    page: int = Query(1, ge=1),
    limit: int = Query(200, ge=1, le=500),
    supabase: AClient = Depends(get_supabase_client),
):
    offset = (page - 1) * limit
    resp = await (
        supabase.from_("customers")
        .select("*", count="exact")
        .order("first_name", desc=False)
        .range(offset, offset + limit - 1)
        .execute()
    )

    return {
        "data": resp.data,
        "page": page,
        "limit": limit,
        "total": resp.count,
        "totalPages": (resp.count + limit - 1) // limit,
    }

@customer_router.get("/with-appointments", response_model=List[CustomerResponse])
async def get_customers_with_appointments(
    date: str = Query(..., description="YYYY-MM-DD"),
    supabase: AClient = Depends(get_supabase_client),
):
    try:
        start_of_day = f"{date}T00:00:00"
        end_of_day   = f"{date}T23:59:59"

        res = await (
            supabase
            .from_("customers")
            .select("*, appointments!inner(id)")
            .gte("appointments.start_time", start_of_day)
            .lte("appointments.start_time", end_of_day)
            .execute()
        )

        return res.data
    except Exception as e:
        logger.error(f"Error fetching customers with appointments: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Supabase query failed: {str(e)}")



def fuzzy_digit_like(digits: str) -> str:
    return "%" + "%".join(digits) + "%"

# Search over first name and last name
@customer_router.get("/search", response_model=List[CustomerResponse])
async def search_customers(
    search_query: str | None = None, supabase: AClient = Depends(get_supabase_client)
):
    try:
        q_raw = (search_query or "").strip()
        if not q_raw:
            return (await supabase.from_("customers").select("*").execute()).data

        # normalize query for phone search: keep only digits
        q_digits = re.sub(r"\D", "", q_raw)

        parts = [p for p in q_raw.split() if p]
        or_clauses: list[str] = []

        if len(parts) == 1:
            like = f"%{parts[0]}%"
            or_clauses += [
                f"first_name.ilike.{like}",
                f"last_name.ilike.{like}",
            ]
        else:
            first, last = parts[0], parts[-1]
            first_like, last_like = f"%{first}%", f"%{last}%"
            or_clauses += [
                f"and(first_name.ilike.{first_like},last_name.ilike.{last_like})",
                f"and(first_name.ilike.{last_like},last_name.ilike.{first_like})",
            ]

        if q_digits:
            or_clauses.append(f"phone.ilike.%{q_digits}%")                  # contiguous
            or_clauses.append(f"phone.ilike.{fuzzy_digit_like(q_digits)}")  # spaced/separated
            or_clauses.append(f"phone.ilike.%{q_raw}%")                     # original input

        customers = (
            await supabase
            .from_("customers")
            .select("*")
            .or_(",".join(or_clauses))
            .execute()
        )
        return customers.data

    except Exception as e:
        logger.error(
            f"Error searching customers over query '{search_query}': {str(e)}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to search for customers")


@customer_router.get("/{customer_id}", response_model=CustomerResponse)
async def get_customer(
    customer_id: int, supabase: AClient = Depends(get_supabase_client)
):
    try:
        target_customer = (
            await supabase.from_("customers")
            .select("*")
            .eq("id", customer_id)
            .maybe_single()
            .execute()
        )

        if not target_customer:
            raise HTTPException(status_code=404, detail="Customer not found")

        return target_customer.data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching customer {customer_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get single customer")


@customer_router.get(
    "/{customer_id}/appointments", response_model=List[AppointmentResponse]
)
async def get_customer_appointments(
    customer_id: int, supabase: AClient = Depends(get_supabase_client)
):
    try:
        target_customer = (
            await supabase.from_("customers")
            .select("*")
            .eq("id", customer_id)
            .single()
            .execute()
        )

        if not target_customer.data:
            raise HTTPException(status_code=404, detail="Customer not found")

        target_customer_appointments = (
            await supabase.from_("appointments")
            .select("*")
            .eq("customer_id", customer_id)
            .execute()
        )

        return target_customer_appointments.data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error fetching customer {customer_id} appointments: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail="Failed to fetch appointments for customer"
        )


# Create
@customer_router.put("", status_code=201)
async def create_customer(
    customer_data: CustomerUpsert, supabase: AClient = Depends(get_supabase_client)
):
    return await _upsert_customer(None, customer_data, supabase)


# Update
@customer_router.put("/{customer_id}")
async def update_customer(
    customer_id: int,
    customer_data: CustomerUpsert,
    supabase: AClient = Depends(get_supabase_client),
):
    return await _upsert_customer(customer_id, customer_data, supabase)


# Helper to handle both
async def _upsert_customer(
    customer_id: Optional[int], customer_data: CustomerUpsert, supabase: AClient
):
    # Construct payload
    payload = customer_data.model_dump(exclude_unset=True, by_alias=False)

    if customer_id is not None:
        payload["id"] = customer_id

    if payload.get("birthday"):
        payload["birthday"] = payload["birthday"].isoformat()

    try:
        response = await supabase.from_("customers").upsert(payload).execute()

        if customer_id and not response.data:
            raise HTTPException(
                status_code=404, detail="Customer to be updated not found"
            )

        return (
            "Customer successfully updated"
            if customer_id
            else "Customer successfully created"
        )

    except Exception as e:
        logger.error(f"Error upserting customer: {str(e)}", exc_info=True)

        action = "update" if customer_id else "create"
        raise HTTPException(
            status_code=500, detail=f"Failed to {action} single customer"
        )


@customer_router.delete("/{customer_id}")
async def delete_customer(
    customer_id: int, supabase: AClient = Depends(get_supabase_client)
):
    try:
        response = (
            await supabase.from_("customers").delete().eq("id", customer_id).execute()
        )

        if not response.data:
            raise HTTPException(status_code=404, detail="Customer not found")

        return "Customer successfully deleted"

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting customer {customer_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete single customer")
