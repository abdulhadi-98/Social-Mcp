"""Entry point: registers all tools and serves them over stdio or Streamable HTTP.

    python -m ads_mcp.server                      # stdio (local desktop / CLI agents)
    python -m ads_mcp.server --transport http     # remote server (web connectors, xAI API, agent frameworks)
"""

import argparse
import functools
import hmac

import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.responses import JSONResponse

from . import ga4, google_ads, meta_ads
from .config import settings

INSTRUCTIONS = """\
Tools for Google Ads, Google Analytics 4 and Meta (Facebook/Instagram) Ads.

Start by discovering accounts: google_ads_list_accounts, ga4_list_properties, meta_list_ad_accounts.
Every tool that changes something takes `confirm`. Always call it first with confirm=false,
show the user the returned preview, and only call again with confirm=true after the user
explicitly approves. Never activate campaigns or raise budgets without explicit approval.
Google Ads costs are in micros (divide by 1,000,000); Meta budgets in list/insights output are in minor units (cents).
"""

mcp = MCPServer(name="social-mcp", instructions=INSTRUCTIONS)

READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=True)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=True)

TOOLS = [
    # Google Ads
    ("google_ads_list_accounts", google_ads.list_accounts, READ),
    ("google_ads_list_client_accounts", google_ads.list_client_accounts, READ),
    ("google_ads_query", google_ads.query, READ),
    ("google_ads_campaign_performance", google_ads.campaign_performance, READ),
    ("google_ads_set_status", google_ads.set_status, WRITE),
    ("google_ads_set_campaign_budget", google_ads.set_campaign_budget, WRITE),
    ("google_ads_set_ad_group_cpc_bid", google_ads.set_ad_group_cpc_bid, WRITE),
    ("google_ads_add_negative_keywords", google_ads.add_negative_keywords, WRITE),
    # Google Analytics 4
    ("ga4_list_properties", ga4.list_properties, READ),
    ("ga4_run_report", ga4.run_report, READ),
    ("ga4_realtime_report", ga4.realtime_report, READ),
    ("ga4_get_metadata", ga4.get_metadata, READ),
    ("ga4_create_key_event", ga4.create_key_event, WRITE),
    ("ga4_create_custom_dimension", ga4.create_custom_dimension, WRITE),
    # Meta Ads
    ("meta_list_ad_accounts", meta_ads.list_ad_accounts, READ),
    ("meta_list_entities", meta_ads.list_entities, READ),
    ("meta_get_insights", meta_ads.get_insights, READ),
    ("meta_search_ad_library", meta_ads.search_ad_library, READ),
    ("meta_set_status", meta_ads.set_status, WRITE),
    ("meta_set_budget", meta_ads.set_budget, WRITE),
    ("meta_update_entity", meta_ads.update_entity, WRITE),
    ("meta_create_campaign", meta_ads.create_campaign, WRITE),
]



def _surface_errors(fn):
    """Pass the real error text to the agent (by default the SDK hides it) so it can explain or retry."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            raise ToolError(f"{type(exc).__name__}: {exc}") from exc

    return wrapper


for name, fn, annotations in TOOLS:
    mcp.tool(name=name, annotations=annotations)(_surface_errors(fn))


@mcp.custom_route("/health", methods=["GET"])
async def health(_request):
    return JSONResponse({"ok": True, "writes_enabled": settings.allow_writes})


class ApiKeyMiddleware:
    """Requires MCP_API_KEY as `Authorization: Bearer <key>` or a `?key=<key>` query param.

    The query-param form exists for clients whose connector settings only take a URL.
    """

    def __init__(self, app, api_key: str):
        self.app, self.api_key = app, api_key.encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"] != "/health":
            headers = dict(scope["headers"])
            supplied = headers.get(b"authorization", b"").removeprefix(b"Bearer ").strip()
            if not supplied:
                for part in scope.get("query_string", b"").split(b"&"):
                    if part.startswith(b"key="):
                        supplied = part[4:]
            if not hmac.compare_digest(supplied, self.api_key):
                await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
                return
        await self.app(scope, receive, send)


def main() -> None:
    parser = argparse.ArgumentParser(description="Social MCP: ads & analytics MCP server")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run("stdio")
        return

    if not settings.mcp_api_key:
        raise SystemExit("Refusing to serve over HTTP without MCP_API_KEY set.")
    app = mcp.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        # The API key replaces host-header checks, which would reject your public domain.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        host=settings.host,
    )
    uvicorn.run(ApiKeyMiddleware(app, settings.mcp_api_key), host=settings.host, port=settings.port, proxy_headers=True)


if __name__ == "__main__":
    main()
