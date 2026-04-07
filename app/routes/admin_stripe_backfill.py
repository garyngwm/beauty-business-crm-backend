import logging
import stripe
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from supabase import AClient
from db.supabase import get_supabase_client

logger = logging.getLogger(__name__)

admin_stripe_router = APIRouter(prefix="/api/admin/stripe", tags=["admin-stripe"])


def _iso_from_unix(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


@admin_stripe_router.post("/backfill-renewals")
async def backfill_stripe_renewals(
    outlet_id: int = Query(...),
    limit: int = Query(500, ge=1, le=5000),
    supabase: AClient = Depends(get_supabase_client),
):

    gw = (
        await supabase.table("outlet_gateways")
        .select("stripe_secret_key")
        .eq("outlet_id", outlet_id)
        .single()
        .execute()
    ).data
    if not gw or not gw.get("stripe_secret_key"):
        raise HTTPException(400, "Outlet has no Stripe configuration")

    stripe.api_key = gw["stripe_secret_key"]

    # Get customers for mapping stripe_customer_id -> customer.id
    cust_rows = (
        await supabase.table("customers")
        .select("id, stripe_customer_id")
        .neq("stripe_customer_id", None)
        .execute()
    ).data or []

    customers_by_stripe_id = {
        c["stripe_customer_id"]: int(c["id"])
        for c in cust_rows
        if c.get("stripe_customer_id")
    }

    if not customers_by_stripe_id:
        return {"inserted_or_updated": 0, "message": "No customers with stripe_customer_id"}

    # Pull invoices from Stripe (history)
    inserted = 0
    starting_after = None

    while True:
        page = stripe.Invoice.list(
            limit=min(100, limit),
            starting_after=starting_after,
            expand=["data.lines.data.price"],
        )

        for inv in page.data:
            if inserted >= limit:
                return {"inserted_or_updated": inserted, "message": "Reached limit"}

            if inv.get("billing_reason") != "subscription_cycle":
                continue

            stripe_customer_id = inv.get("customer")
            if not stripe_customer_id:
                continue

            customer_id = customers_by_stripe_id.get(stripe_customer_id)
            if not customer_id:
                continue

            invoice_id = inv.get("id")
            subscription_id = inv.get("subscription")

            status = inv.get("status")
            stripe_status = "paid" if status == "paid" else "failed"

            amount_minor = int(inv.get("amount_paid") if status == "paid" else inv.get("amount_due") or 0)
            amount_major = float(amount_minor) / 100.0

            created_at = _iso_from_unix(int(inv.get("created") or 0))

            membership_id = None
            outlet_from_price = None

            try:
                price_id = inv["lines"]["data"][0]["price"]["id"]
                mp = (
                    await supabase.table("membership_prices")
                    .select("membership_id, outlet_id")
                    .eq("stripe_price_id", price_id)
                    .single()
                    .execute()
                ).data
                if mp:
                    membership_id = int(mp["membership_id"])
                    outlet_from_price = int(mp["outlet_id"])
            except Exception:
                pass

            if outlet_from_price is not None and outlet_from_price != outlet_id:
                continue

            payload_tx = {
                "customer_id": customer_id,
                "appointment_id": None,  # Set to a valid appointment ID if your schema does not allow NULL
                "outlet_id": outlet_id,
                "amount": amount_major,
                "type": "stripe_recurring",
                "description": f"Stripe renewal ({stripe_status})",
                "created_at": created_at,
                "membership_id": membership_id,
                "stripe_invoice_id": invoice_id,
                "stripe_subscription_id": subscription_id,
                "stripe_status": stripe_status,
            }

            await supabase.table("credit_transactions").upsert(
                payload_tx, on_conflict="stripe_invoice_id"
            ).execute()
            inserted += 1

        if not page.has_more:
            break
        starting_after = page.data[-1].id

    return {"inserted_or_updated": inserted}
