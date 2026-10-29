"""Google Ads tools: account discovery, GAQL reporting and common campaign changes."""

from functools import lru_cache
from typing import Any, Literal

from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException
from google.api_core import protobuf_helpers
from google.protobuf.json_format import MessageToDict

from .config import settings
from .safety import check_budget, check_google_customer, guarded_write


@lru_cache(maxsize=8)
def _client(login_customer_id: str = "") -> GoogleAdsClient:
    if not (settings.google_ads_developer_token and settings.google_refresh_token):
        raise RuntimeError("Google Ads is not configured: set GOOGLE_ADS_DEVELOPER_TOKEN and the GOOGLE_* OAuth values.")
    config = {
        "developer_token": settings.google_ads_developer_token,
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "refresh_token": settings.google_refresh_token,
        "use_proto_plus": True,
    }
    login = (login_customer_id or settings.google_ads_login_customer_id).replace("-", "")
    if login:
        config["login_customer_id"] = login
    return GoogleAdsClient.load_from_dict(config)


def _error(ex: GoogleAdsException) -> dict[str, Any]:
    return {
        "error": "GoogleAdsException",
        "request_id": ex.request_id,
        "messages": [e.message for e in ex.failure.errors],
    }


def _search(customer_id: str, query: str, login_customer_id: str = "", limit: int = 1000) -> list[dict]:
    service = _client(login_customer_id).get_service("GoogleAdsService")
    rows: list[dict] = []
    for batch in service.search_stream(customer_id=customer_id, query=query):
        for row in batch.results:
            rows.append(MessageToDict(row._pb, preserving_proto_field_name=True))
            if len(rows) >= limit:
                return rows
    return rows


def list_accounts(login_customer_id: str = "") -> dict[str, Any]:
    """List every Google Ads account the authenticated user can access, with name, currency and whether it is a manager (MCC)."""
    try:
        client = _client(login_customer_id)
        names = client.get_service("CustomerService").list_accessible_customers().resource_names
        accounts = []
        for rn in names:
            cid = rn.split("/")[-1]
            try:
                info = _search(
                    cid,
                    "SELECT customer.id, customer.descriptive_name, customer.currency_code, "
                    "customer.time_zone, customer.manager, customer.status FROM customer",
                    login_customer_id,
                )
                accounts.append(info[0]["customer"] if info else {"id": cid})
            except GoogleAdsException as ex:
                accounts.append({"id": cid, "note": _error(ex)["messages"]})
        return {"accounts": accounts}
    except GoogleAdsException as ex:
        return _error(ex)


def list_client_accounts(manager_customer_id: str) -> dict[str, Any]:
    """List the client accounts under a manager (MCC) account."""
    mcc = check_google_customer(manager_customer_id)
    try:
        rows = _search(
            mcc,
            "SELECT customer_client.id, customer_client.descriptive_name, customer_client.manager, "
            "customer_client.level, customer_client.currency_code, customer_client.status "
            "FROM customer_client WHERE customer_client.level <= 2",
            login_customer_id=mcc,
        )
        return {"clients": [r["customer_client"] for r in rows]}
    except GoogleAdsException as ex:
        return _error(ex)


def query(customer_id: str, gaql: str, login_customer_id: str = "", limit: int = 500) -> dict[str, Any]:
    """Run any read-only Google Ads Query Language (GAQL) query.

    Example: SELECT campaign.id, campaign.name, metrics.clicks, metrics.cost_micros
             FROM campaign WHERE segments.date DURING LAST_7_DAYS
    Costs are in micros (divide by 1,000,000).
    """
    cid = check_google_customer(customer_id)
    try:
        rows = _search(cid, gaql, login_customer_id, limit)
        return {"row_count": len(rows), "rows": rows}
    except GoogleAdsException as ex:
        return _error(ex)


