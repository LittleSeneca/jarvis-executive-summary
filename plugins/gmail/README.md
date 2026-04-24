# Gmail Plugin

Fetches inbox messages from the Gmail API and summarizes them in the morning brief. Requires a one-time OAuth2 consent flow to obtain a refresh token.

## Credentials

| Env var | Required | Notes |
|---------|----------|-------|
| `GMAIL_CLIENT_ID` | Yes | Google OAuth2 client ID |
| `GMAIL_CLIENT_SECRET` | Yes | Google OAuth2 client secret |
| `GMAIL_REFRESH_TOKEN` | Yes | Obtained by running `setup.py` once |
| `GMAIL_USER` | Yes | Gmail address (e.g. `you@example.com`) or `me` |
| `GMAIL_QUERY` | No | Gmail search query; default `in:inbox newer_than:1d` |

### First-time setup

1. Create a project in [Google Cloud Console](https://console.cloud.google.com/).
2. Enable the **Gmail API**.
3. Create an **OAuth 2.0 Client ID** of type "Desktop app" and download the credentials.
4. Run the setup script:

```bash
python plugins/gmail/setup.py
```

5. Visit the printed URL, authorize access, paste the code back.
6. Copy the printed `GMAIL_REFRESH_TOKEN` into your `.env`.

## What it fetches

Up to 100 messages matching `GMAIL_QUERY` (default: inbox messages from the last day):

- Message IDs via `GET /gmail/v1/users/{user}/messages`
- Per-message metadata (From, To, Subject, Date) and snippet via `GET /gmail/v1/users/{user}/messages/{id}?format=metadata`

Message bodies are **not** fetched — only the snippet Google provides (up to 500 characters).

Fetches are batched in groups of 20 concurrent requests.

## Payload shape

```json
{
  "window_hours": 24,
  "message_count": 5,
  "messages": [
    {
      "id": "18f3a...",
      "thread_id": "18f3a...",
      "subject": "Q2 budget review",
      "from": "Alice <alice@example.com>",
      "to": "you@example.com",
      "snippet": "Hi, can you review the attached...",
      "date": "Thu, 23 Apr 2026 08:12:00 -0400",
      "is_unread": true,
      "has_attachments": true
    }
  ]
}
```

## Redaction

Before the payload is sent to Groq, the local part of each `from` address is replaced with `...`:

- `Alice <alice@example.com>` → `Alice <...@example.com>`
- `alice@example.com` → (left as-is if no display name — the domain alone is not sensitive)

Snippets are also truncated to 500 characters if not already done.
