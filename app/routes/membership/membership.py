import logging
import os
import stripe
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from stripe import APIError
from supabase import AClient

from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta
from app.models.membership.membership import MembershipResponse
from db.supabase import get_supabase_client

# stripe.api_key = os.environ["STRIPE_SECRET_KEY"]

logger = logging.getLogger(__name__)

membership_router = APIRouter(
    prefix="/api/membership",
    tags=["membership"],
)

# Set to a valid appointment ID if your schema does not allow NULL on credit_transactions.appointment_id
# Set to None if your schema allows NULL
FALLBACK_APPOINTMENT_ID = None

class SubscribeBody(BaseModel):
    outlet_id: int
    customer_id: int
    membership_id: int
    success_url: str
    cancel_url: str
    
class FulfillMembershipBody(BaseModel):
    membership_plan_id: int
    customer_id: int
    payment_intent_id: Optional[str] = None  # useful for reconciliation

class FulfillMembershipResponse(BaseModel):
    ok: bool
    credit_transaction_id: Optional[int] = None
    new_credit_balance: Optional[float] = None

@membership_router.get("", response_model=List[MembershipResponse])
async def get_all_memberships(supabase: AClient = Depends(get_supabase_client)):
    try:
        response = await supabase.from_("membership").select("*").execute()
        return response.data
    except Exception as e:
        logger.error(f"Error fetching memberships: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get all memberships")

@membership_router.get("/{membership_id}", response_model=MembershipResponse)
async def get_membership_by_id(
    membership_id: int, supabase: AClient = Depends(get_supabase_client)
):
    try:
        response = (
            await supabase.from_("membership").select("*").eq("id", membership_id).execute()
        )
        if not response.data:
            raise HTTPException(status_code=404, detail="Membership not found")
        return response.data[0]
    except Exception as e:
        logger.error(f"Error fetching membership by id: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get membership by id")

