"""Razorpay Test Mode HTTP client for RecoverAI.

Uses httpx directly to call Razorpay REST API v1.
No Razorpay SDK dependency. Full control over HTTP calls.
"""
from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def _get_auth_header() -> str:
    """Create Basic auth header from Razorpay credentials."""
    key_id = settings.razorpay_key_id
    key_secret = settings.razorpay_key_secret
    raw = f"{key_id}:{key_secret}"
    return "Basic " + base64.b64encode(raw.encode()).decode()


def _headers() -> dict[str, str]:
    return {
        "Authorization": _get_auth_header(),
        "Content-Type": "application/json",
    }


def create_payment_link(
    amount_paise: int,
    currency: str,
    customer_name: str,
    customer_email: str | None,
    customer_contact: str | None,
    description: str,
    reference_id: str,
    callback_url: str | None = None,
    callback_method: str | None = None,
) -> dict[str, Any]:
    """Create a Razorpay Payment Link via the REST API.

    Args:
        amount_paise: Amount in smallest currency unit (paise for INR).
        currency: Currency code (e.g. "INR").
        customer_name: Customer name for the payment link.
        customer_email: Optional customer email.
        customer_contact: Optional customer phone.
        description: Description shown on the payment page.
        reference_id: Unique reference ID for idempotency.
        callback_url: Optional URL to redirect after payment.
        callback_method: Optional callback method ("get" or "post").

    Returns:
        Razorpay API response dict containing:
        - id: Payment link ID
        - short_url: Shareable payment link URL
        - status: "created"
        - amount: Amount in paise
        - currency
        - reference_id
        - customer: dict with name/email/contact

    Raises:
        RazorpayAPIError: If the API call fails.
    """
    url = f"{settings.razorpay_base_url}/payment_links"

    payload: dict[str, Any] = {
        "amount": amount_paise,
        "currency": currency,
        "description": description,
        "reference_id": reference_id,
        "customer": {
            "name": customer_name,
        },
    }

    if customer_email:
        payload["customer"]["email"] = customer_email
    if customer_contact:
        payload["customer"]["contact"] = customer_contact

    if callback_url:
        payload["callback_url"] = callback_url
    if callback_method:
        payload["callback_method"] = callback_method

    # Notify via webhook for async status updates
    payload["notify"] = {
        "sms": False,
        "email": bool(customer_email),
    }

    logger.info("Razorpay: Creating payment link for reference_id=%s amount=%d %s", reference_id, amount_paise, currency)

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(url, json=payload, headers=_headers())
            resp.raise_for_status()
            data = resp.json()
            logger.info("Razorpay: Payment link created id=%s short_url=%s", data.get("id"), data.get("short_url"))
            return data
    except httpx.TimeoutException as e:
        logger.error("Razorpay: Timeout creating payment link: %s", e)
        raise RazorpayAPIError(f"Razorpay API timeout: {e}") from e
    except httpx.HTTPStatusError as e:
        error_body = {}
        try:
            error_body = e.response.json()
        except Exception:
            pass
        error_description = error_body.get("error", {}).get("description", str(e))
        error_code = error_body.get("error", {}).get("code", "unknown")
        logger.error("Razorpay: API error %s: %s", error_code, error_description)
        raise RazorpayAPIError(
            f"Razorpay API error: {error_description}",
            code=error_code,
            status_code=e.response.status_code,
        ) from e
    except httpx.RequestError as e:
        logger.error("Razorpay: Network error: %s", e)
        raise RazorpayAPIError(f"Razorpay network error: {e}") from e


def has_credentials() -> bool:
    """Check if Razorpay credentials are configured."""
    return bool(settings.razorpay_key_id and settings.razorpay_key_secret)


class RazorpayAPIError(Exception):
    """Raised when a Razorpay API call fails."""

    def __init__(
        self,
        message: str,
        code: str | None = None,
        status_code: int | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.status_code = status_code
