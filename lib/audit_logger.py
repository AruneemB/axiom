"""
Security audit logging and webhook IP verification for the Telegram bot.

log_security_event is intentionally non-fatal — a logging failure must
never interrupt the request path.
"""

import ipaddress
from typing import Optional

# Telegram's published webhook source ranges (updated 2024).
# Reference: https://core.telegram.org/bots/webhooks#the-short-version
TELEGRAM_CIDR_RANGES = [
    "149.154.160.0/20",
    "91.108.4.0/22",
]

_TELEGRAM_NETWORKS = [
    ipaddress.ip_network(cidr, strict=False) for cidr in TELEGRAM_CIDR_RANGES
]

# Event type constants — use these instead of raw strings in callers.
EVT_BLOCKED_UNKNOWN   = "blocked_unknown_user"
EVT_RATE_LIMITED      = "rate_limited"
EVT_VALIDATION_FAILED = "validation_failed"
EVT_AUTO_SUSPENDED    = "auto_suspended"
EVT_BURST_BLOCKED     = "burst_blocked"
EVT_IP_REJECTED       = "ip_rejected"


def is_telegram_ip(ip_str: str) -> bool:
    """Return True if ip_str falls within Telegram's published webhook ranges."""
    try:
        addr = ipaddress.ip_address(ip_str)
        return any(addr in net for net in _TELEGRAM_NETWORKS)
    except ValueError:
        return False


def log_security_event(
    conn,
    event_type: str,
    user_id: Optional[int] = None,
    details: Optional[str] = None,
    ip_addr: Optional[str] = None,
) -> None:
    """
    Append a security event to security_audit_log.
    Silently swallows all exceptions so a DB failure never crashes the handler.
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO security_audit_log (user_id, event_type, details, ip_addr)
                VALUES (%s, %s, %s, %s)
                """,
                (user_id, event_type, details, ip_addr),
            )
        conn.commit()
    except Exception:
        pass
