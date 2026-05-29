from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
import os
import stripe
from pydantic import BaseModel
import uuid
from typing import List, Optional

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
    email: Optional[str] = None
    token: Optional[str] = None
    chain: Optional[str] = "solana"
   

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
        "token": req.token or "unknown",
        "chain": req.chain or "solana",
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
    "token": report["token"],
    "chain": report.get("chain", "solana"),
    }


@app.post("/reports/{report_id}/mark-paid")
def mark_paid(report_id: str):
    if report_id in reports:
        reports[report_id]["paid"] = True

    return {"ok": True}


@app.post("/checkout")
def create_checkout(req: CheckoutRequest):
    stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
    print("STRIPE KEY MODE:", stripe.api_key[:7] if stripe.api_key else "MISSING")

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
        success_url=f"https://kryos.io/success?report_id={req.report_id}",
        cancel_url="https://kryos.io",
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

    # TGE penalty — early unlock risk
    if data.tge_pct >= 40:
        score -= 30
        warnings.append("Aggressive TGE unlock")
        recommendations.append("Reduce TGE closer to 10–15%")

    elif data.tge_pct >= 25:
        score -= 22
        warnings.append("High TGE unlock")

    elif data.tge_pct >= 15:
        score -= 10
        warnings.append("Moderate TGE unlock")

    # FDV / liquidity penalty — market depth risk
    if fdv_liquidity_ratio >= 100:
        score -= 35
        warnings.append("Extreme FDV/liquidity stress")
        recommendations.append("Increase liquidity before launch")

    elif fdv_liquidity_ratio >= 50:
        score -= 28
        warnings.append("Very high FDV/liquidity ratio")

    elif fdv_liquidity_ratio >= 25:
        score -= 14
        warnings.append("Elevated liquidity stress")

    elif fdv_liquidity_ratio >= 12:
        score -= 8

    # Circulating supply penalty — low float risk
    if circulating_pct < 5:
        score -= 30
        warnings.append("Extremely low circulating supply")
        recommendations.append(
            "Increase initial circulating float or reduce FDV"
        )

    elif circulating_pct < 10:
        score -= 22
        warnings.append("Very low circulating supply")

    elif circulating_pct < 20:
        score -= 6
        warnings.append("Low circulating float")

    # Volume support penalty
    volume_liquidity_ratio = (
        data.volume_24h / data.liquidity
        if data.liquidity > 0 else 0
    )

    if volume_liquidity_ratio < 0.05:
        score -= 20
        warnings.append("Very weak trading activity versus liquidity")

    elif volume_liquidity_ratio < 0.15:
        score -= 12
        warnings.append("Weak trading activity")

    elif volume_liquidity_ratio < 0.30:
        score -= 6
    
        # Positive quality signals — reward healthy launch structure
    if circulating_pct >= 25:
        score += 6

    if fdv_liquidity_ratio <= 10:
        score += 6

    if data.tge_pct <= 12:
        score += 5

    if volume_liquidity_ratio >= 0.50:
        score += 5

    # Unlock schedule penalty
    for unlock in data.unlock_schedules:

        if unlock.duration_months < 12:
            score -= 8
            recommendations.append(
                f"Extend {unlock.category} vesting duration"
            )

        if unlock.tge_pct > 15:
            score -= 10
            warnings.append(
                f"{unlock.category} unlock too aggressive"
            )

        elif unlock.tge_pct > 8:
            score -= 5

    score = max(min(score, 100), 1)

    if score >= 80:
        risk = "Low"

    elif score >= 45:
        risk = "Medium"

    else:
        risk = "High"

    strengths = []
    weaknesses = []

    if circulating_pct >= 25:
        strengths.append("Healthy circulating supply at launch")
    elif circulating_pct < 10:
        weaknesses.append("Very low circulating supply")

    if fdv_liquidity_ratio <= 10:
        strengths.append("Strong liquidity relative to valuation")
    elif fdv_liquidity_ratio >= 25:
        weaknesses.append("High FDV relative to liquidity")

    if data.tge_pct <= 12:
        strengths.append("Disciplined TGE structure")
    elif data.tge_pct >= 25:
        weaknesses.append("Aggressive TGE unlock")

    if score >= 80:
        investor_summary = (
            "Launch structure appears strong with healthy liquidity, "
            "reasonable token distribution, and manageable unlock risk."
        )

        would_invest = (
            "Yes. Based on current launch metrics, this launch appears "
            "well structured and investable."
        )

    elif score >= 45:
        investor_summary = (
            "Launch has both strengths and weaknesses. Investors should "
            "monitor dilution risk, liquidity depth, and unlock schedules."
        )

        would_invest = (
            "Possibly. The opportunity may be attractive, but additional "
            "due diligence is recommended."
        )

    else:
        investor_summary = (
            "Launch structure presents elevated risk due to liquidity, "
            "distribution, or unlock concerns."
        )

        would_invest = (
            "No. Current launch conditions appear too risky without "
            "meaningful improvements."
        )

    return {
        "score": score,
        "risk": risk,
        "summary": "Launch structure analysis completed.",

        "investor_summary": investor_summary,
        "would_invest": would_invest,
        "strengths": strengths,
        "weaknesses": weaknesses,

        "metrics": {
            "circulating_pct": round(circulating_pct, 2),
            "fdv_liquidity_ratio": round(fdv_liquidity_ratio, 2),
            "tge_pct": data.tge_pct,
            "liquidity": data.liquidity
        },
        "warnings": warnings,
        "recommendations": recommendations
    }