def campaign_performance(
    customer_id: str, date_range: str = "LAST_30_DAYS", login_customer_id: str = "", include_paused: bool = True
) -> dict[str, Any]:
    """Campaign-level spend, clicks, impressions, conversions, CPA and ROAS for a date range.

    date_range is a GAQL predefined range, e.g. TODAY, YESTERDAY, LAST_7_DAYS, LAST_30_DAYS, THIS_MONTH, LAST_MONTH.
    """
    cid = check_google_customer(customer_id)
    status_filter = "AND campaign.status != 'REMOVED'" if include_paused else "AND campaign.status = 'ENABLED'"
    gaql = f"""
        SELECT campaign.id, campaign.name, campaign.status, campaign.advertising_channel_type,
               campaign_budget.amount_micros, metrics.impressions, metrics.clicks, metrics.cost_micros,
               metrics.conversions, metrics.conversions_value, metrics.ctr, metrics.average_cpc
        FROM campaign
        WHERE segments.date DURING {date_range} {status_filter}
        ORDER BY metrics.cost_micros DESC"""
    try:
        rows = _search(cid, gaql, login_customer_id)
    except GoogleAdsException as ex:
        return _error(ex)
    out = []
    for r in rows:
        m = r.get("metrics", {})
        cost = int(m.get("cost_micros", 0)) / 1e6
        conv = float(m.get("conversions", 0))
        value = float(m.get("conversions_value", 0))
        out.append({
            "campaign_id": r["campaign"]["id"],
            "name": r["campaign"]["name"],
            "status": r["campaign"]["status"],
            "channel": r["campaign"].get("advertising_channel_type"),
            "daily_budget": int(r.get("campaign_budget", {}).get("amount_micros", 0)) / 1e6,
            "impressions": int(m.get("impressions", 0)),
            "clicks": int(m.get("clicks", 0)),
            "cost": round(cost, 2),
            "conversions": round(conv, 2),
            "conversion_value": round(value, 2),
            "cpa": round(cost / conv, 2) if conv else None,
            "roas": round(value / cost, 2) if cost else None,
        })
    return {"date_range": date_range, "campaigns": out}


_STATUS_TARGETS = {
    "campaign": ("CampaignService", "mutate_campaigns", "CampaignStatusEnum", "campaign_path"),
    "ad_group": ("AdGroupService", "mutate_ad_groups", "AdGroupStatusEnum", "ad_group_path"),
    "ad": ("AdGroupAdService", "mutate_ad_group_ads", "AdGroupAdStatusEnum", "ad_group_ad_path"),
    "keyword": ("AdGroupCriterionService", "mutate_ad_group_criteria", "AdGroupCriterionStatusEnum", "ad_group_criterion_path"),
}


def set_status(
    customer_id: str,
    level: Literal["campaign", "ad_group", "ad", "keyword"],
    entity_id: str,
    status: Literal["ENABLED", "PAUSED"],
    confirm: bool = False,
    login_customer_id: str = "",
) -> dict[str, Any]:
    """Pause or enable a campaign, ad group, ad or keyword.

    entity_id: the campaign/ad group id; for ads and keywords use "<ad_group_id>~<ad_id or criterion_id>".
    """
    cid = check_google_customer(customer_id)
    service_name, mutate_fn, enum_name, path_fn = _STATUS_TARGETS[level]

    def execute():
        client = _client(login_customer_id)
        service = client.get_service(service_name)
        op = client.get_type(f"{service_name.removesuffix('Service')}Operation")
        obj = op.update
        ids = entity_id.split("~")
        obj.resource_name = getattr(service, path_fn)(cid, *ids)
        obj.status = getattr(client.enums, enum_name)[status]
        client.copy_from(op.update_mask, protobuf_helpers.field_mask(None, obj._pb))
        resp = getattr(service, mutate_fn)(customer_id=cid, operations=[op])
        return {"resource_name": resp.results[0].resource_name}

    try:
        return guarded_write(
            "google_ads.set_status",
            {"customer_id": cid, "level": level, "entity_id": entity_id, "new_status": status},
            confirm,
            execute,
        )
    except GoogleAdsException as ex:
        return _error(ex)


