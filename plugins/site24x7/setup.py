"""One-time OAuth2 consent flow for the Site24x7 plugin.

Run this script once to obtain a Zoho refresh token, then set
SITE24X7_ZOHO_REFRESH_TOKEN in your .env file.

Usage:
    python plugins/site24x7/setup.py [--dc us|eu|in|au|cn|jp]
"""

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

__all__: list[str] = []

_SCOPE = "Site24x7.Reports.Read,Site24x7.Operations.Read"
_REDIRECT_URI = "https://www.zoho.com/site24x7"

_DC_AUTH_URLS: dict[str, str] = {
    "us": "https://accounts.zoho.com/oauth/v2/auth",
    "eu": "https://accounts.zoho.eu/oauth/v2/auth",
    "in": "https://accounts.zoho.in/oauth/v2/auth",
    "au": "https://accounts.zoho.com.au/oauth/v2/auth",
    "cn": "https://accounts.zoho.com.cn/oauth/v2/auth",
    "jp": "https://accounts.zoho.jp/oauth/v2/auth",
}

_DC_TOKEN_URLS: dict[str, str] = {
    "us": "https://accounts.zoho.com/oauth/v2/token",
    "eu": "https://accounts.zoho.eu/oauth/v2/token",
    "in": "https://accounts.zoho.in/oauth/v2/token",
    "au": "https://accounts.zoho.com.au/oauth/v2/token",
    "cn": "https://accounts.zoho.com.cn/oauth/v2/token",
    "jp": "https://accounts.zoho.jp/oauth/v2/token",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Site24x7 OAuth2 setup")
    parser.add_argument(
        "--dc",
        default="us",
        choices=list(_DC_AUTH_URLS),
        help="Zoho datacenter (default: us)",
    )
    args = parser.parse_args()
    dc: str = args.dc

    print("=== Site24x7 / Zoho OAuth2 Setup ===")
    print("Datacenter: %s" % dc.upper())
    print()
    client_id = input("Enter SITE24X7_CLIENT_ID: ").strip()
    client_secret = input("Enter SITE24X7_CLIENT_SECRET: ").strip()

    if not client_id or not client_secret:
        print("ERROR: client_id and client_secret are required.")
        sys.exit(1)

    params = {
        "client_id": client_id,
        "redirect_uri": _REDIRECT_URI,
        "response_type": "code",
        "scope": _SCOPE,
        "access_type": "offline",
    }
    auth_url = "%s?%s" % (_DC_AUTH_URLS[dc], urllib.parse.urlencode(params))

    print()
    print("Visit this URL to authorize Jarvis to access Site24x7:")
    print()
    print("  " + auth_url)
    print()
    print("After granting access, you will be redirected to the Site24x7 home page.")
    print("Copy the 'code' parameter from the redirect URL and paste it below.")
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

    req = urllib.request.Request(_DC_TOKEN_URLS[dc], data=data, method="POST")
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
        print("ERROR: No refresh_token in response.")
        print("Full response: %s" % json.dumps(tokens, indent=2))
        sys.exit(1)

    print()
    print("=== Success ===")
    print()
    print("Add the following to your .env file:")
    print()
    print("  SITE24X7_ZOHO_REFRESH_TOKEN=%s" % refresh_token)
    print("  SITE24X7_CLIENT_ID=%s" % client_id)
    print("  SITE24X7_CLIENT_SECRET=<your secret>")
    if dc != "us":
        print("  SITE24X7_DATACENTER=%s" % dc)


if __name__ == "__main__":
    main()
