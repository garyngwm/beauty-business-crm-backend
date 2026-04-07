import os
import logging
from typing import Optional, List, Dict, Any
from dateutil import parser as dateparser
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from supabase import AClient
from postgrest import APIError  # <-- exceptions for DB errors
import stripe

from db.supabase import get_supabase_client

logger = logging.getLogger(__name__)

payments_router = APIRouter(
    prefix="/api/payments",
    tags=["payments"],
)

# Configure Stripe once at import time
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
CURRENCY = os.getenv("CURRENCY", "sgd")


# ---- Models ----
class CreatePaymentIntentBody(BaseModel):
    appointment_id: Optional[int] = None
    service_id: Optional[int] = None
    appointment_ids: Optional[List[int]] = None   # NEW

class CreatePaymentIntentResponse(BaseModel):
    clientSecret: str
    amount: float
    currency: str
    serviceName: str
    publishableKey: str

class MarkAppointmentsPaidBody(BaseModel):
    appointment_ids: List[int]

class CreateMembershipIntentBody(BaseModel):
    membership_plan_id: int
    customer_id: int

class CreateMembershipIntentResponse(BaseModel):
    clientSecret: str
    amount: float
    currency: str
    planTitle: str | None = None

# ---- Helpers ----
def _same_customer(appts: List[Dict[str, Any]]) -> bool:
    if not appts:
        return False
    c = appts[0].get("customer_id")
    return all(a.get("customer_id") == c for a in appts)

def _same_staff(appts: list[dict]) -> bool:
    if not appts:
        return False
    s = appts[0].get("staff_id")
    return all(a.get("staff_id") == s for a in appts)

def _same_outlet(appts: list[dict]) -> bool:
    if not appts:
        return False
    o = appts[0].get("outlet_id")
    return all(a.get("outlet_id") == o for a in appts)

def _overlap_same_hour(appts: List[Dict[str, Any]]) -> bool:
    if len(appts) <= 1:
        return True
    # Use the first appt's hour as the slot window
    first_start = dateparser.isoparse(appts[0]["start_time"])
    slot_start = first_start.replace(minute=0, second=0, microsecond=0)
    slot_end = slot_start.replace(hour=slot_start.hour + 1)
    for a in appts:
        a_start = dateparser.isoparse(a["start_time"])
        a_end = dateparser.isoparse(a["end_time"])
        if not (a_start < slot_end and a_end > slot_start):
            return False
    return True

def _to_minor_units(amount: float, currency: str) -> int:
    zero_decimal = currency.lower() in {"jpy", "krw"}
    return int(round(amount if zero_decimal else amount * 100))

async def _get_gateway_and_set_key(supabase: AClient, outlet_id: int):
    gw = (
        await supabase.table("outlet_gateways")
        .select("stripe_secret_key, stripe_publishable_key")
        .eq("outlet_id", outlet_id)
        .single()
        .execute()
    ).data
    if not gw or not gw.get("stripe_secret_key") or not gw.get("stripe_publishable_key"):
        raise HTTPException(400, "Outlet has no Stripe configuration")
    stripe.api_key = gw["stripe_secret_key"]
    return gw

