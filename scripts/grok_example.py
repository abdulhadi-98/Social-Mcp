"""Use the Social MCP remote server from Grok via the xAI API (Responses API, remote MCP tool).

    pip install openai
    XAI_API_KEY=... MCP_URL=https://your-host/mcp MCP_API_KEY=... python scripts/grok_example.py
"""

import os

from openai import OpenAI

client = OpenAI(api_key=os.environ["XAI_API_KEY"], base_url="https://api.x.ai/v1")

response = client.responses.create(
    model=os.getenv("GROK_MODEL", "grok-4"),
    input="List my Meta ad accounts, then show the top 5 campaigns by spend in the last 7 days.",
    tools=[{
        "type": "mcp",
        "server_label": "ads",
        "server_url": os.environ["MCP_URL"],
        "authorization": os.environ["MCP_API_KEY"],
    }],
)
print(response.output_text)
