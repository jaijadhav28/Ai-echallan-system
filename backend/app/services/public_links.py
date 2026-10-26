"""Links sent to a vehicle owner with a challan SMS."""

from __future__ import annotations

import socket


def site_base_url() -> str:
    """Address the owner's phone can open on the same network."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        address = sock.getsockname()[0]
        sock.close()
        if address and not address.startswith("127."):
            return f"http://{address}:8000"
    except OSError:
        pass
    return "http://127.0.0.1:8000"


def evidence_url(challan_number: str) -> str:
    return f"{site_base_url()}/notice/{challan_number}/evidence"


def payment_url(challan_number: str) -> str:
    return f"{site_base_url()}/pay/{challan_number}"
