import os
from dotenv import load_dotenv

from fastapi import FastAPI, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, Response

from app.routes.appointment.appointment import appointment_router
from app.routes.payment.payment import payments_router
from app.routes.customer import customer_router
from app.routes.outlet import outlet_router
from app.routes.service.category import category_router
from app.routes.service.category_color import category_color_router
from app.routes.service.service import service_router
from app.routes.staff.blocked_time import blocked_time_router
from app.routes.staff.shift import shift_router
from app.routes.staff.staff import staff_router
from app.routes.staff.time_off import time_off_router
from app.routes.membership.membership import membership_router
from app.routes.members.members import members_router
from app.routes.sales.sales import sales_router
from app.routes.stripe_webhook.stripe_webhook import webhook_router
from app.routes.admin_stripe_backfill import admin_stripe_router

from app.utils.supabase_auth import require_supabase_user


load_dotenv()

app = FastAPI()

# CORS settings
origins = [
    "http://localhost:5173",
    "https://your-frontend-url.com",  # Replace with your deployed frontend URL
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    # allow_credentials=True,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.options("/{path:path}")
async def preflight_handler(path: str, request: Request):
    return Response(status_code=204)

auth_dep = [Depends(require_supabase_user)]

""" Guard against web crawlers (recursively follows links) """
# Middleware to augment responses
@app.middleware("http")
async def add_robot_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


# Robots.txt file to tell search engine to restrict crawlers from URL access
@app.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    data = """User-agent: *\nDisallow: /"""
    return data


""" Router registration """

# Routers managing services
# With authentication dependency
app.include_router(category_color_router, dependencies=auth_dep)
app.include_router(category_router, dependencies=auth_dep)
app.include_router(service_router, dependencies=auth_dep)

# Routers managing staffs
app.include_router(staff_router, dependencies=auth_dep)
app.include_router(shift_router, dependencies=auth_dep)
app.include_router(time_off_router, dependencies=auth_dep)
app.include_router(blocked_time_router, dependencies=auth_dep)

# Router managing others
app.include_router(appointment_router, dependencies=auth_dep)
app.include_router(customer_router, dependencies=auth_dep)
app.include_router(outlet_router, dependencies=auth_dep)
app.include_router(membership_router, dependencies=auth_dep)
app.include_router(members_router, dependencies=auth_dep)

# Router managing payments
app.include_router(payments_router, dependencies=auth_dep)
app.include_router(sales_router, dependencies=auth_dep)
app.include_router(admin_stripe_router, dependencies=auth_dep)

# Stripe webhook stays public
app.include_router(webhook_router)

# Test route
@app.get("/")
def welcome_screen():
    return "Hello World!"

@app.get("/api/health")
def health():
    return {"ok": True}

@app.get("/api/me")
def me(claims=Depends(require_supabase_user)):
    return {
        "user_id": claims["sub"],
        "claims": {
            "email": claims.get("email"),
            "role": claims.get("role"),
            "aud": claims.get("aud"),
        },
    }
