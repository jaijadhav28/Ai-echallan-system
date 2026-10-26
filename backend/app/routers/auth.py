"""Authentication: password login, OTP login, forgot/reset password."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status

from ..config import settings
from ..constants import ROLE_LABELS
from ..database import AUDIT, OTPS, USERS, coll
from ..deps import get_current_user
from ..schemas import (
    ChangePasswordBody,
    ForgotPasswordBody,
    LoginRequest,
    OtpRequestBody,
    OtpVerifyBody,
    RegisterBody,
    RegisterOtpBody,
    ResetPasswordBody,
    TokenResponse,
)
from ..security import (
    create_access_token,
    create_reset_token,
    decode_reset_token,
    hash_password,
    verify_password,
)
from ..services import sms_service
from ..services.sms_service import normalise_phone
from ..utils import iso, random_digits, serialize, utcnow, utcnow_iso

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

OTP_VALIDITY_MINUTES = 5
MAX_OTP_ATTEMPTS = 5


def _strong_password(password: str) -> str | None:
    """Return an error message if the password fails strength rules, else None."""
    import re

    if len(password) < 8:
        return "Password must be at least 8 characters"
    if not re.search(r"[a-z]", password):
        return "Password needs a lowercase letter"
    if not re.search(r"[A-Z]", password):
        return "Password needs an uppercase letter"
    if not re.search(r"[0-9]", password):
        return "Password needs a number"
    if not re.search(r"[@$!%*?&#]", password):
        return "Password needs a special character (@$!%*?&#)"
    return None


def _valid_batch_id(batch_id: str) -> bool:
    import re

    return bool(re.fullmatch(r"[A-Za-z0-9_\-]{3,30}", batch_id))


def public_user(document: dict) -> dict:
    user = serialize(document) or {}
    user.pop("password_hash", None)
    user["role_label"] = ROLE_LABELS.get(user.get("role", ""), user.get("role", ""))
    return user


async def _audit(action: str, actor: str, detail: str = "", meta: dict | None = None) -> None:
    await coll(AUDIT).insert_one(
        {
            "action": action,
            "actor": actor,
            "detail": detail,
            "meta": meta or {},
            "created_at": utcnow_iso(),
        }
    )


def _issue(document: dict) -> TokenResponse:
    token, expires_in = create_access_token(
        subject=document["user_id"],
        role=document.get("role", "officer"),
        name=document.get("name", ""),
    )
    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        user=public_user(document),
    )


# --------------------------------------------------------------------------- #
@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest) -> TokenResponse:
    document = await coll(USERS).find_one({"user_id": body.user_id.strip()})
    if not document or not verify_password(body.password, document.get("password_hash", "")):
        await _audit("LOGIN_FAILED", body.user_id, "Invalid user id or password")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid User ID or Password",
        )
    if not document.get("active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated. Contact the administrator.",
        )
    if (body.role or "").strip():
        if body.role.strip() != document.get("role"):
            await _audit(
                "LOGIN_FAILED",
                document["user_id"],
                "Role does not match this User ID and password",
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "The selected role is not compatible with this User ID and password. "
                    "Select the correct role to continue."
                ),
            )

    await coll(USERS).update_one(
        {"_id": document["_id"]},
        {"$set": {"last_login_at": utcnow_iso()}, "$inc": {"login_count": 1}},
    )
    await _audit("LOGIN", document["user_id"], "Password login")
    return _issue(document)


# --------------------------------------------------------------------------- #
@router.post("/otp/request")
async def request_otp(body: OtpRequestBody) -> dict:
    document = await coll(USERS).find_one({"user_id": body.user_id.strip()})
    if not document:
        raise HTTPException(status_code=404, detail="No account found for this User ID")

    phone = (document.get("phone") or "").strip()
    if not phone:
        raise HTTPException(
            status_code=400,
            detail="No mobile number is registered for this account. Use password login.",
        )

    code = random_digits(6)
    await coll(OTPS).delete_many({"user_id": document["user_id"]})
    await coll(OTPS).insert_one(
        {
            "user_id": document["user_id"],
            "code": code,
            "attempts": 0,
            "created_at": utcnow_iso(),
            "expires_at": iso(utcnow() + timedelta(minutes=OTP_VALIDITY_MINUTES)),
        }
    )

    outcome = await sms_service.send_sms(
        phone,
        f"Your RTO E-Challan login OTP is {code}. Valid for {OTP_VALIDITY_MINUTES} minutes.",
        purpose="login_otp",
        reference=document["user_id"],
    )
    await _audit("OTP_REQUESTED", document["user_id"], outcome["message"])

    response = {
        "sent": outcome["ok"],
        "sms_configured": outcome["configured"],
        "message": (
            f"OTP sent to the mobile number ending {phone[-4:]}"
            if outcome["ok"]
            else outcome["message"]
        ),
        "masked_phone": f"{'*' * max(len(phone) - 4, 0)}{phone[-4:]}",
        "valid_for_minutes": OTP_VALIDITY_MINUTES,
    }
    return response


@router.post("/otp/verify", response_model=TokenResponse)
async def verify_otp(body: OtpVerifyBody) -> TokenResponse:
    record = await coll(OTPS).find_one({"user_id": body.user_id.strip()})
    if not record:
        raise HTTPException(status_code=400, detail="Request an OTP first")
    if record.get("expires_at", "") < utcnow_iso():
        await coll(OTPS).delete_many({"user_id": body.user_id.strip()})
        raise HTTPException(status_code=400, detail="This OTP has expired. Request a new one.")
    if int(record.get("attempts") or 0) >= MAX_OTP_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many attempts. Request a new OTP.")

    if body.otp.strip() != record.get("code"):
        await coll(OTPS).update_one({"_id": record["_id"]}, {"$inc": {"attempts": 1}})
        raise HTTPException(status_code=401, detail="Incorrect OTP")

    document = await coll(USERS).find_one({"user_id": body.user_id.strip()})
    if not document or not document.get("active", True):
        raise HTTPException(status_code=403, detail="Account unavailable")

    await coll(OTPS).delete_many({"user_id": body.user_id.strip()})
    await coll(USERS).update_one(
        {"_id": document["_id"]},
        {"$set": {"last_login_at": utcnow_iso()}, "$inc": {"login_count": 1}},
    )
    await _audit("LOGIN", document["user_id"], "OTP login")
    return _issue(document)


# --------------------------------------------------------------------------- #
@router.post("/register/otp")
async def register_request_otp(body: RegisterOtpBody) -> dict:
    """Send a mobile OTP used only for creating a new account."""
    phone = normalise_phone(body.phone)
    if len(phone) != 10:
        raise HTTPException(status_code=400, detail="Enter a valid 10-digit mobile number")

    existing = await coll(USERS).find_one({"phone": phone})
    if existing:
        raise HTTPException(
            status_code=409,
            detail="This mobile number is already linked to an account. Please log in.",
        )

    code = random_digits(6)
    await coll(OTPS).delete_many({"phone": phone, "purpose": "register"})
    await coll(OTPS).insert_one(
        {
            "phone": phone,
            "purpose": "register",
            "code": code,
            "attempts": 0,
            "created_at": utcnow_iso(),
            "expires_at": iso(utcnow() + timedelta(minutes=OTP_VALIDITY_MINUTES)),
        }
    )

    outcome = await sms_service.send_sms(
        phone,
        f"Your RTO E-Challan registration OTP is {code}. Valid for {OTP_VALIDITY_MINUTES} minutes.",
        purpose="register_otp",
        reference=phone,
    )

    response = {
        "sent": outcome["ok"],
        "sms_configured": outcome["configured"],
        "message": (
            f"OTP sent to the mobile number ending {phone[-4:]}"
            if outcome["ok"]
            else outcome["message"]
        ),
        "masked_phone": f"{'*' * 6}{phone[-4:]}",
        "valid_for_minutes": OTP_VALIDITY_MINUTES,
    }
    return response


@router.post("/register", response_model=TokenResponse)
async def register_account(body: RegisterBody) -> TokenResponse:
    """Create a new officer account after mobile OTP verification."""
    batch_id = body.batch_id.strip().upper()
    name = body.name.strip()
    phone = normalise_phone(body.phone)
    otp = body.otp.strip()

    if not _valid_batch_id(batch_id):
        raise HTTPException(
            status_code=400,
            detail="Officer Batch ID must be 3–30 letters, numbers, _ or -",
        )
    if len(phone) != 10:
        raise HTTPException(status_code=400, detail="Enter a valid 10-digit mobile number")

    strength_error = _strong_password(body.password)
    if strength_error:
        raise HTTPException(status_code=400, detail=strength_error)

    if await coll(USERS).find_one({"user_id": batch_id}):
        raise HTTPException(
            status_code=409,
            detail=f"Officer Batch ID '{batch_id}' is already registered",
        )
    if await coll(USERS).find_one({"phone": phone}):
        raise HTTPException(
            status_code=409,
            detail="This mobile number is already linked to an account",
        )

    record = await coll(OTPS).find_one({"phone": phone, "purpose": "register"})
    if not record:
        raise HTTPException(status_code=400, detail="Request a mobile OTP first")
    if record.get("expires_at", "") < utcnow_iso():
        await coll(OTPS).delete_many({"phone": phone, "purpose": "register"})
        raise HTTPException(status_code=400, detail="This OTP has expired. Request a new one.")
    if int(record.get("attempts") or 0) >= MAX_OTP_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many attempts. Request a new OTP.")
    if otp != record.get("code"):
        await coll(OTPS).update_one({"_id": record["_id"]}, {"$inc": {"attempts": 1}})
        raise HTTPException(status_code=401, detail="Incorrect OTP")

    document = {
        "user_id": batch_id,
        "name": name,
        "role": "officer",
        "designation": "Traffic Officer",
        "phone": phone,
        "email": "",
        "station": "",
        "active": True,
        "password_hash": hash_password(body.password),
        "is_demo": False,
        "login_count": 1,
        "last_login_at": utcnow_iso(),
        "created_at": utcnow_iso(),
        "created_by": "self-register",
        "updated_at": utcnow_iso(),
    }
    inserted = await coll(USERS).insert_one(document)
    document["_id"] = inserted.inserted_id
    await coll(OTPS).delete_many({"phone": phone, "purpose": "register"})
    await _audit("USER_REGISTERED", batch_id, f"Self-registered with phone ending {phone[-4:]}")
    return _issue(document)


# --------------------------------------------------------------------------- #
@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordBody) -> dict:
    document = await coll(USERS).find_one({"user_id": body.user_id.strip()})
    if not document:
        # Do not disclose which accounts exist.
        return {
            "requested": True,
            "message": "If the User ID exists, a reset link has been sent to the registered mobile number.",
        }

    token = create_reset_token(document["user_id"])
    phone = (document.get("phone") or "").strip()
    outcome = None
    if phone:
        outcome = await sms_service.send_sms(
            phone,
            "RTO E-Challan: a password reset was requested for your account. "
            "Use the reset code shown in the portal to set a new password.",
            purpose="password_reset",
            reference=document["user_id"],
        )
    await _audit("PASSWORD_RESET_REQUESTED", document["user_id"])

    response = {
        "requested": True,
        "message": "If the User ID exists, a reset link has been sent to the registered mobile number.",
        "sms_configured": bool(outcome and outcome["configured"]),
    }
    if settings.app_env == "development":
        response["reset_token"] = token
        response["demo_note"] = (
            "Development build: the reset token is returned directly so the flow can "
            "be demonstrated without an SMS gateway."
        )
    return response


@router.post("/reset-password")
async def reset_password(body: ResetPasswordBody) -> dict:
    user_id = decode_reset_token(body.token)
    if not user_id:
        raise HTTPException(status_code=400, detail="This reset link is invalid or expired")

    document = await coll(USERS).find_one({"user_id": user_id})
    if not document:
        raise HTTPException(status_code=404, detail="Account not found")

    await coll(USERS).update_one(
        {"_id": document["_id"]},
        {
            "$set": {
                "password_hash": hash_password(body.new_password),
                "password_changed_at": utcnow_iso(),
            }
        },
    )
    await _audit("PASSWORD_RESET", user_id)
    return {"updated": True, "message": "Password updated. You can log in now."}


@router.post("/change-password")
async def change_password(
    body: ChangePasswordBody, user: dict = Depends(get_current_user)
) -> dict:
    document = await coll(USERS).find_one({"user_id": user["user_id"]})
    if not document or not verify_password(
        body.current_password, document.get("password_hash", "")
    ):
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    await coll(USERS).update_one(
        {"_id": document["_id"]},
        {
            "$set": {
                "password_hash": hash_password(body.new_password),
                "password_changed_at": utcnow_iso(),
            }
        },
    )
    await _audit("PASSWORD_CHANGED", user["user_id"])
    return {"updated": True, "message": "Password changed successfully"}


# --------------------------------------------------------------------------- #
@router.get("/me")
async def me(user: dict = Depends(get_current_user)) -> dict:
    user["role_label"] = ROLE_LABELS.get(user.get("role", ""), user.get("role", ""))
    return user


@router.get("/demo-credentials")
async def demo_credentials() -> dict:
    """Convenience for the login screen during development only."""
    if settings.app_env != "development":
        return {"available": False, "accounts": []}
    documents = await coll(USERS).find({"is_demo": True}).to_list(10)
    return {
        "available": True,
        "note": "Seeded demo accounts (development build only).",
        "accounts": [
            {
                "user_id": document.get("user_id"),
                "password": document.get("demo_password", ""),
                "role": document.get("role"),
                "role_label": ROLE_LABELS.get(document.get("role", ""), ""),
                "name": document.get("name"),
            }
            for document in documents
        ],
    }
