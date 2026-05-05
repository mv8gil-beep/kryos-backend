from fastapi import FastAPI
import os

app = FastAPI()

@app.get("/")
def root():
    return {"message": "Kryos backend is live"}

@app.get("/health")
def health():
    return {"ok": True}
