from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
import os
import stripe
from pydantic import BaseModel
import uuid

app = FastAPI()

# CORS (allow frontend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory storage (temporary)
reports = {}

# ---------- MODELS ----------
class CreateReportRequest(BaseModel):
    email: str | None = None
    token: str | None = None

class CheckoutRequest(BaseModel):
    report_id: str


# ---------- ROUTES ----------

@app.post("/reports/create")
def create_report(req: CreateReportRequest):
    report_id = str(uuid.uuid4())

    reports[report_id] = {
        "paid": False,
        "token": req.token or "unknown"
    }

    return {
        "report_id": report_id,
        "paid": False
    }


@app.get("/reports/{report_id}")
def get_report(report_id: str):
    report = reports.get(report_id)

    if not report:
        return {"error": "Not found"}

    return {
        "report_id": report_id,
        "paid": report["paid"],
        "token": report["token"]
    }


@app.post("/reports/{report_id}/mark-paid")
def mark_paid(report_id: str):
    if report_id in reports:
        reports[report_id]["paid"] = True

    return {"ok": True}


@app.post("/checkout")
def create_checkout(req: CheckoutRequest):
    stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")

    session = stripe.checkout.Session.create(
        mode="payment",
        payment_method_types=["card"],
        line_items=[
            {
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": "Kryos Full Risk Report",
                    },
                    "unit_amount": 2900,
                },
                "quantity": 1,
            }
        ],
        client_reference_id=req.report_id,
        metadata={"report_id": req.report_id},
        success_url=f"http://localhost:5173/success?report_id={req.report_id}",
        cancel_url="http://localhost:5173",
    )

    return {"url": session.url}


@app.post("/analyze-token")
def analyze_token(data: dict):
    token = data.get("token")

    if not token:
        return {"error": "No token provided"}

    url = f"https://api.dexscreener.com/latest/dex/search/?q={token}"
    res = requests.get(url).json()

    if not res.get("pairs"):
        return {"error": "Token not found"}

    token_lower = token.lower()

    matching_pairs = [
    p for p in res["pairs"]
    if p.get("baseToken", {}).get("symbol", "").lower() == token_lower
    ]

if matching_pairs:
    pair = matching_pairs[0]
else:
    pair = res["pairs"][0]

    price = float(pair.get("priceUsd", 0))
    liquidity = float(pair.get("liquidity", {}).get("usd", 0))
    volume = float(pair.get("volume", {}).get("h24", 0))
    fdv = float(pair.get("fdv", 0))

    score = 100

    if liquidity < 100000:
        score -= 20
    if volume < 50000:
        score -= 20
    if fdv > 100000000:
        score -= 20
    if price < 0.01:
        score -= 10

    if score > 75:
        risk = "Low"
    elif score > 50:
        risk = "Medium"
    else:
        risk = "High"

    return {
        "score": score,
        "risk": risk,
        "price": price,
        "liquidity": liquidity,
        "volume_24h": volume,
        "fdv": fdv,
        "token": token,
    }