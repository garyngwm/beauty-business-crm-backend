# app/routes/sales.py

import logging
from typing import List, Dict, Tuple

from fastapi import APIRouter, Depends, HTTPException
from supabase import AClient

from app.models.sales.credit_transaction import SalesRecordResponse
from db.supabase import get_supabase_client

logger = logging.getLogger(__name__)

sales_router = APIRouter(
    prefix="/api/sales-records",
    tags=["sales"],
)

GST_MULTIPLIER = 1.09

# Stripe fee rates per outlet — update these to match your Stripe account's fee structure
MEMBERSHIP_STRIPE_FEE_RATE = {
    1: 0.007,  # Outlet 1 fee rate (e.g. 0.7%)
    2: 0.005,  # Outlet 2 fee rate (e.g. 0.5%)
}

def _calc_gst_fee(amount: float, gst_rate: float | None) -> float:
    if not gst_rate or gst_rate <= 0:
        return 0.0
    gst_fee = amount * gst_rate / (1.0 + gst_rate)
    return round(gst_fee, 2)

def _calc_membership_stripe_fee(amount: float, outlet_id: int) -> float:
    rate = MEMBERSHIP_STRIPE_FEE_RATE.get(int(outlet_id), 0.0)
    return round(amount * rate * GST_MULTIPLIER, 2)

def _is_stripe_row(row: dict) -> bool:
    # treat as Stripe-driven if it has Stripe identifiers/status
    return bool(row.get("stripe_invoice_id") or row.get("stripe_subscription_id") or row.get("stripe_status"))

def _stripe_fee_for_row(row: dict) -> float:
    """
    - Only charge fee if stripe_status == "paid"
    - Only apply to membership-related Stripe rows:
      type in ["purchase", "stripe_recurring"] AND has Stripe identifiers
    """
    if row.get("stripe_status") != "paid":
        return 0.0

    if row.get("type") not in ("purchase", "stripe_recurring"):
        return 0.0

    if not _is_stripe_row(row):
        return 0.0

    outlet_id = row.get("outlet_id")
    if not outlet_id:
        return 0.0

    amount = float(row.get("amount") or 0)
    if amount <= 0:
        return 0.0

    return _calc_membership_stripe_fee(amount, int(outlet_id))

@sales_router.get("", response_model=List[SalesRecordResponse])
async def get_sales_records(supabase: AClient = Depends(get_supabase_client)):
    try:
        # 1) Base query from credit_transactions
        tx_response = (
            await supabase.from_("credit_transactions")
            .select("*, membership:membership_id ( title )")
            .order("created_at", desc=True)
            .execute()
        )

        transactions = tx_response.data or []

        if not transactions:
            return []

        customer_ids = {row["customer_id"] for row in transactions if row.get("customer_id")}
        outlet_ids = {row["outlet_id"] for row in transactions if row.get("outlet_id")}

        mp_pairs: set[Tuple[int, int]] = set()
        for row in transactions:
            if row.get("membership_id") and row.get("outlet_id"):
                # Only meaningful for membership-related sales types
                if row.get("type") in ("purchase", "stripe_recurring"):
                    mp_pairs.add((int(row["membership_id"]), int(row["outlet_id"])))

        gst_rate_by_pair: Dict[Tuple[int, int], float] = {}
        if mp_pairs:
            membership_ids = sorted({m for (m, _o) in mp_pairs})
            outlet_ids_for_mp = sorted({o for (_m, o) in mp_pairs})

            mp_resp = (
                await supabase.from_("membership_prices")
                .select("membership_id, outlet_id, gst_percentage")
                .in_("membership_id", membership_ids)
                .in_("outlet_id", outlet_ids_for_mp)
                .execute()
            )

            for mp in mp_resp.data or []:
                key = (int(mp["membership_id"]), int(mp["outlet_id"]))
                gst_rate_by_pair[key] = float(mp.get("gst_percentage") or 0)
        
        customers_by_id: Dict[int, dict] = {}
        if customer_ids:
            cust_response = (
                await supabase.from_("customers")
                .select("id, first_name, last_name")
                .in_("id", list(customer_ids))
                .execute()
            )
            for c in cust_response.data or []:
                customers_by_id[c["id"]] = c

        outlets_by_id: Dict[int, dict] = {}
        if outlet_ids:
            outlet_response = (
                await supabase.from_("outlets")
                .select("id, name")
                .in_("id", list(outlet_ids))
                .execute()
            )
            for o in outlet_response.data or []:
                outlets_by_id[o["id"]] = o

        sales_records: List[SalesRecordResponse] = []

        for row in transactions:
            customer = customers_by_id.get(row["customer_id"])
            outlet = outlets_by_id.get(row["outlet_id"]) if row.get("outlet_id") else None

            customer_name = ""
            if customer:
                first_name = customer.get("first_name") or ""
                last_name = customer.get("last_name") or ""
                customer_name = f"{first_name} {last_name}".strip()

            outlet_name = outlet.get("name") if outlet else None

            membership_title = None
            if row.get("membership"):
                membership_title = row["membership"].get("title")
            
            stripe_fee = _stripe_fee_for_row(row)
            amount = float(row.get("amount") or 0)

            gst_fee = 0.0
            if row.get("type") in ("purchase", "stripe_recurring") and row.get("membership_id") and row.get("outlet_id"):
                key = (int(row["membership_id"]), int(row["outlet_id"]))
                gst_rate = gst_rate_by_pair.get(key)
                gst_fee = _calc_gst_fee(amount, gst_rate)

            record = SalesRecordResponse(
                id=row["id"],
                customer_id=row["customer_id"],
                customerName=customer_name,  # alias
                appointmentId=row.get("appointment_id"),
                outletId=row.get("outlet_id"),
                outletName=outlet_name,
                amount=row["amount"],
                type=row["type"],
                description=row.get("description"),
                createdAt=row["created_at"],
                membershipTitle=membership_title,
                stripeStatus=row.get("stripe_status"),
                stripeInvoiceId=row.get("stripe_invoice_id"),
                stripeSubscriptionId=row.get("stripe_subscription_id"),
                stripeFee=stripe_fee,
                gstFee=gst_fee,
            )

            sales_records.append(record)

        return sales_records

    except Exception as e:
        logger.error(f"Error fetching sales records: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get sales records")
