"""Small Razorpay client using only the standard library.

Covers what FoodyX needs: creating orders, verifying the checkout
signature and verifying webhook signatures.
"""
import base64
import hashlib
import hmac
import json
import urllib.error
import urllib.request

API_BASE = "https://api.razorpay.com/v1"


class RazorpayError(Exception):
    pass


def create_order(key_id, key_secret, amount_paise, receipt, notes=None, currency="INR"):
    payload = json.dumps({
        "amount": int(amount_paise),
        "currency": currency,
        "receipt": str(receipt)[:40],
        "notes": notes or {},
    }).encode()
    token = base64.b64encode(f"{key_id}:{key_secret}".encode()).decode()
    req = urllib.request.Request(
        f"{API_BASE}/orders",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Basic {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="ignore")
        raise RazorpayError(f"Razorpay returned {exc.code}: {body[:200]}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RazorpayError(f"Could not reach Razorpay: {exc}") from exc


def _hmac(secret, message):
    return hmac.new(secret.encode(), message.encode() if isinstance(message, str) else message, hashlib.sha256).hexdigest()


def verify_payment_signature(order_id, payment_id, signature, key_secret):
    if not (order_id and payment_id and signature and key_secret):
        return False
    expected = _hmac(key_secret, f"{order_id}|{payment_id}")
    return hmac.compare_digest(expected, signature)


def verify_webhook_signature(body_bytes, signature, webhook_secret):
    if not (signature and webhook_secret):
        return False
    expected = _hmac(webhook_secret, body_bytes)
    return hmac.compare_digest(expected, signature)


def to_paise(amount):
    from decimal import Decimal

    return int((Decimal(str(amount)) * 100).to_integral_value())
