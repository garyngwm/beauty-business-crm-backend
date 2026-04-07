# app/routes/stripe_webhook/stripe_webhook.py

import asyncio
import logging
import stripe
from datetime import datetime, timezone
from fastapi import APIRouter, Request, HTTPException, Depends
from supabase import AClient
from db.supabase import get_supabase_client

logger = logging.getLogger(__name__)
webhook_router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

FALLBACK_APPOINTMENT_ID = None  # Set to a valid appointment ID if your schema does not allow NULL

def _ts(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc)


async def _get_all_webhook_secrets(supabase: AClient) -> list[str]:
    res = await (
        supabase.table("outlet_gateways")
        .select("stripe_webhook_secret")
        .execute()
    )
    rows = res.data or []
    return [r["stripe_webhook_secret"] for r in rows if r.get("stripe_webhook_secret")]

def _verify_with_any_secret(payload: bytes, sig_header: str, secrets: list[str]):
    last_err = None
    for s in secrets:
        try:
            return stripe.Webhook.construct_event(payload, sig_header, s), s
        except stripe.error.SignatureVerificationError as e:
            last_err = e
            continue
    raise last_err or stripe.error.SignatureVerificationError("No matching secret", sig_header, None)


def _first_price_id(invoice_obj: dict) -> str | None:
    try:
        return invoice_obj["lines"]["data"][0]["price"]["id"]
    except Exception:
        return None


async def _resolve_membership_price(
    supabase: AClient,
    *,
    price_id: str,
) -> tuple[int | None, int | None]:
    """
    Given a stripe_price_id, resolve (outlet_id, membership_id).
    """
    mp = (
        await supabase.table("membership_prices")
        .select("outlet_id, membership_id")
        .eq("stripe_price_id", price_id)
        .single()
        .execute()
    ).data
    if not mp:
        return None, None
    return int(mp["outlet_id"]), int(mp["membership_id"])


async def _get_membership_credits(supabase: AClient, membership_id: int) -> int:
    plan = (
        await supabase.table("membership")
        .select("credits")
        .eq("id", membership_id)
        .single()
        .execute()
    ).data
    return int(plan["credits"]) if plan and plan.get("credits") is not None else 0


async def _get_customer_by_stripe_id(supabase: AClient, stripe_customer_id: str) -> dict | None:
    return (
        await supabase.table("customers")
        .select("id, credit_balance")
        .eq("stripe_customer_id", stripe_customer_id)
        .single()
        .execute()
    ).data


async def _upsert_credit_transaction(
    supabase: AClient,
    payload_tx: dict,
):
    """
    Requires: credit_transactions has stripe_invoice_id column and a unique constraint/index on it.
    """
    await (
        supabase.table("credit_transactions")
        .upsert(payload_tx, on_conflict="stripe_invoice_id")
        .execute()
    )


async def _insert_membership_period_and_credit(
    supabase: AClient,
    *,
    customer_id: int,
    outlet_id: int,
    membership_id: int,
    credits: int,
    period_start_unix: int,
    period_end_unix: int,
):
    starts_at = _ts(period_start_unix).isoformat()
    ends_at = _ts(period_end_unix).isoformat()

    await supabase.table("members").insert(
        {
            "customer_id": customer_id,
            "membership_id": membership_id,
            "outlet_id": outlet_id,
            "starts_at": starts_at,
            "ends_at": ends_at,
        }
    ).execute()

    cust = (
        await supabase.table("customers")
        .select("credit_balance")
        .eq("id", customer_id)
        .single()
        .execute()
    ).data
    current_bal = int(cust.get("credit_balance") or 0) if cust else 0
    new_bal = current_bal + credits

    await (
        supabase.table("customers")
        .update({"credit_balance": new_bal})
        .eq("id", customer_id)
        .execute()
    )


