"""Google Analytics 4 tools: property discovery, reports, realtime, and key-event / custom-dimension setup."""

from functools import lru_cache
from typing import Any, Literal

from google.analytics import admin_v1beta
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta import types as data
from google.oauth2.credentials import Credentials
from google.protobuf.json_format import MessageToDict

from .config import settings
from .safety import guarded_write

SCOPES = ["https://www.googleapis.com/auth/analytics.readonly", "https://www.googleapis.com/auth/analytics.edit"]


@lru_cache(maxsize=1)
def _credentials():
    if settings.google_refresh_token:
        return Credentials(
            token=None,
            refresh_token=settings.google_refresh_token,
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            token_uri="https://oauth2.googleapis.com/token",
            scopes=SCOPES,
        )
    return None  # fall back to Application Default Credentials / GOOGLE_APPLICATION_CREDENTIALS


@lru_cache(maxsize=1)
def _data_client() -> BetaAnalyticsDataClient:
    return BetaAnalyticsDataClient(credentials=_credentials())


@lru_cache(maxsize=1)
def _admin_client() -> admin_v1beta.AnalyticsAdminServiceClient:
    return admin_v1beta.AnalyticsAdminServiceClient(credentials=_credentials())


def _prop(property_id: str) -> str:
    return property_id if property_id.startswith("properties/") else f"properties/{property_id}"


def _rows(resp) -> list[dict]:
    dims = [h.name for h in resp.dimension_headers]
    mets = [h.name for h in resp.metric_headers]
    return [
        {**{d: v.value for d, v in zip(dims, r.dimension_values)}, **{m: v.value for m, v in zip(mets, r.metric_values)}}
        for r in resp.rows
    ]


def list_properties() -> dict[str, Any]:
    """List every GA4 account and property the authenticated user can access."""
    out = []
    for summary in _admin_client().list_account_summaries():
        out.append({
            "account": summary.account,
            "account_name": summary.display_name,
            "properties": [{"property": p.property, "name": p.display_name} for p in summary.property_summaries],
        })
    return {"accounts": out}


def _filter(filters: list[dict] | None):
    if not filters:
        return None
    exprs = []
    for f in filters:
        match = data.Filter.StringFilter.MatchType[f.get("match", "EXACT")]
        exprs.append(data.FilterExpression(filter=data.Filter(
            field_name=f["field"], string_filter=data.Filter.StringFilter(value=f["value"], match_type=match)
        )))
    return exprs[0] if len(exprs) == 1 else data.FilterExpression(and_group=data.FilterExpressionList(expressions=exprs))


def run_report(
    property_id: str,
    metrics: list[str],
    dimensions: list[str] | None = None,
    start_date: str = "28daysAgo",
    end_date: str = "today",
    dimension_filters: list[dict] | None = None,
    order_by_metric: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Run a GA4 report.

    metrics e.g. ["sessions", "totalUsers", "conversions", "purchaseRevenue"];
    dimensions e.g. ["date", "sessionSourceMedium", "sessionCampaignName", "landingPage"].
    Dates: YYYY-MM-DD, "today", "yesterday" or "NdaysAgo".
    dimension_filters: [{"field": "sessionSourceMedium", "value": "google / cpc", "match": "EXACT|CONTAINS|BEGINS_WITH"}] (ANDed).
    order_by_metric: sort descending by this metric.
    """
    req = data.RunReportRequest(
        property=_prop(property_id),
        metrics=[data.Metric(name=m) for m in metrics],
        dimensions=[data.Dimension(name=d) for d in dimensions or []],
        date_ranges=[data.DateRange(start_date=start_date, end_date=end_date)],
        dimension_filter=_filter(dimension_filters),
        order_bys=[data.OrderBy(metric=data.OrderBy.MetricOrderBy(metric_name=order_by_metric), desc=True)] if order_by_metric else [],
        limit=limit,
    )
    resp = _data_client().run_report(req)
    return {"row_count": resp.row_count, "rows": _rows(resp)}


def realtime_report(property_id: str, metrics: list[str] | None = None, dimensions: list[str] | None = None) -> dict[str, Any]:
    """Users active in the last 30 minutes. Defaults to activeUsers by country."""
    resp = _data_client().run_realtime_report(data.RunRealtimeReportRequest(
        property=_prop(property_id),
        metrics=[data.Metric(name=m) for m in metrics or ["activeUsers"]],
        dimensions=[data.Dimension(name=d) for d in dimensions or ["country"]],
    ))
    return {"rows": _rows(resp)}


def get_metadata(property_id: str, search: str = "") -> dict[str, Any]:
    """List the dimension and metric API names available for a property (optionally filtered by a search term)."""
    meta = _data_client().get_metadata(name=f"{_prop(property_id)}/metadata")
    s = search.lower()

    def keep(x):
        return not s or s in x.api_name.lower() or s in x.ui_name.lower()

    return {
        "dimensions": [{"api_name": d.api_name, "ui_name": d.ui_name} for d in meta.dimensions if keep(d)],
        "metrics": [{"api_name": m.api_name, "ui_name": m.ui_name} for m in meta.metrics if keep(m)],
    }


def create_key_event(property_id: str, event_name: str, confirm: bool = False) -> dict[str, Any]:
    """Mark an event (e.g. "generate_lead", "purchase") as a key event (conversion) in GA4."""
    def execute():
        ke = _admin_client().create_key_event(
            parent=_prop(property_id),
            key_event=admin_v1beta.KeyEvent(event_name=event_name, counting_method=admin_v1beta.KeyEvent.CountingMethod.ONCE_PER_EVENT),
        )
        return MessageToDict(ke._pb)

    return guarded_write("ga4.create_key_event", {"property": _prop(property_id), "event_name": event_name}, confirm, execute)


def create_custom_dimension(
    property_id: str,
    parameter_name: str,
    display_name: str,
    scope: Literal["EVENT", "USER"] = "EVENT",
    description: str = "",
    confirm: bool = False,
) -> dict[str, Any]:
    """Register an event or user parameter as a custom dimension so it can be used in reports."""
    def execute():
        cd = _admin_client().create_custom_dimension(
            parent=_prop(property_id),
            custom_dimension=admin_v1beta.CustomDimension(
                parameter_name=parameter_name,
                display_name=display_name,
                description=description,
                scope=admin_v1beta.CustomDimension.DimensionScope[scope],
            ),
        )
        return MessageToDict(cd._pb)

    return guarded_write(
        "ga4.create_custom_dimension",
        {"property": _prop(property_id), "parameter_name": parameter_name, "display_name": display_name, "scope": scope},
        confirm,
        execute,
    )
