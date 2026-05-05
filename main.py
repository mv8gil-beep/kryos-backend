from fastapi import FastAPI
from pydantic import BaseModel
import uuid
from fastapi.middleware.cors import CORSMiddleware
import os
import stripe
from pydantic import BaseModel

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
