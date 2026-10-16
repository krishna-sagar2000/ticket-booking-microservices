"""Fake payment gateway. Pretend this is the bank.

POST /charge          -> approves the payment
POST /admin/mode      -> {"mode": "ok" | "down" | "slow"} to test failure paths
"""
import asyncio
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

app = FastAPI(title="Mock Payment Gateway", version="1.0.0")
state = {"mode": "ok"}


class Charge(BaseModel):
    bookingId: str
    amount: float


class Mode(BaseModel):
    mode: str


@app.get("/health")
def health():
    return {"status": "UP", "service": "mock-gateway", "mode": state["mode"]}


@app.post("/charge")
async def charge(body: Charge):
    if state["mode"] == "down":
        return JSONResponse(status_code=503, content={"code": "GATEWAY_DOWN", "message": "Gateway is down", "correlationId": "-"})
    if state["mode"] == "slow":
        await asyncio.sleep(10)
    return {"status": "APPROVED", "bookingId": body.bookingId, "amount": body.amount}


@app.post("/admin/mode")
def set_mode(body: Mode):
    if body.mode not in ("ok", "down", "slow"):
        return JSONResponse(status_code=400, content={"code": "VALIDATION_ERROR", "message": "mode must be ok, down or slow", "correlationId": "-"})
    state["mode"] = body.mode
    return {"mode": state["mode"]}
