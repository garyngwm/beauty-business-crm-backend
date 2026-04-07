import asyncio
import logging
from typing import Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from supabase import AClient

from decimal import Decimal, ROUND_HALF_UP
import dateutil.parser as dp

from app.models.appointment.appointment import (
    AppointmentSaleResponse,
    AppointmentResponse,
    AppointmentStatus,
    AppointmentUpsert,
)
from app.models.appointment.sales_performance import (
    SalesPerformancePoint,
    SalesPerformanceResponse,
)
from app.models.customer import CustomerResponse
from app.models.service.service import (
    ServiceWithoutLocationsResponse,
)
from app.routes.payment.payment import MarkAppointmentsPaidBody
from app.utils.appointment import (
    ChangeStaffSlotPayload,
    RescheduleSlotPayload,
    _get_appointments_by_outlet_and_date,
)
from app.utils.blocked_time import (
    HasOverlappingBlockedTimeArgs,
    _has_overlapping_blocked_times,
)
from app.utils.shift import IsWithinStaffShiftArgs, _is_within_staff_shift
from app.utils.time_off import HasOverlappingTimeOffsArgs, _has_overlapping_time_offs
from db.supabase import get_supabase_client

logger = logging.getLogger(__name__)

appointment_router = APIRouter(
    prefix="/api/appointments",
    tags=["appointments"],
)

STRIPE_FEE_RULES = {
    # Outlet 2
    1: {"percent": Decimal("0.029"), "fixed": Decimal("0.35")},
    # Outlet 1
    2: {"percent": Decimal("0.0317"), "fixed": Decimal("0.40")},
}

def calc_stripe_fee(outlet_id: int, sale_amount: float) -> float:

    amt = Decimal(str(sale_amount or 0))
    if amt <= 0:
        return 0.0

    rule = STRIPE_FEE_RULES.get(outlet_id)
    if not rule:
        return 0.0

    fee = (amt * rule["percent"]) + rule["fixed"]
    fee = fee.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(fee)

"""
    [FastAPI + Supbase Integration]

    1) I'll just write this once (@current maintainer)
    2) FastAPI, an async framework, requires supabase client as a dependency injection
    3) This prevents weird timeouts and disconnects

"""
@appointment_router.get("", response_model=List[AppointmentResponse])
async def get_appointments(
    customerId: Optional[int] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    supabase: AClient = Depends(get_supabase_client),
):
    try:
        q = (
            supabase.from_("appointments")
            .select("*")
            .order("start_time", desc=False)
            .range(offset, offset + limit - 1)
        )

        if customerId is not None:
            q = q.eq("customer_id", customerId)

        res = await q.execute()
        return res.data
    except Exception as e:
        logger.error(f"Error fetching appointments: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get appointments")