@webhook_router.post("/stripe")
async def stripe_webhook(
    request: Request,
    supabase: AClient = Depends(get_supabase_client),
):
    payload = await request.body()
    sig = request.headers.get("stripe-signature")
    if not sig:
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature header")

    secrets = await _get_all_webhook_secrets(supabase)
    if not secrets:
        raise HTTPException(status_code=500, detail="No webhook secrets configured")

    try:
        event, _matched_secret = _verify_with_any_secret(payload, sig, secrets)
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    etype = event["type"]
    obj = event["data"]["object"]

    # Handle subscription invoices
    if etype in ("invoice.payment_succeeded", "invoice.payment_failed"):
        invoice_id = obj.get("id")
        stripe_customer_id = obj.get("customer")
        if not stripe_customer_id:
            return {"ok": True}

        is_failed = etype == "invoice.payment_failed"
        is_succeeded = etype == "invoice.payment_succeeded"

        # Identify renewals vs first invoice
        billing_reason = obj.get("billing_reason")
        is_renewal = billing_reason == "subscription_cycle"

        price_id = _first_price_id(obj)
        if not price_id:
            logger.warning("Invoice missing price_id: %s", invoice_id)
            return {"ok": True}

        md = obj.get("metadata") or {}
        outlet_id = None
        membership_id = None

        if md.get("outlet_id"):
            try:
                outlet_id = int(md["outlet_id"])
            except ValueError:
                outlet_id = None

        if md.get("membership_id"):
            try:
                membership_id = int(md["membership_id"])
            except ValueError:
                membership_id = None

        if outlet_id is None or not membership_id:
            mp_outlet, mp_membership = await _resolve_membership_price(supabase, price_id=price_id)
            outlet_id = outlet_id or mp_outlet
            membership_id = membership_id or mp_membership

        if outlet_id is None or not membership_id:
            logger.warning("Unable to resolve outlet/membership for invoice %s price %s", invoice_id, price_id)
            return {"ok": True}

        cust = await _get_customer_by_stripe_id(supabase, stripe_customer_id)
        if not cust:
            logger.warning("No customer found for stripe_customer_id=%s", stripe_customer_id)
            return {"ok": True}

        credits = await _get_membership_credits(supabase, membership_id)

        amount_minor = int((obj.get("amount_paid") if is_succeeded else obj.get("amount_due")) or 0)
        amount_major = float(amount_minor) / 100.0

        stripe_status = "failed" if is_failed else "paid"
        tx_type = "stripe_recurring" if is_renewal else "purchase"

        payload_tx = {
            "customer_id": int(cust["id"]),
            "appointment_id": FALLBACK_APPOINTMENT_ID,
            "outlet_id": int(outlet_id),
            "amount": amount_major,
            "type": tx_type,
            "description": (
                f"Stripe renewal ({stripe_status}) - {credits} credits"
                if is_renewal
                else f"Purchased {credits} credits"
            ),
            "membership_id": int(membership_id),
            "stripe_invoice_id": invoice_id,
            "stripe_subscription_id": obj.get("subscription"),
            "stripe_status": stripe_status,
        }

        try:
            await _upsert_credit_transaction(supabase, payload_tx)
        except Exception as e:
            logger.error("Failed to upsert credit transaction: %s", str(e), exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to record credit ledger")

        if is_failed:
            return {"ok": True, "renewal": is_renewal, "status": "failed"}

        try:
            period = obj["lines"]["data"][0]["period"]
            await _insert_membership_period_and_credit(
                supabase,
                customer_id=int(cust["id"]),
                outlet_id=int(outlet_id),
                membership_id=int(membership_id),
                credits=int(credits),
                period_start_unix=int(period["start"]),
                period_end_unix=int(period["end"]),
            )
        except Exception as e:
            logger.error("Failed to apply membership/credits: %s", str(e), exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to apply membership benefits")

        return {"ok": True, "renewal": is_renewal, "status": "paid"}

    # Handle subscription cancel
    if etype == "customer.subscription.deleted":
        stripe_customer_id = obj.get("customer")
        if not stripe_customer_id:
            return {"ok": True}

        cust = (
            await supabase.table("customers")
            .select("id")
            .eq("stripe_customer_id", stripe_customer_id)
            .single()
            .execute()
        ).data

        if cust:
            await (
                supabase.table("members")
                .update({"canceled_at": datetime.now(timezone.utc).isoformat()})
                .eq("customer_id", cust["id"])
                .is_("canceled_at", None)
                .execute()
            )

        return {"ok": True}

    return {"received": True}
