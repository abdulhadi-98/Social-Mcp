"""Meta (Facebook / Instagram) Ads tools via the Marketing API (Graph API)."""

from typing import Any, Literal

import httpx

from .config import settings
from .safety import SafetyError, check_budget, check_meta_account, guarded_write

# Currencies Meta stores without minor units (budget 1000 JPY is sent as 1000, not 100000).
_ZERO_DECIMAL = {"CLP", "COP", "CRC", "HUF", "ISK", "IDR", "JPY", "KRW", "PYG", "TWD", "VND"}

# Fields an agent may change through meta_update_entity.
_UPDATABLE_FIELDS = {"name", "status", "daily_budget", "lifetime_budget", "bid_amount", "end_time", "start_time", "spend_cap"}


def _base() -> str:
    return f"https://graph.facebook.com/{settings.meta_api_version}"


def _request(method: str, path: str, params: dict | None = None, data: dict | None = None) -> dict[str, Any]:
    if not settings.meta_access_token:
        raise RuntimeError("Meta is not configured: set META_ACCESS_TOKEN.")
    params = {**(params or {}), "access_token": settings.meta_access_token}
    resp = httpx.request(method, f"{_base()}/{path.lstrip('/')}", params=params, data=data, timeout=60)
    body = resp.json()
    if "error" in body:
        err = body["error"]
        return {"error": err.get("message"), "type": err.get("type"), "code": err.get("code"),
                "user_message": err.get("error_user_msg")}
    return body


def _get_all(path: str, params: dict, limit: int) -> list[dict] | dict:
    items: list[dict] = []
    body = _request("GET", path, {**params, "limit": min(limit, 500)})
    while True:
        if "error" in body:
            return body
        items.extend(body.get("data", []))
        nxt = body.get("paging", {}).get("next")
        if not nxt or len(items) >= limit:
            return items[:limit]
        body = httpx.get(nxt, timeout=60).json()


def _to_minor_units(amount: float, currency: str) -> int:
    return int(round(amount)) if currency in _ZERO_DECIMAL else int(round(amount * 100))


def _currency_of(object_id: str) -> str:
    obj = _request("GET", object_id, {"fields": "account_id"})
    if "error" in obj:
        raise SafetyError(f"Could not look up {object_id}: {obj['error']}")
    acct = obj.get("account_id") or object_id.removeprefix("act_")
    check_meta_account(acct)
    return _request("GET", f"act_{acct}", {"fields": "currency"}).get("currency", "USD")


def list_ad_accounts(limit: int = 200) -> dict[str, Any]:
    """List every Meta ad account the token can access (including via Business Managers)."""
    res = _get_all("me/adaccounts", {"fields": "id,name,account_status,currency,timezone_name,amount_spent,business"}, limit)
    return res if isinstance(res, dict) else {"ad_accounts": res}


