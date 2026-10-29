"""Guardrails shared by every tool that changes something in an ad or analytics account.

Every write tool takes ``confirm``. With ``confirm=False`` (the default) the tool only
returns a preview of what it would do, so the agent can show it to you first. Writes
are also blocked entirely unless ALLOW_WRITES=true, and every executed write is
appended to an audit log.
"""

import json
import time
from typing import Any

from .config import settings


class SafetyError(Exception):
    pass


def check_google_customer(customer_id: str) -> str:
    cid = customer_id.replace("-", "").strip()
    allowed = settings.allowed_google_ads_customers
    if allowed and cid not in allowed:
        raise SafetyError(f"Google Ads customer {cid} is not in ALLOWED_GOOGLE_ADS_CUSTOMERS")
    return cid


def check_meta_account(ad_account_id: str) -> str:
    acct = ad_account_id if ad_account_id.startswith("act_") else f"act_{ad_account_id}"
    allowed = settings.allowed_meta_ad_accounts
    if allowed and acct not in allowed and acct.removeprefix("act_") not in allowed:
        raise SafetyError(f"Meta ad account {acct} is not in ALLOWED_META_AD_ACCOUNTS")
    return acct


def check_budget(amount: float) -> None:
    if amount <= 0:
        raise SafetyError("Budget must be greater than 0")
    if amount > settings.max_daily_budget:
        raise SafetyError(
            f"Daily budget {amount} exceeds MAX_DAILY_BUDGET={settings.max_daily_budget}. "
            "Raise the limit in the server config if this is intended."
        )


def guarded_write(action: str, details: dict[str, Any], confirm: bool, execute) -> dict[str, Any]:
    """Preview the write unless confirmed; otherwise run ``execute()`` and audit it."""
    if not confirm:
        return {
            "dry_run": True,
            "action": action,
            "details": details,
            "next_step": "Show this to the user. If they approve, call again with confirm=true.",
        }
    if not settings.allow_writes:
        raise SafetyError("Writes are disabled on this server (set ALLOW_WRITES=true to enable).")
    result = execute()
    with open(settings.audit_log_path, "a") as f:
        f.write(json.dumps({"ts": time.time(), "action": action, "details": details, "result": result}, default=str) + "\n")
    return {"dry_run": False, "action": action, "details": details, "result": result}
