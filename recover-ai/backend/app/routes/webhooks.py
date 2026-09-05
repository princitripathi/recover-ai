"""Razorpay webhook endpoint for RecoverAI.

POST /api/webhooks/razorpay
- Verifies Razorpay signature (HMAC SHA256)
- Rejects invalid signatures with 400
- Idempotent via event_id unique constraint
- Updates recovery action, transaction, amount_recovered only on verified payment success
"""
from fastapi import APIRouter, Request, Header
from fastapi.responses import JSONResponse

from app.services.webhook_service import process_webhook_event

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


@router.post("/razorpay")
async def handle_razorpay_webhook(
    request: Request,
    x_razorpay_signature: str | None = Header(default=None, alias="X-Razorpay-Signature"),
):
    raw_body = await request.body()
    # Build headers dict case-insensitively
    headers = dict(request.headers)

    try:
        # Use raw body and headers for signature verification
        result = process_webhook_event(raw_body, headers)
    except ValueError as e:
        msg = str(e)
        if "Missing" in msg:
            return JSONResponse(status_code=400, content={"detail": msg, "error": "missing_signature"})
        if "Invalid" in msg:
            return JSONResponse(status_code=400, content={"detail": msg, "error": "invalid_signature"})
        return JSONResponse(status_code=400, content={"detail": msg})

    # Map service duplicate/ignored to HTTP 200 idempotent success
    # Always return 200 for valid signature (even for failed reference lookup) except signature errors
    status_map = {
        "processed": 200,
        "duplicate": 200,
        "ignored": 200,
        "failed": 200,
    }
    http_status = status_map.get(result.get("status", "processed"), 200)
    return JSONResponse(status_code=http_status, content=result)


@router.get("/events")
def list_webhook_events():
    """List recent webhook events for debugging/audit."""
    from app.database import get_connection

    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM webhook_events ORDER BY received_at DESC LIMIT 100").fetchall()
    return {"events": [dict(r) for r in rows]}
