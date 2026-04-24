"""One-time OAuth2 consent flow for the Gmail plugin.

Run this script once to obtain a refresh token, then set GMAIL_REFRESH_TOKEN
in your .env file.

Usage:
    python plugins/gmail/setup.py
"""

import urllib.parse
import urllib.request
import json
import sys

__all__: list[str] = []

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
_REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob"


def main() -> None:
    print("=== Gmail OAuth2 Setup ===")
    print()
    client_id = input("Enter GMAIL_CLIENT_ID: ").strip()
    client_secret = input("Enter GMAIL_CLIENT_SECRET: ").strip()

    if not client_id or not client_secret:
        print("ERROR: client_id and client_secret are required.")
        sys.exit(1)

    params = {
        "client_id": client_id,
        "redirect_uri": _REDIRECT_URI,
        "response_type": "code",
        "scope": _SCOPE,
        "access_type": "offline",
        "prompt": "consent",
    }
    auth_url = "%s?%s" % (_AUTH_URL, urllib.parse.urlencode(params))

    print()
    print("Visit this URL to authorize Jarvis to read your Gmail inbox:")
    print()
    print("  " + auth_url)
    print()
    code = input("Paste the authorization code here: ").strip()

    if not code:
        print("ERROR: No authorization code provided.")
        sys.exit(1)

    data = urllib.parse.urlencode(
        {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": _REDIRECT_URI,
            "grant_type": "authorization_code",
        }
    ).encode()

    req = urllib.request.Request(_TOKEN_URL, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req) as resp:
            tokens = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print("ERROR: Token exchange failed (HTTP %s): %s" % (exc.code, body))
        sys.exit(1)

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        print("ERROR: No refresh_token in response. Ensure 'access_type=offline' and 'prompt=consent' were sent.")
        print("Full response: %s" % json.dumps(tokens, indent=2))
        sys.exit(1)

    print()
    print("=== Success ===")
    print()
    print("Add the following to your .env file:")
    print()
    print("  GMAIL_REFRESH_TOKEN=%s" % refresh_token)
    print()
    print("Also set:")
    print("  GMAIL_CLIENT_ID=%s" % client_id)
    print("  GMAIL_CLIENT_SECRET=<your secret>")
    print("  GMAIL_USER=<your Gmail address>")


if __name__ == "__main__":
    main()