@appointment_router.get("/sales", response_model=List[AppointmentSaleResponse])
async def get_appointment_sales(
    supabase: AClient = Depends(get_supabase_client),
):
    try:
        appt_resp = (
            await supabase.from_("appointments")
            .select("*")
            .in_("payment_method", ["Cash", "Card"])
            .order("created_at", desc=True)
            .execute()
        )

        appointments = appt_resp.data or []
        if not appointments:
            return []

        customer_ids = {row["customer_id"] for row in appointments}
        outlet_ids = {row["outlet_id"] for row in appointments if row.get("outlet_id")}
        service_ids = {row["service_id"] for row in appointments if row.get("service_id")}
        customers_by_id: Dict[int, dict] = {}
        if customer_ids:
            cust_resp = (
                await supabase.from_("customers")
                .select("id, first_name, last_name")
                .in_("id", list(customer_ids))
                .execute()
            )
            for c in cust_resp.data or []:
                customers_by_id[c["id"]] = c

        outlets_by_id: Dict[int, dict] = {}
        if outlet_ids:
            outlet_resp = (
                await supabase.from_("outlets")
                .select("id, name")
                .in_("id", list(outlet_ids))
                .execute()
            )
            for o in outlet_resp.data or []:
                outlets_by_id[o["id"]] = o

        services_by_id: Dict[int, dict] = {}
        if service_ids:
            svc_resp = (
                await supabase.from_("services")
                .select("id, name")
                .in_("id", list(service_ids))
                .execute()
            )
            for s in svc_resp.data or []:
                services_by_id[s["id"]] = s

        service_outlet_gst: Dict[Tuple[int, int], float] = {}
        if service_ids and outlet_ids:
            so_resp = (
                await supabase.from_("service_outlet")
                .select("service_id, outlet_id, gst_percentage")
                .in_("service_id", list(service_ids))
                .in_("outlet_id", list(outlet_ids))
                .execute()
            )
            for so in so_resp.data or []:
                key = (so["service_id"], so["outlet_id"])
                service_outlet_gst[key] = float(so.get("gst_percentage") or 0)

        records: List[AppointmentSaleResponse] = []

        for row in appointments:
            customer = customers_by_id.get(row["customer_id"])
            outlet = outlets_by_id.get(row["outlet_id"]) if row.get("outlet_id") else None
            service = services_by_id.get(row["service_id"]) if row.get("service_id") else None

            customer_name = ""
            if customer:
                first = customer.get("first_name") or ""
                last = customer.get("last_name") or ""
                customer_name = f"{first} {last}".strip()

            outlet_name = outlet.get("name") if outlet else None
            service_name = service.get("name") if service else None

            cash_paid = float(row.get("cash_paid") or 0)
            payment_method = row.get("payment_method")
            outlet_id = row.get("outlet_id")
            stripe_fee = 0.0

            if payment_method == "Card":
                stripe_fee = calc_stripe_fee(outlet_id, cash_paid)

            gst_percent = 0.0
            if row.get("service_id") and row.get("outlet_id"):
                gst_percent = service_outlet_gst.get(
                    (row["service_id"], row["outlet_id"]),
                    0.0,
                )

            record = AppointmentSaleResponse(
                id=row["id"],
                customer_id=row["customer_id"],
                customerName=customer_name or None,
                service_id=row["service_id"],
                serviceName=service_name or None,
                outlet_id=row.get("outlet_id"),
                outletName=outlet_name,
                start_time=row["start_time"],
                created_at=row["created_at"],
                payment_method=payment_method,
                payment_status=row["payment_status"],
                credits_paid=row["credits_paid"],
                cash_paid=cash_paid,
                stripeFee=stripe_fee,
                gstPercent=gst_percent,
            )

            records.append(record)

        return records

    except Exception as e:
        logger.error(f"Error fetching sales records: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get appointment sales")