# ---- Routes ----
@payments_router.post(
    "/create-payment-intent",
    response_model=CreatePaymentIntentResponse,
)
async def create_payment_intent(
    body: CreatePaymentIntentBody,
    supabase: AClient = Depends(get_supabase_client),
):
    if not stripe.api_key:
        logger.error("Stripe not configured: missing STRIPE_SECRET_KEY")
        raise HTTPException(status_code=500, detail="Stripe not configured")

    try:
        # ---------------------------
        # MULTI-APPOINTMENT
        # ---------------------------
        if body.appointment_ids and len(body.appointment_ids) > 0:
            ids = list({int(x) for x in body.appointment_ids if x is not None})
            if not ids:
                raise HTTPException(status_code=400, detail="Empty appointment_ids")

            # Fetch appointments including overridden price
            appt_resp = await (
                supabase.table("appointments")
                .select(
                    "id, customer_id, start_time, end_time, outlet_id, "
                    "service_id, staff_id, cash_paid"
                )
                .in_("id", ids)
                .execute()
            )
            appts = appt_resp.data or []
            if len(appts) != len(ids):
                raise HTTPException(status_code=400, detail="Some appointment_ids not found")

            if not _same_customer(appts):
                raise HTTPException(status_code=400, detail="Appointments must belong to the same customer")
            if not _same_staff(appts):
                raise HTTPException(status_code=400, detail="Appointments must belong to the same staff")
            if not _same_outlet(appts):
                raise HTTPException(status_code=400, detail="Appointments must belong to the same outlet")
            if not _overlap_same_hour(appts):
                raise HTTPException(status_code=400, detail="Appointments are not within the same slot/hour")

            service_ids = list({a["service_id"] for a in appts if a.get("service_id") is not None})
            if not service_ids:
                raise HTTPException(status_code=400, detail="Missing service_id(s) on appointments")
            
            outlet_id = int(appts[0]["outlet_id"])
            gw = await _get_gateway_and_set_key(supabase, outlet_id)

            svc_resp = await (
                supabase.table("services")
                .select("id, cash_price, name")
                .in_("id", service_ids)
                .execute()
            )
            svcs = svc_resp.data or []
            price_map = {int(s["id"]): float(s["cash_price"]) for s in svcs if s.get("cash_price") is not None}

            total = 0.0
            for a in appts:
                sid = a["service_id"]
                if sid not in price_map:
                    raise HTTPException(status_code=400, detail="Missing service for appointment")

                if a.get("cash_paid") is not None:
                    try:
                        p = float(a["cash_paid"])
                    except (TypeError, ValueError):
                        raise HTTPException(status_code=400, detail=f"Invalid cash_paid for appointment {a['id']}")
                else:
                    p = price_map[sid]

                if p <= 0:
                    raise HTTPException(status_code=400, detail=f"Invalid price for appointment {a['id']}")

                total += p

            first_dt = dateparser.isoparse(appts[0]["start_time"])
            display_name = f"{len(appts)} service(s) — {first_dt.strftime('%b %d, %Y')}"
            amount_cents = _to_minor_units(total, CURRENCY)

            metadata = {
                "mode": "multi_appointments",
                "appointment_ids": ",".join(str(i) for i in ids),
                "customer_id": str(appts[0]["customer_id"]),
                "count": str(len(appts)),
                "total_amount": str(total),
                "outlet_id": str(outlet_id),
            }

            pi = stripe.PaymentIntent.create(
                amount=amount_cents,
                currency=CURRENCY,
                automatic_payment_methods={"enabled": True},
                metadata=metadata,
            )

            return CreatePaymentIntentResponse(
                clientSecret=pi.client_secret,
                amount=total,
                currency=CURRENCY.upper(),
                serviceName=display_name,
                publishableKey=gw["stripe_publishable_key"],
            )

        # ---------------------------
        # SINGLE SERVICE
        # ---------------------------
        service_id = body.service_id
        cash_paid = None
        outlet_id: int | None = None

        # Try to resolve service_id and overridden price from appointment
        if not service_id and body.appointment_id:
            appt = (
                await supabase.table("appointments")
                .select("service_id, cash_paid, outlet_id")
                .eq("id", body.appointment_id)
                .single()
                .execute()
            ).data
            if not appt or appt.get("service_id") is None:
                raise HTTPException(status_code=400, detail="Invalid appointment_id")
            service_id = appt["service_id"]
            cash_paid = appt.get("cash_paid")
            outlet_id = int(appt["outlet_id"])

        if not service_id:
            raise HTTPException(status_code=400, detail="Missing service_id or appointment_id")

        svc_resp = await (
            supabase.table("services")
            .select("cash_price, name")
            .eq("id", service_id)
            .single()
            .execute()
        )
        svc = svc_resp.data
        if not svc or svc.get("cash_price") is None:
            raise HTTPException(status_code=400, detail="Invalid service_id")

        try:
            if cash_paid is not None:
                price = float(cash_paid)
            else:
                price = float(svc["cash_price"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid price type")

        if price <= 0:
            raise HTTPException(status_code=400, detail="Invalid service price")

        service_name = svc.get("name")
        amount_cents = _to_minor_units(price, CURRENCY)

        metadata = {"service_id": str(service_id), "outlet_id": str(outlet_id)}
        if body.appointment_id:
            metadata["appointment_id"] = str(body.appointment_id)

        pi = stripe.PaymentIntent.create(
            amount=amount_cents,
            currency=CURRENCY,
            automatic_payment_methods={"enabled": True},
            metadata=metadata,
        )

        return CreatePaymentIntentResponse(
            clientSecret=pi.client_secret,
            amount=price,
            currency=CURRENCY.upper(),
            serviceName=service_name or "Service",
            publishableKey=gw["stripe_publishable_key"],
        )
    
    except APIError as e:
        logger.error(f"Supabase APIError: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail="Failed to resolve service/appointment")

    except stripe.error.StripeError as e:
        logger.error(f"Stripe error creating PaymentIntent: {str(e)}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"Unexpected error creating PaymentIntent: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create PaymentIntent")

    
@payments_router.post(
    "/create-membership-intent",
    response_model=CreateMembershipIntentResponse,
)
async def create_membership_intent(
    body: CreateMembershipIntentBody,
    supabase: AClient = Depends(get_supabase_client),
):

    if not stripe.api_key:
        logger.error("Stripe not configured: missing STRIPE_SECRET_KEY")
        raise HTTPException(status_code=500, detail="Stripe not configured")

    try:
        # 1) Fetch membership plan (adjust table name/columns to your schema)
        #    Your frontend calls /api/membership and /api/membership/:id,
        #    so this likely maps to a "membership" table.
        plan_resp = await (
            supabase.table("membership")
            .select("id, title, amount, credits")
            .eq("id", body.membership_plan_id)
            .single()
            .execute()
        )
        plan = plan_resp.data
        if not plan:
            raise HTTPException(status_code=400, detail="Invalid membership plan")

        # 2) Parse/validate price
        raw_amount = plan.get("amount")
        try:
            price = float(raw_amount)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid membership amount type")

        if price <= 0:
            raise HTTPException(status_code=400, detail="Invalid membership amount")

        plan_title = plan.get("title") or "Membership"

        # 3) Create Stripe PaymentIntent
        amount_minor = _to_minor_units(price, CURRENCY)
        metadata = {
            "mode": "membership",
            "membership_plan_id": str(body.membership_plan_id),
            "customer_id": str(body.customer_id),
            # Optional: include credits for later fulfillment/debugging
            "credits": str(plan.get("credits") or ""),
        }

        pi = stripe.PaymentIntent.create(
            amount=amount_minor,
            currency=CURRENCY,  # e.g. "sgd"
            automatic_payment_methods={"enabled": True},
            metadata=metadata,
        )

        # 4) Return client secret + display info
        return CreateMembershipIntentResponse(
            clientSecret=pi.client_secret,
            amount=price,
            currency=CURRENCY.upper(),  # e.g. "SGD"
            planTitle=plan_title,
        )

    except APIError as e:
        logger.error(f"Supabase APIError (membership): {e}", exc_info=True)
        raise HTTPException(status_code=400, detail="Failed to resolve membership plan")

    except stripe.error.StripeError as e:
        logger.error(f"Stripe error creating membership PaymentIntent: {str(e)}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"Unexpected error (membership intent): {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create membership PaymentIntent")