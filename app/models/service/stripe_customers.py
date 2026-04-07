import stripe
import os

stripe.api_key = os.environ["STRIPE_SECRET_KEY"]

async def get_or_create_stripe_customer(email: str, name: str | None, supabase, customer_id: int):
    # Try to read from DB first
    row = await (supabase.table("customers")
                 .select("id, stripe_customer_id")
                 .eq("id", customer_id)
                 .single().execute())
    if row.data and row.data.get("stripe_customer_id"):
        return row.data["stripe_customer_id"]

    sc = stripe.Customer.create(email=email, name=name)
    await (supabase.table("customers")
           .update({"stripe_customer_id": sc["id"]})
           .eq("id", customer_id).execute())
    return sc["id"]