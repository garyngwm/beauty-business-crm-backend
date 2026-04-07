# Beauty Business CRM — Backend

A FastAPI + Supabase backend for a beauty business CRM / POS system. Handles appointments, staff, services, memberships, payments, and Stripe webhook processing.

## Tech Stack

- Python 3.11+
- FastAPI
- Supabase (auth + database)
- Stripe (payments + webhooks)

## Prerequisites

- Python 3.11+
- A [Supabase](https://supabase.com) project
- A [Stripe](https://stripe.com) account
- [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) (for local Stripe webhook testing)

## Setup

1. Clone this repo

2. Install the **Ruff VSCode extension** (linter/formatter) and add this to your `settings.json`:

   ```json
   "[python]": {
     "editor.formatOnSave": true,
     "editor.codeActionsOnSave": {
       "source.fixAll": "explicit",
       "source.organizeImports": "explicit"
     },
     "editor.defaultFormatter": "charliermarsh.ruff"
   }
   ```

3. Go into the root directory:

   ```
   cd beauty-business-crm-backend
   ```

4. Create and activate a virtual environment:

   ```
   python -m venv venv

   # Windows
   venv\Scripts\activate

   # macOS / Linux
   source venv/bin/activate
   ```

5. Install dependencies:

   ```
   cd .scripts
   bash update_dependencies.sh
   cd ..
   pip install -r .requirements/requirements.txt
   ```

6. Create your `.env` file:

   ```
   touch .env
   ```

   Then fill in the values (see [Environment Variables](#environment-variables) below).

7. Run the local server:

   ```
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
   # Visit http://localhost:8080
   ```

8. (Optional) Seed the database by pasting `db/seed.sql` into Supabase's SQL editor.

## Environment Variables

Create a `.env` file in the root directory with the following:

```env
# Your Supabase project URL
# Found in: Supabase Dashboard > Project Settings > API > Project URL
SUPABASE_URL=https://your-project-id.supabase.co

# Your Supabase service role key (NOT the anon key — this is a secret)
# Found in: Supabase Dashboard > Project Settings > API > service_role
SUPABASE_KEY=your-supabase-service-role-key

# Your Supabase JWT secret (used to verify auth tokens)
# Found in: Supabase Dashboard > Project Settings > API > JWT Secret
SUPABASE_JWT_SECRET=your-supabase-jwt-secret
```

## Stripe Webhook Testing (Local)

To receive Stripe webhooks locally, use Cloudflare Tunnel:

```
winget install Cloudflare.cloudflared

# In a separate terminal while your server is running:
cloudflared tunnel --url http://localhost:8080
```

Copy the generated URL into your Stripe Dashboard > Webhooks as a new endpoint for each outlet.

## CORS Configuration

Update the `origins` list in `app/main.py` to match your frontend URL:

```python
origins = [
    "http://localhost:5173",          # local dev
    "https://your-frontend-url.com",  # your deployed frontend
]
```

## Outlet Configuration

This system supports **one or multiple outlets** (locations/branches). Here's how to set it up for your situation:

### Single Outlet

1. In `db/seed.sql`, keep only one row in the outlets insert:
   ```sql
   INSERT INTO outlets (id, name, address, phone, active)
   VALUES
     (1, 'Your Outlet Name', 'Your Address', 'Your Phone', true)
   ```
2. In the 6 route files that validate outlet IDs (e.g. `app/routes/staff/staff.py`), update to:
   ```python
   if outlet_id not in [1]:
   ```
3. In `app/routes/sales/sales.py`, keep only one entry:
   ```python
   MEMBERSHIP_STRIPE_FEE_RATE = {
       1: 0.007,  # Your Stripe fee rate
   }
   ```
4. In `app/main.py`, your single frontend URL is sufficient in `origins`.

### Multiple Outlets

1. In `db/seed.sql`, add a row per outlet:
   ```sql
   INSERT INTO outlets (id, name, address, phone, active)
   VALUES
     (1, 'Outlet One', '123 Example Street', '61234567', true),
     (2, 'Outlet Two', '456 Example Avenue', '62345678', true),
     (3, 'Outlet Three', '789 Example Road',  '63456789', true)
   ```
2. In the 6 route files, update the list to include all your outlet IDs:
   ```python
   if outlet_id not in [1, 2, 3]:
   ```
3. In `app/routes/sales/sales.py`, add a rate per outlet:
   ```python
   MEMBERSHIP_STRIPE_FEE_RATE = {
       1: 0.007,
       2: 0.005,
       3: 0.006,
   }
   ```
4. Each outlet can have its own Stripe account — configure these in the `outlet_gateways` table in Supabase.

---

## Customisation Checklist

Before going live, replace the following placeholders in the codebase:

| File | What to Replace |
|------|----------------|
| `.env` | All env vars — Supabase URL, service role key, JWT secret |
| `app/main.py` | `origins` list — replace `https://your-frontend-url.com` with your actual frontend URL |
| `db/seed.sql` | Outlet names and addresses — replace `Outlet One / Outlet Two` and example addresses with your real outlets |
| `app/routes/sales/sales.py` | `MEMBERSHIP_STRIPE_FEE_RATE` — update fee rates to match your Stripe account's fee structure per outlet |
| `app/routes/staff/staff.py` (and 5 other route files) | `if outlet_id not in [1, 2]` — update `[1, 2]` to match your actual outlet IDs from the database |
| `app/routes/membership/membership.py` | `FALLBACK_APPOINTMENT_ID` — set to a valid appointment ID if your `credit_transactions.appointment_id` column does not allow NULL |
| `app/routes/admin_stripe_backfill.py` | Same as above — `appointment_id: None` |

## Deployment

Deployable on [Render](https://render.com) or any Python hosting provider. Set all environment variables in your hosting platform's dashboard — never commit your `.env` file.