@appointment_router.get(
    "/appointment-sales-performance",
    response_model=SalesPerformanceResponse,
)
async def get_appointment_sales_performance(
    from_date: str = Query(..., alias="from"),
    to_date: str = Query(..., alias="to"),
    group_by: Literal["day", "month"] = Query("day", alias="groupBy"),
    date_field: Literal["start_time", "created_at"] = Query("start_time", alias="dateField"),
    outlet_id: int | None = Query(None, alias="outletId"),
    supabase: AClient = Depends(get_supabase_client),
):
    """
    - Only appointments with payment_status = "Paid"
    - Only payment_method in ["Cash", "Card"]
    - Group by day/month using start_time or created_at
    - Revenue returned is NET after Stripe fees (Card only)
    """
    try:
        from_ts = f"{from_date}T00:00:00"
        to_ts = f"{to_date}T23:59:59.999999"

        q = (
            supabase.from_("appointments")
            .select(f"id, cash_paid, {date_field}, payment_status, payment_method, outlet_id")
            .eq("payment_status", "Paid")
            .in_("payment_method", ["Cash", "Card"])
            .gte(date_field, from_ts)
            .lte(date_field, to_ts)
        )

        if outlet_id is not None:
            q = q.eq("outlet_id", outlet_id)

        res = await q.execute()
        rows = res.data or []

        buckets: Dict[str, Dict[str, float | int]] = {}
        total_revenue = 0.0
        total_count = 0

        for r in rows:
            cash_paid = float(r.get("cash_paid") or 0)
            if cash_paid <= 0:
                continue

            dt = r.get(date_field)
            if not dt:
                continue

            key = dt[:7] if group_by == "month" else dt[:10]

            if key not in buckets:
                buckets[key] = {"revenue": 0.0, "count": 0}

            payment_method = r.get("payment_method")
            stripe_fee = calc_stripe_fee(outlet_id, cash_paid) if payment_method == "Card" else 0.0
            net_revenue = cash_paid - stripe_fee

            buckets[key]["revenue"] = float(buckets[key]["revenue"]) + net_revenue
            buckets[key]["count"] = int(buckets[key]["count"]) + 1

            total_revenue += net_revenue
            total_count += 1

        points = [
            SalesPerformancePoint(
                date=k,
                revenue=round(float(v["revenue"]), 2),
                count=int(v["count"]),
            )
            for k, v in sorted(buckets.items())
        ]

        return SalesPerformanceResponse(
            groupBy=group_by,
            points=points,
            totalRevenue=round(total_revenue, 2),
            totalCount=total_count,
        )

    except Exception:
        logger.error("Failed to load appointment sales performance", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to load sales performance")
    
@appointment_router.get(
    "/outlet/{outlet_id}/{date}", response_model=List[AppointmentResponse]
)
async def get_appointments_by_outlet_and_date(
    outlet_id: int, date: str, supabase: AClient = Depends(get_supabase_client)
):
    if outlet_id not in [1, 2]:  # TODO: Replace [1, 2] with your actual outlet IDs
        raise HTTPException(status_code=400, detail="Invalid outlet id")

    try:
        appointments = await _get_appointments_by_outlet_and_date(
            outlet_id, date, supabase
        )
        return appointments

    except Exception as e:
        logger.error(f"Error fetching outlet appointments: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500, detail="Failed to get appointments for the outlet"
        )


@appointment_router.get("/{appointment_id}", response_model=AppointmentResponse)
async def get_single_appointment(
    appointment_id: int, supabase: AClient = Depends(get_supabase_client)
):
    try:
        appointment = (
            await supabase.from_("appointments")
            .select("*")
            .eq("id", appointment_id)
            .single()
            .execute()
        )

        if not appointment.data:
            raise HTTPException(status_code=404, detail="Appointment not found")

        return appointment.data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error fetching appointment {appointment_id}: {str(e)}", exc_info=True
        )
        raise HTTPException(status_code=500, detail="Failed to get appointment")

@appointment_router.put("/status/{appointment_id}")
async def update_appointment_status(
    appointment_id: int,
    status: AppointmentStatus,
    supabase: AClient = Depends(get_supabase_client),
):
    try:
        appt_resp = (
            await supabase.from_("appointments")
            .select("id, status, customer_id, outlet_id, payment_method, credits_paid")
            .eq("id", appointment_id)
            .single()
            .execute()
        )

        appt = appt_resp.data
        if not appt:
            raise HTTPException(status_code=404, detail="Appointment not found")

        old_status = appt["status"]
        new_status = status

        # Refund credits if transitioning to Cancelled
        if old_status != "Cancelled" and new_status == "Cancelled":
            await _refund_credits_if_needed(appt, supabase)

        upd_resp = (
            await supabase.from_("appointments")
            .update({"status": new_status})
            .eq("id", appointment_id)
            .execute()
        )

        if not upd_resp.data:
            raise HTTPException(status_code=404, detail="Appointment not found")

        return "Appointment status successfully updated"

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error updating appointment {appointment_id} status: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to update appointment status")