def list_entities(
    ad_account_id: str,
    entity_type: Literal["campaigns", "adsets", "ads"] = "campaigns",
    effective_status: list[str] | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """List campaigns, ad sets or ads in an ad account with their status and budgets.

    effective_status filter e.g. ["ACTIVE"] or ["ACTIVE","PAUSED"]. Budgets are returned in minor units (cents).
    """
    acct = check_meta_account(ad_account_id)
    fields = {
        "campaigns": "id,name,objective,status,effective_status,daily_budget,lifetime_budget,bid_strategy,created_time",
        "adsets": "id,name,campaign_id,status,effective_status,daily_budget,lifetime_budget,optimization_goal,billing_event,bid_amount,targeting",
        "ads": "id,name,adset_id,campaign_id,status,effective_status,creative{id,name,title,body,thumbnail_url}",
    }[entity_type]
    params: dict[str, Any] = {"fields": fields}
    if effective_status:
        params["effective_status"] = str(effective_status).replace("'", '"')
    res = _get_all(f"{acct}/{entity_type}", params, limit)
    return res if isinstance(res, dict) else {entity_type: res}


def get_insights(
    object_id: str,
    level: Literal["account", "campaign", "adset", "ad"] = "campaign",
    date_preset: str = "last_30d",
    since: str = "",
    until: str = "",
    fields: list[str] | None = None,
    breakdowns: list[str] | None = None,
    time_increment: str = "",
    limit: int = 200,
) -> dict[str, Any]:
    """Performance insights for an ad account (act_...), campaign, ad set or ad.

    date_preset: today, yesterday, last_7d, last_14d, last_30d, this_month, last_month, maximum (ignored if since/until given).
    breakdowns e.g. ["age","gender"], ["publisher_platform"], ["country"]. time_increment "1" for daily rows.
    """
    if object_id.startswith("act_"):
        check_meta_account(object_id)
    params: dict[str, Any] = {
        "level": level,
        "fields": ",".join(fields or [
            "campaign_id", "campaign_name", "adset_name", "ad_name", "spend", "impressions", "reach", "clicks",
            "ctr", "cpc", "cpm", "frequency", "actions", "action_values", "purchase_roas", "cost_per_action_type",
        ]),
    }
    if since and until:
        params["time_range"] = f'{{"since":"{since}","until":"{until}"}}'
    else:
        params["date_preset"] = date_preset
    if breakdowns:
        params["breakdowns"] = ",".join(breakdowns)
    if time_increment:
        params["time_increment"] = time_increment
    res = _get_all(f"{object_id}/insights", params, limit)
    return res if isinstance(res, dict) else {"rows": res}


def set_status(object_id: str, status: Literal["ACTIVE", "PAUSED"], confirm: bool = False) -> dict[str, Any]:
    """Pause or activate a Meta campaign, ad set or ad by id."""
    current = _request("GET", object_id, {"fields": "name,status,account_id"})
    if "error" in current:
        return current
    check_meta_account(current["account_id"])
    details = {"object_id": object_id, "name": current.get("name"), "current_status": current.get("status"), "new_status": status}
    return guarded_write("meta.set_status", details, confirm, lambda: _request("POST", object_id, data={"status": status}))


def set_budget(
    object_id: str,
    amount: float,
    budget_type: Literal["daily_budget", "lifetime_budget"] = "daily_budget",
    confirm: bool = False,
) -> dict[str, Any]:
    """Change the budget of a campaign (CBO) or ad set, in the account currency's major units (e.g. 50 = $50)."""
    if budget_type == "daily_budget":
        check_budget(amount)
    currency = _currency_of(object_id)
    current = _request("GET", object_id, {"fields": "name,daily_budget,lifetime_budget"})
    if "error" in current:
        return current
    minor = _to_minor_units(amount, currency)
    details = {
        "object_id": object_id,
        "name": current.get("name"),
        "currency": currency,
        f"current_{budget_type}_minor_units": current.get(budget_type),
        f"new_{budget_type}": amount,
        "new_minor_units": minor,
    }
    return guarded_write("meta.set_budget", details, confirm, lambda: _request("POST", object_id, data={budget_type: minor}))


def update_entity(object_id: str, fields: dict[str, Any], confirm: bool = False) -> dict[str, Any]:
    """Update allowed fields (name, status, bid_amount, start_time, end_time, spend_cap, budgets) on a campaign, ad set or ad.

    Budget, bid and spend_cap values must be in minor units (cents), as the Marketing API expects.
    Prefer meta_set_budget for budgets.
    """
    bad = set(fields) - _UPDATABLE_FIELDS
    if bad:
        raise SafetyError(f"Fields not allowed: {sorted(bad)}. Allowed: {sorted(_UPDATABLE_FIELDS)}")
    current = _request("GET", object_id, {"fields": "name,account_id"})
    if "error" in current:
        return current
    check_meta_account(current["account_id"])
    return guarded_write(
        "meta.update_entity",
        {"object_id": object_id, "name": current.get("name"), "changes": fields},
        confirm,
        lambda: _request("POST", object_id, data={k: str(v) for k, v in fields.items()}),
    )


def create_campaign(
    ad_account_id: str,
    name: str,
    objective: Literal[
        "OUTCOME_AWARENESS", "OUTCOME_TRAFFIC", "OUTCOME_ENGAGEMENT",
        "OUTCOME_LEADS", "OUTCOME_APP_PROMOTION", "OUTCOME_SALES",
    ],
    daily_budget: float | None = None,
    special_ad_categories: list[str] | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Create a new campaign. It is always created PAUSED so nothing spends until you activate it.

    daily_budget (major units) enables campaign budget optimization; omit it to set budgets on ad sets instead.
    special_ad_categories: [] or e.g. ["HOUSING"], ["EMPLOYMENT"], ["FINANCIAL_PRODUCTS_SERVICES"].
    """
    acct = check_meta_account(ad_account_id)
    payload: dict[str, Any] = {
        "name": name,
        "objective": objective,
        "status": "PAUSED",
        "special_ad_categories": str(special_ad_categories or []).replace("'", '"'),
    }
    if daily_budget is not None:
        check_budget(daily_budget)
        currency = _request("GET", acct, {"fields": "currency"}).get("currency", "USD")
        payload["daily_budget"] = _to_minor_units(daily_budget, currency)
        payload["bid_strategy"] = "LOWEST_COST_WITHOUT_CAP"
    else:
        payload["is_adset_budget_sharing_enabled"] = "false"
    return guarded_write("meta.create_campaign", {"ad_account": acct, **payload}, confirm,
                         lambda: _request("POST", f"{acct}/campaigns", data=payload))
