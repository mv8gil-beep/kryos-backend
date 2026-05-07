from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
import os
import stripe
from pydantic import BaseModel
import uuid
from typing import List

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

class UnlockSchedule(BaseModel):
    category: str
    allocation_pct: float
    tge_pct: float
    cliff_months: int
    duration_months: int

class LaunchAnalysisRequest(BaseModel):
    total_supply: float
    circulating_supply: float
    fdv: float
    liquidity: float
    tge_pct: float
    volume_24h: float
    avg_daily_volume: float
    unlock_schedules: List[UnlockSchedule]



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
    chain = data.get("chain", "solana")

    if not token:
        return {"error": "No token provided"}

    url = f"https://api.dexscreener.com/token-pairs/v1/{chain}/{token}"
    res = requests.get(url).json()

    if not isinstance(res, list) or len(res) == 0:
        return {"error": "Token not found"}

    # Pick pair with highest liquidity
    pair = max(
        res,
        key=lambda p: float(p.get("liquidity", {}).get("usd", 0) or 0),
    )

    price = float(pair.get("priceUsd", 0) or 0)
    liquidity = float(pair.get("liquidity", {}).get("usd", 0) or 0)
    volume = float(pair.get("volume", {}).get("h24", 0) or 0)
    fdv = float(pair.get("fdv", 0) or 0)

    score = 100

    if liquidity < 100000:
        score -= 25
    if volume < 50000:
        score -= 20
    if fdv > 100000000:
        score -= 15
    if price <= 0:
        score -= 20

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
        "chain": chain,
        "pair_address": pair.get("pairAddress"),
        "dex": pair.get("dexId"),
        "base_symbol": pair.get("baseToken", {}).get("symbol"),
        "base_name": pair.get("baseToken", {}).get("name"),
    }

@app.post("/analyze-launch")
def analyze_launch(data: LaunchAnalysisRequest):

    score = 100
    warnings = []
    recommendations = []

    circulating_pct = (
        data.circulating_supply / data.total_supply * 100
        if data.total_supply > 0 else 0
    )

    fdv_liquidity_ratio = (
        data.fdv / data.liquidity
        if data.liquidity > 0 else 999999
    )

    # TGE penalty
    if data.tge_pct > 20:
        score -= 25
        warnings.append("High TGE unlock")
        recommendations.append("Reduce TGE below 15%")

    elif data.tge_pct > 12:
        score -= 10
        warnings.append("Moderate TGE unlock")

    # Liquidity penalty
    if fdv_liquidity_ratio > 30:
        score -= 20
        warnings.append("Very thin liquidity")
        recommendations.append("Increase liquidity depth")

    elif fdv_liquidity_ratio > 15:
        score -= 10

    # Circulating supply penalty
    if circulating_pct < 10:
        score -= 15
        warnings.append("Very low circulating supply")

    # Volume support penalty
    if data.volume_24h < data.liquidity * 0.25:
        score -= 10
        warnings.append("Weak trading activity")

    # Unlock analysis
    for unlock in data.unlock_schedules:

        if unlock.duration_months < 12:
            score -= 5
            recommendations.append(
                f"Extend {unlock.category} vesting duration"
            )

        if unlock.tge_pct > 10:
            score -= 5
            warnings.append(
                f"{unlock.category} unlock too aggressive"
            )

    score = max(score, 1)

    risk = "Low"

    if score < 75:
        risk = "Medium"

    if score < 50:
        risk = "High"

    return {
        "score": score,
        "risk": risk,
        "summary": "Launch structure analysis completed.",
        "metrics": {
            "circulating_pct": round(circulating_pct, 2),
            "fdv_liquidity_ratio": round(fdv_liquidity_ratio, 2),
            "tge_pct": data.tge_pct,
            "liquidity": data.liquidity
        },
        "warnings": warnings,
        "recommendations": recommendations
    }
    