async def _refund_credits_if_needed(appt: dict, supabase: AClient):
    if appt.get("payment_method") != "Credits":
        return

    credits_paid = appt.get("credits_paid") or 0
    if credits_paid <= 0:
        return

    customer_id = appt["customer_id"]
    appointment_id = appt["id"]
    outlet_id = appt["outlet_id"]

    try:
        await (
            supabase.from_("credit_transactions")
            .insert({
                "customer_id": customer_id,
                "appointment_id": appointment_id,
                "outlet_id": outlet_id,
                "type": "refund",
                "amount": credits_paid,
                "description": "Refund for cancelled appointment",
            })
            .execute()
        )
    except Exception as e:
        # If unique violation => already refunded => do nothing
        msg = str(e).lower()
        if "duplicate" in msg or "unique" in msg or "uq_credit_refund_once" in msg:
            return
        raise

    cust_resp = (
        await supabase.from_("customers")
        .select("id, credit_balance")
        .eq("id", customer_id)
        .single()
        .execute()
    )
    cust = cust_resp.data
    if not cust:
        raise HTTPException(status_code=404, detail="Customer not found")

    new_balance = (cust.get("credit_balance") or 0) + credits_paid

    await (
        supabase.from_("customers")
        .update({"credit_balance": new_balance})
        .eq("id", customer_id)
        .execute()
    )

# Create
# @appointment_router.put("", status_code=201)
@appointment_router.post("", status_code=201)
async def create_appointment(
    appointment_data: AppointmentUpsert,
    supabase: AClient = Depends(get_supabase_client),
):
    return await _upsert_appointment(None, appointment_data, supabase)


# Update
@appointment_router.put("/{appointment_id:int}")
async def update_appointment(
    appointment_id: int,
    appointment_data: AppointmentUpsert,
    supabase: AClient = Depends(get_supabase_client),
):
    return await _upsert_appointment(appointment_id, appointment_data, supabase)