@membership_router.post("/fulfill", response_model=FulfillMembershipResponse)
async def fulfill_membership(
    body: FulfillMembershipBody,
    supabase: AClient = Depends(get_supabase_client),
):
    try:
        plan_resp = await (
            supabase.table("membership")
            .select("id, title, amount, credits, duration")   # <-- add duration
            .eq("id", body.membership_plan_id)
            .single()
            .execute()
        )
        plan = plan_resp.data
        if not plan:
            raise HTTPException(status_code=400, detail="Invalid membership plan")
        
        try:
            plan_id = int(plan["id"])
        except (KeyError, TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid plan id")
        try:
            amount = float(plan.get("amount", 0))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid plan amount")
        if amount <= 0:
            raise HTTPException(status_code=400, detail="Plan amount must be > 0")

        try:
            credits = int(plan.get("credits", 0))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid plan credits")
        if credits <= 0:
            raise HTTPException(status_code=400, detail="Plan credits must be > 0")

        try:
            duration_months = int(plan.get("duration", 0))   # <-- read duration
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid plan duration")
        if duration_months <= 0:
            raise HTTPException(status_code=400, detail="Plan duration must be > 0")

        # Credit transaction
        appointment_id_to_use: Optional[int] = None
        if FALLBACK_APPOINTMENT_ID:
            try:
                appointment_id_to_use = int(FALLBACK_APPOINTMENT_ID)
            except ValueError:
                logger.warning("Invalid MEMBERSHIP_FALLBACK_APPOINTMENT_ID; ignoring.")
        if appointment_id_to_use is None:
            raise HTTPException(
                status_code=400,
                detail=("credit_transactions.appointment_id is NOT NULL, but no fallback was configured. "
                        "Set MEMBERSHIP_FALLBACK_APPOINTMENT_ID or make appointment_id nullable."),
            )

        insert_payload = {
            "customer_id": body.customer_id,
            "appointment_id": appointment_id_to_use,
            "amount": amount,
            "type": "purchase",
            "description": f"Purchased {credits} credits",
            "membership_id": plan_id,
        }
        ct_resp = await supabase.table("credit_transactions").insert(
            insert_payload, returning="representation"
        ).execute()

        credit_txn_id: Optional[int] = None
        if ct_resp.data:
            row = ct_resp.data[0] if isinstance(ct_resp.data, list) else ct_resp.data
            credit_txn_id = row.get("id")

        # Update credit balance
        cust_resp = await (
            supabase.table("customers")
            .select("id, credit_balance")
            .eq("id", body.customer_id)
            .single()
            .execute()
        )
        customer = cust_resp.data
        if not customer:
            raise HTTPException(status_code=400, detail="Customer not found")

        current_balance_raw = customer.get("credit_balance") or 0
        try:
            current_balance = int(current_balance_raw)
        except (TypeError, ValueError):
            current_balance = int(float(current_balance_raw))
        new_balance = current_balance + int(credits)

        # Compute membership window and insert into `members`
        now_utc = datetime.now(timezone.utc)

        # Find current active window (ends_at > now and not canceled)
        active_resp = await (
            supabase.table("members")
            .select("ends_at")
            .eq("customer_id", body.customer_id)
            .is_("canceled_at", None)
            .gt("ends_at", now_utc.isoformat())
            .order("ends_at", desc=True)
            .limit(1)
            .execute()
        )

        if active_resp.data:
            latest_ends_at_str = active_resp.data[0]["ends_at"]
            latest_ends_at = datetime.fromisoformat(latest_ends_at_str.replace("Z", "+00:00"))
            starts_at = latest_ends_at
        else:
            starts_at = now_utc

        ends_at = starts_at + relativedelta(months=duration_months)

        await supabase.table("members").insert(
            {
                "customer_id": int(body.customer_id),
                "membership_id": plan_id,
                "starts_at": starts_at.isoformat(),
                "ends_at": ends_at.isoformat(),
            }
        ).execute()

        # keep denormalized status for now; safe to remove later
        await (
            supabase.table("customers")
            .update({
                "credit_balance": new_balance,
                "membership_status": "Active",
                "membership_type": plan_id,
            })
            .eq("id", int(body.customer_id))
            .execute()
        )

        return FulfillMembershipResponse(
            ok=True,
            credit_transaction_id=credit_txn_id,
            new_credit_balance=new_balance,
        )

    except APIError as e:
        logger.error(f"Supabase APIError (fulfill): {e}", exc_info=True)
        raise HTTPException(status_code=400, detail="Database error while fulfilling membership")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error during membership fulfillment: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fulfill membership")
    
# Recurring payments
@membership_router.post("/subscribe")
async def subscribe(body: SubscribeBody, supabase: AClient = Depends(get_supabase_client)):
    # Load outlet gateway for the selected outlet
    gw = (
        await supabase.table("outlet_gateways")
        .select("stripe_secret_key")
        .eq("outlet_id", body.outlet_id)
        .single()
        .execute()
    ).data
    if not gw or not gw.get("stripe_secret_key"):
        raise HTTPException(400, "Outlet has no Stripe configuration")

    # Use THIS outlet's Stripe account
    stripe.api_key = gw["stripe_secret_key"]
    logger.debug("Stripe key loaded for outlet %s", body.outlet_id)

    # Resolve the Stripe price for (membership_id, outlet_id)
    mp = (
        await supabase.table("membership_prices")
        .select("stripe_price_id")
        .eq("membership_id", body.membership_id)
        .eq("outlet_id", body.outlet_id)
        .single()
        .execute()
    ).data
    if not mp or not mp.get("stripe_price_id"):
        raise HTTPException(400, "No Stripe price configured for this plan at this outlet")
    price_id = mp["stripe_price_id"]

    # Resolve (or create) the Stripe Customer
    cust_row = (
        await supabase.table("customers")
        .select("email, stripe_customer_id")
        .eq("id", body.customer_id)
        .single()
        .execute()
    ).data
    if not cust_row:
        raise HTTPException(400, "Customer not found")

    stripe_customer_id = cust_row.get("stripe_customer_id")
    if not stripe_customer_id:
        sc = stripe.Customer.create(email=cust_row["email"])
        stripe_customer_id = sc.id
        await (
            supabase.table("customers")
            .update({"stripe_customer_id": stripe_customer_id})
            .eq("id", body.customer_id)
            .execute()
        )

    # Create the Checkout Session for subscription in the outlet's Stripe account
    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            customer=stripe_customer_id,
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=body.success_url,
            cancel_url=body.cancel_url,
            subscription_data={
                "metadata": {
                    "outlet_id": str(body.outlet_id),
                    "membership_id": str(body.membership_id),
                    "customer_id": str(body.customer_id),
                }
            },
        )
    except stripe.error.StripeError as e:
        raise HTTPException(400, getattr(e, "user_message", str(e)))

    return {"checkout_url": session.url}