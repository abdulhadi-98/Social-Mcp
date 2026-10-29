<div align="center">

# Social MCP

**Let your AI agent run your ads and read your analytics: Google Ads, Google Analytics 4 and Meta Ads, in one MCP server.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![MCP](https://img.shields.io/badge/protocol-MCP-black)

Built and maintained by **[Discret Digital](https://www.discretdigital.com)**

</div>

---

Social MCP is an open-source [Model Context Protocol](https://modelcontextprotocol.io) server. It connects AI assistants and agents to your advertising and analytics accounts. Once connected, you can ask in plain language:

> *"Which Google Ads campaigns had a CPA above $40 last week? Pause the worst one."*
>
> *"Compare Meta and Google spend against GA4 conversions by source / medium for the last 30 days."*
>
> *"Pull the search terms for my brand campaign and add the irrelevant ones as negatives."*
>
> *"Create a paused Meta sales campaign called 'Black Friday' with a $100/day budget."*

It works with any MCP-compatible client: Claude (Desktop, Code and web), Grok through the xAI API, Cursor, the OpenAI Agents SDK, LangChain, n8n and others.

## Contents

- [Features](#features)
- [Safety by design](#safety-by-design)
- [Quick start](#quick-start)
- [Getting credentials](#getting-credentials)
- [Configuration](#configuration)
- [Connecting your AI client](#connecting-your-ai-client)
- [Deploying as a remote server](#deploying-as-a-remote-server)
- [Tool reference](#tool-reference)
- [Project structure](#project-structure)
- [Contributing](#contributing)
- [License](#license)

## Features

- **Multi-account by default.** It works with every Google Ads account (including manager/MCC client accounts), every GA4 property and every Meta ad account your credentials can access.
- **Read and write.** Agents can report, analyse and act: pause, enable, change budgets and bids, add negative keywords, create campaigns, and mark GA4 key events.
- **Built-in reporting helpers.** You can run any Google Ads Query Language (GAQL) query, or use ready-made campaign performance reports with CPA and ROAS. Meta insights support breakdowns, and GA4 reports support filters, realtime data and metadata lookup.
- **Two transports.** `stdio` for local clients, and Streamable HTTP for remote and web clients.
- **Docker-ready.** A single container can be deployed to Cloud Run, Railway, Render, Fly.io or any VPS.

## Safety by design

Ad accounts spend real money, so every change goes through several layers of protection:

| Guardrail | What it does |
|---|---|
| **Preview → confirm** | Every write tool returns a dry-run preview by default (`confirm=false`). The agent must show you the preview and call again with `confirm=true` only after you approve. |
| **Read-only by default** | All writes are blocked until you set `ALLOW_WRITES=true`. |
| **Budget cap** | `MAX_DAILY_BUDGET` rejects any daily budget above your limit. |
| **Account allowlists** | `ALLOWED_GOOGLE_ADS_CUSTOMERS` and `ALLOWED_META_AD_ACCOUNTS` restrict which accounts can be touched. |
| **Paused creation** | New Meta campaigns are always created **PAUSED**. |
| **Field allowlist** | Generic Meta updates are limited to a fixed set of safe fields. |
| **Audit log** | Every executed write is appended to `audit_log.jsonl`, with a timestamp and the result. |
| **Authenticated HTTP** | The remote server refuses to start without `MCP_API_KEY` and compares keys in constant time. |

## Quick start

```bash
git clone https://github.com/abdulhadi-98/Social-Mcp.git
cd Social-Mcp
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env        # fill in your credentials (see below)
social-mcp                  # runs over stdio
```

## Getting credentials

### Google Ads and GA4 (one login covers both)

1. **Create a Google Cloud project** in the [Cloud Console](https://console.cloud.google.com/). Then enable:
   - Google Ads API
   - Google Analytics Data API
   - Google Analytics Admin API
2. **Configure the OAuth consent screen** under *APIs & Services → OAuth consent screen*, and add yourself as a test user.
3. **Create an OAuth client ID** of type **Desktop app** under *APIs & Services → Credentials*, and download the JSON file.
4. **Generate a refresh token.** A browser window opens; sign in with the Google account that can access your Ads and GA4 accounts.
   ```bash
   python scripts/get_google_refresh_token.py path/to/client_secret.json
   ```
   > While the consent screen is in *Testing* mode, refresh tokens expire after 7 days. Publish the app to get a long-lived token. It can stay unverified for personal or internal use.
5. **Get a Google Ads developer token** from a manager (MCC) account under *Tools → API Center*. New tokens have *Test* access, which only works with test accounts. Apply for **Basic access** to manage live accounts.
6. If you access your accounts through an MCC, set `GOOGLE_ADS_LOGIN_CUSTOMER_ID` to its ID.

### Meta (Facebook and Instagram) Ads

1. Create an app at [developers.facebook.com](https://developers.facebook.com/) (type *Business*) and add the **Marketing API** product.
2. In **Business Settings → Users → System users**, create an *Admin* system user. Assign it your ad accounts, plus your Pages if it will create ads.
3. Click **Generate token**, select your app, and grant `ads_management`, `ads_read` and `business_management`. System user tokens do not expire.

## Configuration

All settings come from environment variables or a `.env` file in the project root. See [`.env.example`](.env.example).

| Variable | Required | Description |
|---|---|---|
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Google | The OAuth client from the steps above |
| `GOOGLE_REFRESH_TOKEN` | Google | Output of `get_google_refresh_token.py` |
| `GOOGLE_ADS_DEVELOPER_TOKEN` | Google Ads | Developer token from the API Center |
| `GOOGLE_ADS_LOGIN_CUSTOMER_ID` | Optional | MCC ID (digits only) when you access accounts through a manager |
| `META_ACCESS_TOKEN` | Meta | System user access token |
| `META_API_VERSION` | Optional | Graph API version (default `v24.0`) |
| `ALLOW_WRITES` | Optional | `true` to allow confirmed changes (default `false`) |
| `MAX_DAILY_BUDGET` | Optional | Maximum daily budget an agent can set (default `500`) |
| `ALLOWED_GOOGLE_ADS_CUSTOMERS` | Optional | Comma-separated customer IDs the server may touch |
| `ALLOWED_META_AD_ACCOUNTS` | Optional | Comma-separated ad account IDs, e.g. `act_123,act_456` |
| `AUDIT_LOG_PATH` | Optional | Where write actions are logged (default `audit_log.jsonl`) |
| `MCP_API_KEY` | HTTP mode | Secret that clients must send to the remote server |
| `HOST` / `PORT` | Optional | HTTP bind address (default `0.0.0.0:8000`) |

You only need credentials for the platforms you use. Tools for an unconfigured platform return a clear error.

## Connecting your AI client

### Local clients (stdio)

**Claude Desktop:** add this to `claude_desktop_config.json` (*Settings → Developer → Edit Config*):

```json
{
  "mcpServers": {
    "social-mcp": { "command": "/absolute/path/to/Social-Mcp/.venv/bin/social-mcp" }
  }
}
```

**Claude Code:**

```bash
claude mcp add social-mcp -- /absolute/path/to/Social-Mcp/.venv/bin/social-mcp
```

**Cursor and other stdio clients:** use the same command, `/absolute/path/to/Social-Mcp/.venv/bin/social-mcp`.

### Remote clients (HTTP)

First deploy the server (see [Deploying as a remote server](#deploying-as-a-remote-server)). Your endpoint is `https://YOUR-HOST/mcp`.

**Claude web and mobile:** go to *Settings → Connectors → Add custom connector* and enter:

```
https://YOUR-HOST/mcp?key=YOUR_MCP_API_KEY
```

> The key is passed in the URL because that form only accepts a URL. Treat the full URL like a password.

**Grok (xAI API):** pass the server as a remote MCP tool. See [`scripts/grok_example.py`](scripts/grok_example.py) for a full example:

```python
tools=[{
    "type": "mcp",
    "server_label": "social-mcp",
    "server_url": "https://YOUR-HOST/mcp",
    "authorization": "YOUR_MCP_API_KEY",
}]
```

> Check the [xAI docs](https://docs.x.ai) for the current remote-MCP field names.

**Claude Code (remote), the OpenAI Agents SDK, LangChain, n8n and others:** connect to `https://YOUR-HOST/mcp` with this header:

```
Authorization: Bearer YOUR_MCP_API_KEY
```

## Deploying as a remote server

```bash
# Generate an API key
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Build and run
docker build -t social-mcp .
docker run -p 8000:8000 --env-file .env social-mcp
```

To check that it's running, open `GET /health`. It returns `{"ok": true, "writes_enabled": false}`.

On a managed platform (Cloud Run, Railway, Render, Fly.io), set your variables as the platform's secrets rather than baking `.env` into the image. Always serve the server over HTTPS.

To run it without Docker:

```bash
social-mcp --transport http
```

## Tool reference

### Google Ads

| Tool | Type | Description |
|---|---|---|
| `google_ads_list_accounts` | Read | All accessible accounts, with name, currency and manager flag |
| `google_ads_list_client_accounts` | Read | Client accounts under an MCC |
| `google_ads_query` | Read | Run any GAQL query |
| `google_ads_campaign_performance` | Read | Spend, clicks, conversions, CPA and ROAS per campaign |
| `google_ads_set_status` | Write | Pause or enable a campaign, ad group, ad or keyword |
| `google_ads_set_campaign_budget` | Write | Change a campaign's daily budget (warns about shared budgets) |
| `google_ads_set_ad_group_cpc_bid` | Write | Set an ad group's max CPC |
| `google_ads_add_negative_keywords` | Write | Add campaign-level negative keywords |

### Google Analytics 4

| Tool | Type | Description |
|---|---|---|
| `ga4_list_properties` | Read | All accounts and properties |
| `ga4_run_report` | Read | Metrics and dimensions with date ranges, filters and sorting |
| `ga4_realtime_report` | Read | Users active in the last 30 minutes |
| `ga4_get_metadata` | Read | Search the available dimensions and metrics |
| `ga4_create_key_event` | Write | Mark an event as a key event (conversion) |
| `ga4_create_custom_dimension` | Write | Register an event or user parameter as a custom dimension |

### Meta Ads

| Tool | Type | Description |
|---|---|---|
| `meta_list_ad_accounts` | Read | All accessible ad accounts |
| `meta_list_entities` | Read | Campaigns, ad sets or ads, with status and budgets |
| `meta_get_insights` | Read | Performance with breakdowns and daily rows |
| `meta_set_status` | Write | Pause or activate a campaign, ad set or ad |
| `meta_set_budget` | Write | Change a daily or lifetime budget (handles currency units) |
| `meta_update_entity` | Write | Update safe fields (name, bid, schedule, spend cap) |
| `meta_create_campaign` | Write | Create a campaign, always paused |

## Project structure

```
Social-Mcp/
├── ads_mcp/
│   ├── server.py        # MCP server, tool registry, HTTP auth
│   ├── google_ads.py    # Google Ads tools
│   ├── ga4.py           # Google Analytics 4 tools
│   ├── meta_ads.py      # Meta Marketing API tools
│   ├── safety.py        # Preview/confirm, limits, allowlists, audit log
│   └── config.py        # Environment settings
├── scripts/
│   ├── get_google_refresh_token.py
│   └── grok_example.py
├── Dockerfile
├── pyproject.toml
└── .env.example
```

### Adding a tool

1. Write a typed function with a clear docstring in the relevant platform module. The docstring becomes the tool description the AI sees.
2. Wrap any account change in `guarded_write(...)` so it gets the preview, confirmation and audit behavior.
3. Register the function in `TOOLS` in `ads_mcp/server.py` with the `READ` or `WRITE` annotation.

## Roadmap

- [ ] Google Ads campaign, ad group and responsive search ad creation
- [ ] Meta ad set and ad creation, plus creative upload
- [ ] TikTok Ads and LinkedIn Ads
- [ ] OAuth 2.1 sign-in for the remote server
- [ ] Search Console and Merchant Center

## Contributing

Contributions are welcome. Open an issue to discuss larger changes, or send a pull request for fixes and new tools. Please keep new write tools behind `guarded_write`.

## Security

Never commit `.env`, OAuth client files or access tokens; they are already in `.gitignore`. If you find a security issue, please report it privately through [discretdigital.com](https://www.discretdigital.com) instead of opening a public issue.

## Disclaimer

Social MCP is not affiliated with, endorsed by or sponsored by Google or Meta. "Google Ads" and "Google Analytics" are trademarks of Google LLC. "Meta", "Facebook" and "Instagram" are trademarks of Meta Platforms, Inc. You are responsible for every change made to your ad accounts, so review the previews before you approve them.

## License

[MIT](LICENSE) © [Discret Digital](https://www.discretdigital.com)