# Helper to handle both
async def _upsert_appointment(
    appointment_id: Optional[int],
    appointment_data: AppointmentUpsert,
    supabase: AClient,
):
    # Construct payload
    payload = appointment_data.model_dump(exclude_unset=True, by_alias=False)

    if appointment_id is not None:
        payload["id"] = appointment_id

    # Extract important info
    staff_id = appointment_data.staff_id

    staff_response = (
        await supabase.from_("staffs").select("*").eq("id", staff_id).single().execute()
    )

    staff = staff_response.data
    if not staff:
        raise HTTPException(status_code=404, detail="Staff not found")

    start_time = appointment_data.start_time
    end_time = appointment_data.end_time

    date_string = start_time.date().isoformat()  # YYYY-MM-DD
    is_weekday = 0 <= start_time.weekday() <= 4

    appointment_start_time = start_time.strftime("%H:%M")
    appointment_end_time = end_time.strftime("%H:%M")

    # Extra info for cross check 5
    customer_id = appointment_data.customer_id
    customer: CustomerResponse = (
        await supabase.from_("customers")
        .select("*")
        .eq("id", customer_id)
        .single()
        .execute()
    ).data

    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    try:
        # [CROSS CHECK 1]: Appointment falls within staff shift hours
        args = IsWithinStaffShiftArgs(
            staff_id=staff_id,
            staff=staff,
            date_string=date_string,
            target_start_time=appointment_start_time,
            target_end_time=appointment_end_time,
            is_weekday=is_weekday,
            type="Appointment",
        )
        await _is_within_staff_shift(args, supabase)

        # [CROSS CHECK 2]: Appointment does not clash with time-offs
        args = HasOverlappingTimeOffsArgs(
            staff_id=staff_id,
            staff=staff,
            date_string=date_string,
            target_start_time=appointment_start_time,
            target_end_time=appointment_end_time,
            type="Appointment",
        )
        await _has_overlapping_time_offs(args, supabase)

        # [CROSS CHECK 3]: Appointment does not clash with blocked-times
        args = HasOverlappingBlockedTimeArgs(
            staff_id=staff_id,
            staff=staff,
            date_string=date_string,
            target_start_time=appointment_start_time,
            target_end_time=appointment_end_time,
            type="Appointment",
        )
        await _has_overlapping_blocked_times(args, supabase)

        # --- At this point: all scheduling constraints passed ---

        # Normalize times for JSON
        payload["start_time"] = payload["start_time"].isoformat()
        payload["end_time"] = payload["end_time"].isoformat()

        payment_method = appointment_data.payment_method

        # ---------- PRE-CHECK for Credits on CREATE ----------
        if not appointment_id and payment_method == "Credits":
            service_id = appointment_data.service_id
            service: ServiceWithoutLocationsResponse = (
                await supabase.from_("services")
                .select("*")
                .eq("id", service_id)
                .single()
                .execute()
            ).data

            if not service:
                raise HTTPException(status_code=404, detail="Service not found")

            required_credits = service["credit_cost"]
            if customer["credit_balance"] < required_credits:
                # Fail BEFORE inserting any appointment row
                raise HTTPException(
                    status_code=400,
                    detail="Insufficient credits for new appointment",
                )

        # ---------- UPSERT ----------
        if not appointment_id:
            # Create new appointment (initialize credits_paid = 0)
            payload["credits_paid"] = 0
            response = await supabase.from_("appointments").insert(payload).execute()
        else:
            # Update existing appointment - don't include credits_paid field in payload
            payload.pop("credits_paid", None)
            response = (
                await supabase.from_("appointments")
                .update(payload)
                .eq("id", appointment_id)
                .execute()
            )

        if appointment_id and not response.data:
            raise HTTPException(
                status_code=404, detail="Appointment to be updated not found"
            )

        # For both create and update
        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=500, detail="Upsert returned no data")

        target_appointment_id = response.data[0]["id"]

        # ---------- HANDLE PAYMENT / CREDITS ----------
        if payment_method == "Credits":
            # Fetch service again (may be needed on update path or to get cost)
            service_id = appointment_data.service_id
            service: ServiceWithoutLocationsResponse = (
                await supabase.from_("services")
                .select("*")
                .eq("id", service_id)
                .single()
                .execute()
            ).data

            if not service:
                # Safety: if somehow service missing now, roll back if this was a create
                if not appointment_id:
                    await supabase.from_("appointments").delete().eq("id", target_appointment_id).execute()
                raise HTTPException(status_code=404, detail="Service not found")

            current_cost = service["credit_cost"]
            previous_credits_paid = response.data[0]["credits_paid"]  # 0 for create
            credit_diff = current_cost - previous_credits_paid

            # Need to charge more (covers CREATE where prev=0 and UPDATE where service changed)
            if credit_diff > 0:
                if customer["credit_balance"] < credit_diff:
                    # On CREATE, we already pre-checked, so this should only happen on UPDATE
                    # Roll back the fresh CREATE to avoid orphan row
                    if not appointment_id:
                        await supabase.from_("appointments").delete().eq("id", target_appointment_id).execute()

                    raise HTTPException(
                        status_code=400,
                        detail="Insufficient credits for updated appointment"
                        if appointment_id
                        else "Insufficient credits for new appointment",
                    )

                # Deduct credits
                new_balance = customer["credit_balance"] - credit_diff
                await (
                    supabase.from_("customers")
                    .update({"credit_balance": new_balance})
                    .eq("id", customer["id"])
                    .execute()
                )

                # Record deduction
                transaction_info = {
                    "customer_id": customer["id"],
                    "appointment_id": target_appointment_id,
                    "amount": credit_diff,
                    "type": "usage",
                    "description": f"Extra {credit_diff} credits used for updated appointment"
                    if appointment_id
                    else f"Used {current_cost} credits for new appointment",
                }
                await (
                    supabase.from_("credit_transactions")
                    .insert(transaction_info)
                    .execute()
                )

            # Refund surplus credits (ONLY possible on UPDATE where cost decreased)
            elif credit_diff < 0:
                refund_amount = abs(credit_diff)
                new_balance = customer["credit_balance"] + refund_amount

                # Perform refund
                await (
                    supabase.from_("customers")
                    .update({"credit_balance": new_balance})
                    .eq("id", customer["id"])
                    .execute()
                )

                # Record refund
                transaction_info = {
                    "customer_id": customer["id"],
                    "appointment_id": appointment_id,
                    "amount": refund_amount,  # Positive for credits added
                    "type": "refund",
                    "description": f"Refunded {refund_amount} credits after service change",
                }
                await (
                    supabase.from_("credit_transactions")
                    .insert(transaction_info)
                    .execute()
                )

            # Mark appointment as paid by credits
            await (
                supabase.from_("appointments")
                .update({"credits_paid": current_cost, "payment_status": "Paid"})
                .eq("id", target_appointment_id)
                .execute()
            )

        else:
            # Handle refund if switching from credits to cash/card (ONLY on UPDATE)
            if appointment_id:
                previous_credits_paid = response.data[0]["credits_paid"]
                if previous_credits_paid and previous_credits_paid > 0:
                    new_balance = customer["credit_balance"] + previous_credits_paid

                    # Perform refund
                    await (
                        supabase.from_("customers")
                        .update({"credit_balance": new_balance})
                        .eq("id", customer["id"])
                        .execute()
                    )

                    # Record refund
                    transaction_info = {
                        "customer_id": customer["id"],
                        "appointment_id": appointment_id,
                        "amount": previous_credits_paid,
                        "type": "refund",
                        "description": f"Refunded {previous_credits_paid} credits after switching to card/cash payment",
                    }
                    await (
                        supabase.from_("credit_transactions")
                        .insert(transaction_info)
                        .execute()
                    )

            # For non-credits, ensure appointment shows unpaid until settled
            await (
                supabase.from_("appointments")
                .update({"credits_paid": 0, "payment_status": "Pending"})
                .eq("id", target_appointment_id)
                .execute()
            )

        return (
            "Appointment successfully updated"
            if appointment_id
            else "Appointment successfully created"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error upserting appointment: {str(e)}", exc_info=True)

        action = "update" if appointment_id else "create"
        raise HTTPException(
            status_code=500, detail=f"Failed to {action} single appointment"
        )
@appointment_router.delete("/{appointment_id}")
async def delete_appointment(
    appointment_id: int, supabase: AClient = Depends(get_supabase_client)
):
    try:
        response = (
            await supabase.from_("appointments")
            .delete()
            .eq("id", appointment_id)
            .execute()
        )

        if not response.data:
            raise HTTPException(status_code=404, detail="Appointment not found")

        # If customer paid by credits
        # Refund the credits
        deleted_appointment: AppointmentResponse = response.data[0]

        payment_method = deleted_appointment["payment_method"]
        credits_paid = deleted_appointment["credits_paid"]

        customer_id = deleted_appointment["customer_id"]
        customer: CustomerResponse = (
            await supabase.from_("customers")
            .select("*")
            .eq("id", customer_id)
            .single()
            .execute()
        ).data

        if payment_method == "Credits" and credits_paid > 0:
            # Perform the refund
            new_credit_balance = customer["credit_balance"] + credits_paid

            await (
                supabase.from_("customers")
                .update({"credit_balance": new_credit_balance})
                .eq("id", customer_id)
                .execute()
            )

        return "Appointment successfully deleted"

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error deleting appointment {appointment_id}: {str(e)}", exc_info=True
        )
        raise HTTPException(
            status_code=500, detail="Failed to delete single appointment"
        )
    
