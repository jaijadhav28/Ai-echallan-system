"""SMS delivery.

A small provider interface is defined so another gateway (MSG91, Twilio, ...)
can be added later without touching the callers. Fast2SMS is the initial
provider. Every send attempt - including the ones refused because the API key is
missing - is written to the ``sms_logs`` collection so the officer can see what
the system tried to do.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod

import httpx

from ..config import settings
from ..utils import utcnow_iso
from .base import not_configured, result

logger = logging.getLogger("rto.sms")

PROVIDER = "SMS Gateway"
INSTRUCTION = (
    "Add SMS_API_KEY (and optionally SMS_SENDER_ID) to backend/.env "
    "(get it from fast2sms.com/dashboard/dev-api)."
)


def is_configured() -> bool:
    return settings.sms_configured


def normalise_phone(phone: str) -> str:
    digits = "".join(character for character in str(phone or "") if character.isdigit())
    if len(digits) > 10 and digits.startswith("91"):
        digits = digits[2:]
    return digits[-10:] if len(digits) >= 10 else digits


# --------------------------------------------------------------------------- #
# Provider interface
# --------------------------------------------------------------------------- #
class SmsProvider(ABC):
    name: str = "provider"
    display_name: str = "SMS Provider"

    @abstractmethod
    def configured(self) -> bool: ...

    @abstractmethod
    async def send(self, phone: str, message: str) -> dict: ...

    @abstractmethod
    async def balance(self) -> dict: ...


class Fast2SmsProvider(SmsProvider):
    name = "fast2sms"
    display_name = "Fast2SMS"
    endpoint = "https://www.fast2sms.com/dev/bulkV2"
    wallet_endpoint = "https://www.fast2sms.com/dev/wallet"
    # Local placeholder — not a real Fast2SMS credential.
    DEMO_KEYS = {"demo", "demo_key", "fast2sms_demo"}

    def configured(self) -> bool:
        return bool(settings.sms_api_key.strip())

    def _is_demo_key(self) -> bool:
        return settings.sms_api_key.strip().lower() in self.DEMO_KEYS

    def _headers(self) -> dict:
        return {"authorization": settings.sms_api_key.strip()}

    async def send(self, phone: str, message: str) -> dict:
        number = normalise_phone(phone)
        if len(number) != 10:
            return result(
                ok=False,
                provider=self.display_name,
                message=f"'{phone}' is not a valid 10 digit Indian mobile number.",
            )

        if self._is_demo_key():
            logger.info(
                "Fast2SMS DEMO key: SMS to %s****%s accepted locally (not delivered). %s",
                number[:2],
                number[-2:],
                message[:80],
            )
            return result(
                ok=True,
                provider=self.display_name,
                message=f"Demo SMS accepted for number ending {number[-4:]} (not delivered to the phone).",
                data={"phone": number, "delivery": "DEMO_LOCAL"},
                status_code=200,
                latency_ms=0,
            )

        # Fast2SMS Quick SMS (route=q):
        # Prefer POST /dev/bulkV2 with JSON payload to avoid URL-length limits and encoding issues
        sender_id = settings.sms_sender_id.strip()
        payload: dict[str, Any] = {
            "route": "dlt" if sender_id else "q",
            "message": message,
            "numbers": number,
            "language": "english",
            "flash": 0,
        }
        if sender_id:
            payload["sender_id"] = sender_id

        headers = {
            "authorization": settings.sms_api_key.strip(),
            "Content-Type": "application/json",
        }

        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    self.endpoint,
                    headers=headers,
                    json=payload,
                )
                # Fallback to GET if endpoint rejects POST with 405
                if response.status_code == 405:
                    response = await client.get(
                        self.endpoint,
                        headers=self._headers(),
                        params=payload,
                    )
            latency = int((time.perf_counter() - started) * 1000)
        except httpx.HTTPError as exc:
            return result(
                ok=False, provider=self.display_name, message=f"SMS request failed: {exc}"
            )

        try:
            body = response.json()
        except ValueError:
            body = {"raw": response.text[:200]}

        succeeded = response.status_code == 200 and bool(body.get("return"))
        err_msg = body.get("message") or body
        if not succeeded:
            err_str = str(err_msg)
            if "100 INR" in err_str or body.get("status_code") == 999:
                display_msg = (
                    "Fast2SMS API route locked: Fast2SMS requires a one-time wallet recharge of ₹100 INR "
                    "or more at fast2sms.com to unlock programmatic API SMS dispatch. Once recharged, "
                    "SMS alerts will deliver automatically."
                )
            else:
                display_msg = f"Fast2SMS error: {err_msg}"
        else:
            display_msg = f"SMS accepted by Fast2SMS (id {(body.get('request_id') or '-')})"

        return result(
            ok=succeeded,
            provider=self.display_name,
            message=display_msg,
            data={"response": body, "phone": number},
            status_code=response.status_code,
            latency_ms=latency,
        )

    async def balance(self) -> dict:
        if self._is_demo_key():
            return result(
                ok=True,
                provider=self.display_name,
                message="Connected (demo Fast2SMS key). Replace SMS_API_KEY with a real key to deliver SMS.",
                data={"wallet": "DEMO", "sender_id": settings.sms_sender_id, "demo": True},
                status_code=200,
                latency_ms=0,
            )

        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get(self.wallet_endpoint, headers=self._headers())
            latency = int((time.perf_counter() - started) * 1000)
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            return result(
                ok=False, provider=self.display_name, message=f"Wallet check failed: {exc}"
            )

        if response.status_code == 200 and body.get("return"):
            wallet_val = body.get("wallet", 0)
            sms_cnt = body.get("sms_count", 0)
            return result(
                ok=True,
                provider=self.display_name,
                message=f"Connected to Fast2SMS. Wallet balance: Rs.{wallet_val} ({sms_cnt} SMS credits available).",
                data={"wallet": wallet_val, "sms_count": sms_cnt, "sender_id": settings.sms_sender_id},
                status_code=200,
                latency_ms=latency,
            )
        return result(
            ok=False,
            provider=self.display_name,
            message=f"Fast2SMS rejected the key: {body.get('message') or body}",
            status_code=response.status_code,
            latency_ms=latency,
        )


PROVIDERS: dict[str, SmsProvider] = {Fast2SmsProvider.name: Fast2SmsProvider()}


def get_provider() -> SmsProvider:
    return PROVIDERS.get(settings.sms_provider.strip().lower(), PROVIDERS["fast2sms"])


# --------------------------------------------------------------------------- #
# Public helpers
# --------------------------------------------------------------------------- #
async def _log(entry: dict) -> None:
    try:
        from ..database import SMS_LOGS, coll

        await coll(SMS_LOGS).insert_one(entry)
    except Exception as exc:  # noqa: BLE001 - logging must never break a send
        logger.warning("Could not persist SMS log: %s", exc)


async def send_sms(
    phone: str, message: str, purpose: str = "general", reference: str = ""
) -> dict:
    provider = get_provider()

    if not provider.configured():
        payload = not_configured(f"{provider.display_name} SMS", INSTRUCTION)
        payload["data"] = {
            "phone": normalise_phone(phone),
            "message": message,
            "delivery": "NOT_SENT",
        }
        await _log(
            {
                "phone": normalise_phone(phone),
                "message": message,
                "purpose": purpose,
                "reference": reference,
                "provider": provider.display_name,
                "status": "NOT_CONFIGURED",
                "detail": payload["message"],
                "created_at": utcnow_iso(),
            }
        )
        return payload

    outcome = await provider.send(phone, message)
    await _log(
        {
            "phone": normalise_phone(phone),
            "message": message,
            "purpose": purpose,
            "reference": reference,
            "provider": provider.display_name,
            "status": "SENT" if outcome["ok"] else "FAILED",
            "detail": outcome["message"],
            "created_at": utcnow_iso(),
        }
    )
    return outcome


async def test_connection() -> dict:
    provider = get_provider()
    if not provider.configured():
        return not_configured(f"{provider.display_name} SMS", INSTRUCTION)
    return await provider.balance()


def challan_message(
    challan_number: str,
    plate_number: str,
    violation_label: str,
    fine_amount: float,
    location: str,
    when: str,
    due_date: str,
    evidence_url: str = "",
    payment_url: str = "",
) -> str:
    lines = [
        f"RTO E-CHALLAN {challan_number}",
        f"Vehicle: {plate_number}",
        f"Violation: {violation_label}",
        f"Location: {location}",
        f"Date/Time: {when}",
        f"Fine: Rs.{int(fine_amount)}",
        f"Pay before {due_date}.",
    ]
    if evidence_url:
        lines.append(f"Evidence image: {evidence_url}")
    if payment_url:
        lines.append(f"Payment link: {payment_url}")
    return "\n".join(lines)
