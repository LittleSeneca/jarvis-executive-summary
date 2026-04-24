"""One-time OAuth2 consent flow for the Gmail plugin.

Run this script once to obtain a refresh token, then set GMAIL_REFRESH_TOKEN
in your .env file.

Usage:
    python plugins/gmail/setup.py
"""

import json
import socket
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

__all__: list[str] = []

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
_PORT = 8080
_REDIRECT_URI = "http://localhost:%d" % _PORT


def _find_free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _wait_for_code() -> str:
    """Start a one-shot local HTTP server and return the auth code from Google's redirect."""
    code_holder: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            code = params.get("code", [None])[0]
            error = params.get("error", [None])[0]

            if error:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"Authorization denied. You can close this tab.")
                code_holder.append("")
            elif code:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"Authorization successful! You can close this tab.")
                code_holder.append(code)
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Unexpected request.")

        def log_message(self, *args: object) -> None:
            pass  # suppress request logs

    server = HTTPServer(("localhost", _PORT), Handler)
    server.handle_request()
    server.server_close()
    return code_holder[0] if code_holder else ""


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
    print("Opening your browser to authorize Jarvis...")
    print("If it doesn't open automatically, visit:")
    print()
    print("  " + auth_url)
    print()

    # Start the callback server in a thread before opening the browser
    code_holder: list[str] = []

    def _serve() -> None:
        code_holder.append(_wait_for_code())

    t = threading.Thread(target=_serve, daemon=True)
    t.start()

    webbrowser.open(auth_url)
    print("Waiting for Google to redirect back to localhost:%d ..." % _PORT)

    t.join(timeout=120)

    if not code_holder or not code_holder[0]:
        print("ERROR: No authorization code received (timed out or access denied).")
        sys.exit(1)

    code = code_holder[0]

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
        print("ERROR: No refresh_token in response.")
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