# Appointment paid (Can be improved in future with webhooks) 
@appointment_router.post("/mark-appointments-paid")
async def mark_appointments_paid(
    body: MarkAppointmentsPaidBody,
    supabase: AClient = Depends(get_supabase_client),
):
    ids = list({int(x) for x in body.appointment_ids if x is not None})
    if not ids:
        raise HTTPException(status_code=400, detail="Empty appointment_ids")

    # Persist payment info
    payload = {
        "payment_status": "Paid",
        "status": "Show Up",
    }

    try:
        await (
            supabase.table("appointments")
            .update(payload)
            .in_("id", ids)
            .execute()
        )
        return {"ok": True, "updated": len(ids)}

    except Exception:
        logger.error("Failed to mark appointments paid", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update appointments")
    
@appointment_router.post("/reschedule-slot")
async def reschedule_slot(
    payload: RescheduleSlotPayload,
    supabase: AClient = Depends(get_supabase_client)
):
    ids = payload.appointmentIds

    response = (
        await supabase.from_("appointments")
        .select("*")
        .in_("id", ids)
        .order("start_time")
        .execute()
    )
    appts = response.data or []

    if not appts:
        raise HTTPException(status_code=404, detail="Appointments not found")

    # Reference appointment = earliest in slot
    ref = min(appts, key=lambda a: a["start_time"])

    ref_start = dp.parse(ref["start_time"])
    base_start = payload.newStartTime

    updates = []

    for appt in appts:
        old_start = dp.parse(appt["start_time"])
        old_end = dp.parse(appt["end_time"])

        duration = old_end - old_start
        offset = old_start - ref_start

        new_start = base_start + offset
        new_end = new_start + duration

        update_data = {
            "start_time": new_start.isoformat(),
            "end_time": new_end.isoformat(),
            "status": "Reschedule",
        }

        if payload.newStaffId is not None:
            update_data["staff_id"] = payload.newStaffId

        updates.append(
            supabase.from_("appointments")
            .update(update_data)
            .eq("id", appt["id"])
            .execute()
        )

    # Run all updates
    await asyncio.gather(*updates)

    return "Appointments rescheduled"

@appointment_router.put("/change-staff-slot")
async def change_staff_slot(
    payload: ChangeStaffSlotPayload,
    supabase: AClient = Depends(get_supabase_client),
):
    ids = list({int(x) for x in payload.appointmentIds if x is not None})
    if not ids:
        raise HTTPException(status_code=400, detail="Empty appointmentIds")

    new_staff_id = payload.newStaffId

    # Validate staff exists
    staff_resp = (
        await supabase.from_("staffs")
        .select("*")
        .eq("id", new_staff_id)
        .single()
        .execute()
    )
    staff = staff_resp.data
    if not staff:
        raise HTTPException(status_code=404, detail="Staff not found")

    # Fetch all appointments for the slot
    appt_resp = (
        await supabase.from_("appointments")
        .select("id, start_time, end_time, staff_id, customer_id, outlet_id")
        .in_("id", ids)
        .order("start_time")
        .execute()
    )
    appts = appt_resp.data or []
    if not appts:
        raise HTTPException(status_code=404, detail="Appointments not found")

    # Optional safety: ensure we really got all IDs requested
    found_ids = {a["id"] for a in appts}
    missing = [x for x in ids if x not in found_ids]
    if missing:
        raise HTTPException(status_code=404, detail=f"Missing appointments: {missing}")

    # 3) Run scheduling cross-checks for each appointment time range,
    #    but using the NEW staff
    for appt in appts:
        start_dt = dp.parse(appt["start_time"])
        end_dt = dp.parse(appt["end_time"])

        date_string = start_dt.date().isoformat()
        is_weekday = 0 <= start_dt.weekday() <= 4

        appointment_start_time = start_dt.strftime("%H:%M")
        appointment_end_time = end_dt.strftime("%H:%M")

        # check  within staff shift
        args = IsWithinStaffShiftArgs(
            staff_id=new_staff_id,
            staff=staff,
            date_string=date_string,
            target_start_time=appointment_start_time,
            target_end_time=appointment_end_time,
            is_weekday=is_weekday,
            type="Appointment",
        )
        await _is_within_staff_shift(args, supabase)

        # check no clash with time-offs
        args = HasOverlappingTimeOffsArgs(
            staff_id=new_staff_id,
            staff=staff,
            date_string=date_string,
            target_start_time=appointment_start_time,
            target_end_time=appointment_end_time,
            type="Appointment",
        )
        await _has_overlapping_time_offs(args, supabase)

        # check no clash with blocked-times
        args = HasOverlappingBlockedTimeArgs(
            staff_id=new_staff_id,
            staff=staff,
            date_string=date_string,
            target_start_time=appointment_start_time,
            target_end_time=appointment_end_time,
            type="Appointment",
        )
        await _has_overlapping_blocked_times(args, supabase)

    # Update all appointments to new staff
    updates = [
        supabase.from_("appointments")
        .update({"staff_id": new_staff_id})
        .eq("id", appt["id"])
        .execute()
        for appt in appts
    ]

    await asyncio.gather(*updates)

    return "Staff updated for slot"

