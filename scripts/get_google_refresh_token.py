"""One-time helper: sign in with Google and print a refresh token for .env.

Usage:
    python scripts/get_google_refresh_token.py path/to/client_secret.json

Create the client in Google Cloud Console > APIs & Services > Credentials > OAuth client ID
(type "Desktop app"). Sign in with the Google account that has access to your Ads and GA4 accounts.
"""

import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/adwords",
    "https://www.googleapis.com/auth/analytics.readonly",
    "https://www.googleapis.com/auth/analytics.edit",
]

if len(sys.argv) != 2:
    sys.exit(__doc__)

flow = InstalledAppFlow.from_client_secrets_file(sys.argv[1], scopes=SCOPES)
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
print("\nAdd these to your .env:\n")
print(f"GOOGLE_CLIENT_ID={creds.client_id}")
print(f"GOOGLE_CLIENT_SECRET={creds.client_secret}")
print(f"GOOGLE_REFRESH_TOKEN={creds.refresh_token}")
