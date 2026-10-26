"""Public challan notice, evidence image, and payment link. No login required."""

from __future__ import annotations

import html

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from ..config import EVIDENCE_DIR
from ..constants import CHALLAN_PAID, CHALLAN_PENDING
from ..database import CHALLANS, PAYMENTS, VEHICLES, coll
from ..utils import utcnow_iso

router = APIRouter(tags=["Public notice"])


async def _challan(challan_number: str) -> dict:
    document = await coll(CHALLANS).find_one({"challan_number": challan_number})
    if not document:
        raise HTTPException(status_code=404, detail="Challan not found")
    return document


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{html.escape(title)}</title>"
        "<style>body{font-family:Segoe UI,sans-serif;margin:24px;color:#14213d}"
        "img{max-width:100%;border-radius:8px}a.btn,button{display:inline-block;"
        "background:#1d4e89;color:#fff;padding:12px 18px;border:0;border-radius:8px;"
        "text-decoration:none;font-size:16px}</style></head><body>"
        f"{body}</body></html>"
    )


@router.get("/notice/{challan_number}", response_class=HTMLResponse)
async def notice(challan_number: str) -> HTMLResponse:
    challan = await _challan(challan_number)
    fine = int(float(challan.get("fine_amount") or 0))
    body = (
        f"<h1>E-challan {html.escape(challan_number)}</h1>"
        f"<p>Vehicle: {html.escape(str(challan.get('plate_number') or ''))}<br>"
        f"Owner: {html.escape(str(challan.get('owner_name') or ''))}<br>"
        f"Violation: {html.escape(str(challan.get('violation_label') or ''))}<br>"
        f"Location: {html.escape(str(challan.get('location') or ''))}<br>"
        f"Fine: Rs.{fine}<br>"
        f"Status: {html.escape(str(challan.get('status') or ''))}</p>"
        f"<img src='/notice/{html.escape(challan_number)}/evidence' alt='Evidence'>"
        f"<p><a class='btn' href='/pay/{html.escape(challan_number)}'>Pay fine</a></p>"
    )
    return _page(f"Challan {challan_number}", body)


@router.get("/notice/{challan_number}/evidence")
async def notice_evidence(challan_number: str) -> FileResponse:
    challan = await _challan(challan_number)
    filename = str(challan.get("evidence_image") or "")
    path = (EVIDENCE_DIR / filename).resolve()
    if not filename or not path.is_file() or EVIDENCE_DIR.resolve() not in path.parents:
        raise HTTPException(status_code=404, detail="Evidence image not found")
    return FileResponse(path, media_type="image/jpeg")


@router.get("/pay/{challan_number}", response_class=HTMLResponse)
async def pay_page(challan_number: str) -> HTMLResponse:
    challan = await _challan(challan_number)
    fine = int(float(challan.get("fine_amount") or 0))
    if challan.get("status") == CHALLAN_PAID:
        body = (
            f"<h1>Paid</h1><p>Challan {html.escape(challan_number)} "
            f"for {html.escape(str(challan.get('plate_number') or ''))} is already paid.</p>"
        )
        return _page("Payment received", body)
    body = (
        f"<h1>Pay e-challan {html.escape(challan_number)}</h1>"
        f"<p>Vehicle: {html.escape(str(challan.get('plate_number') or ''))}<br>"
        f"Owner: {html.escape(str(challan.get('owner_name') or ''))}<br>"
        f"Amount: Rs.{fine}</p>"
        f"<form method='post' action='/pay/{html.escape(challan_number)}'>"
        "<button type='submit'>Pay fine</button></form>"
    )
    return _page(f"Pay {challan_number}", body)


@router.post("/pay/{challan_number}", response_class=HTMLResponse)
async def pay_submit(challan_number: str) -> HTMLResponse:
    challan = await _challan(challan_number)
    if challan.get("status") == CHALLAN_PAID:
        return _page("Payment received", "<h1>This challan is already paid.</h1>")
    if challan.get("status") != CHALLAN_PENDING:
        raise HTTPException(status_code=409, detail="This challan cannot be paid")
    amount = float(challan.get("fine_amount") or 0)
    await coll(PAYMENTS).insert_one(
        {
            "challan_id": str(challan.get("_id")),
            "challan_number": challan_number,
            "plate_number": challan.get("plate_number", ""),
            "amount": amount,
            "gateway": "owner-link",
            "mode": "LINK",
            "status": "COLLECTED",
            "detail": "Paid from the SMS payment link",
            "created_by": "OWNER",
            "created_at": utcnow_iso(),
        }
    )
    await coll(CHALLANS).update_one(
        {"_id": challan["_id"]},
        {
            "$set": {
                "status": CHALLAN_PAID,
                "amount_paid": amount,
                "updated_at": utcnow_iso(),
                "payment": {"method": "owner-link", "paid_at": utcnow_iso()},
            }
        },
    )
    plate = challan.get("plate_number")
    if plate:
        await coll(VEHICLES).update_one(
            {"plate_number": plate},
            {"$inc": {"total_paid": amount}},
        )
    return _page(
        "Payment received",
        f"<h1>Payment received</h1><p>Rs.{int(amount)} recorded for "
        f"{html.escape(challan_number)}.</p>",
    )
