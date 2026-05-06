    from fastapi import FastAPI
    from pydantic import BaseModel
    import uuid
    from fastapi.middleware.cors import CORSMiddleware
    import os
    import stripe
    from pydantic import BaseModel
    import requests

    app = FastAPI()
    app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    )

    paid_reports = {}

    class CreateReportRequest(BaseModel):
    email: str | None = None
    class CheckoutRequest(BaseModel):
    report_id: str

    @app.get("/")
    def root():
    return {"message": "Kryos backend is live"}

    @app.get("/health")
    def health():
    return {"ok": True}

    @app.post("/reports/create")
    def create_report(req: CreateReportRequest):
    report_id = str(uuid.uuid4())
    paid_reports[report_id] = False
    return {"report_id": report_id, "paid": False}

    @app.get("/reports/{report_id}")
    def get_report(report_id: str):
    paid = paid_reports.get(report_id, False)
    return {"report_id": report_id, "paid": paid}
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
        success_url="http://localhost:5173/success?report_id=" + req.report_id,
        cancel_url="http://localhost:5173",
    )

    return {"url": session.url}

    @app.post("/reports/{report_id}/mark-paid")
    def mark_paid(report_id: str):
    paid_reports[report_id] = True
    return {"report_id": report_id, "paid": True}
    @app.post("/analyze-token")
    def analyze_token(data: dict):
    token = data.get("token")

    if not token:
        return {"error": "No token provided"}

    url = f"https://api.dexscreener.com/latest/dex/search/?q={token}"
    res = requests.get(url).json()

    if not res.get("pairs"):
        return {"error": "Token not found"}

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