def set_campaign_budget(
    customer_id: str, campaign_id: str, daily_budget: float, confirm: bool = False, login_customer_id: str = ""
) -> dict[str, Any]:
    """Change a campaign's daily budget (in the account currency, e.g. 50 = $50/day)."""
    cid = check_google_customer(customer_id)
    check_budget(daily_budget)
    try:
        rows = _search(
            cid,
            "SELECT campaign.name, campaign_budget.resource_name, campaign_budget.amount_micros, "
            f"campaign_budget.explicitly_shared FROM campaign WHERE campaign.id = {int(campaign_id)}",
            login_customer_id,
        )
    except GoogleAdsException as ex:
        return _error(ex)
    if not rows:
        return {"error": f"Campaign {campaign_id} not found in {cid}"}
    budget = rows[0]["campaign_budget"]
    details = {
        "customer_id": cid,
        "campaign_id": campaign_id,
        "campaign_name": rows[0]["campaign"]["name"],
        "current_daily_budget": int(budget.get("amount_micros", 0)) / 1e6,
        "new_daily_budget": daily_budget,
        "shared_budget_warning": bool(budget.get("explicitly_shared")),
    }

    def execute():
        client = _client(login_customer_id)
        service = client.get_service("CampaignBudgetService")
        op = client.get_type("CampaignBudgetOperation")
        op.update.resource_name = budget["resource_name"]
        op.update.amount_micros = int(round(daily_budget * 1_000_000))
        client.copy_from(op.update_mask, protobuf_helpers.field_mask(None, op.update._pb))
        return {"resource_name": service.mutate_campaign_budgets(customer_id=cid, operations=[op]).results[0].resource_name}

    try:
        return guarded_write("google_ads.set_campaign_budget", details, confirm, execute)
    except GoogleAdsException as ex:
        return _error(ex)


def set_ad_group_cpc_bid(
    customer_id: str, ad_group_id: str, cpc_bid: float, confirm: bool = False, login_customer_id: str = ""
) -> dict[str, Any]:
    """Set an ad group's max CPC bid (account currency). Only applies to manual CPC bidding."""
    cid = check_google_customer(customer_id)

    def execute():
        client = _client(login_customer_id)
        service = client.get_service("AdGroupService")
        op = client.get_type("AdGroupOperation")
        op.update.resource_name = service.ad_group_path(cid, ad_group_id)
        op.update.cpc_bid_micros = int(round(cpc_bid * 1_000_000))
        client.copy_from(op.update_mask, protobuf_helpers.field_mask(None, op.update._pb))
        return {"resource_name": service.mutate_ad_groups(customer_id=cid, operations=[op]).results[0].resource_name}

    try:
        return guarded_write(
            "google_ads.set_ad_group_cpc_bid",
            {"customer_id": cid, "ad_group_id": ad_group_id, "new_cpc_bid": cpc_bid},
            confirm,
            execute,
        )
    except GoogleAdsException as ex:
        return _error(ex)


def add_negative_keywords(
    customer_id: str,
    campaign_id: str,
    keywords: list[str],
    match_type: Literal["EXACT", "PHRASE", "BROAD"] = "PHRASE",
    confirm: bool = False,
    login_customer_id: str = "",
) -> dict[str, Any]:
    """Add campaign-level negative keywords (e.g. wasteful search terms found in a search-term report)."""
    cid = check_google_customer(customer_id)

    def execute():
        client = _client(login_customer_id)
        service = client.get_service("CampaignCriterionService")
        campaign_rn = client.get_service("CampaignService").campaign_path(cid, campaign_id)
        ops = []
        for kw in keywords:
            op = client.get_type("CampaignCriterionOperation")
            op.create.campaign = campaign_rn
            op.create.negative = True
            op.create.keyword.text = kw
            op.create.keyword.match_type = client.enums.KeywordMatchTypeEnum[match_type]
            ops.append(op)
        resp = service.mutate_campaign_criteria(customer_id=cid, operations=ops)
        return {"created": [r.resource_name for r in resp.results]}

    try:
        return guarded_write(
            "google_ads.add_negative_keywords",
            {"customer_id": cid, "campaign_id": campaign_id, "keywords": keywords, "match_type": match_type},
            confirm,
            execute,
        )
    except GoogleAdsException as ex:
        return _error(ex)
