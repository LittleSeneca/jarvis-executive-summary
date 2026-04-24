# Site24x7 Plugin

Fetches alert logs, current monitor status, and SLA summary from the [Site24x7 API](https://www.site24x7.com/help/api/) using Zoho OAuth2.

## Credentials

| Env var | Required | Notes |
|---------|----------|-------|
| `SITE24X7_ZOHO_REFRESH_TOKEN` | Yes | Obtained by running `setup.py` once |
| `SITE24X7_CLIENT_ID` | Yes | Zoho client ID from the Zoho API Console |
| `SITE24X7_CLIENT_SECRET` | Yes | Zoho client secret |
| `SITE24X7_DATACENTER` | No | `us` (default), `eu`, `in`, `au`, `cn`, or `jp` |

### First-time setup

1. Register a **Server-based Application** in the [Zoho API Console](https://api-console.zoho.com/).
2. Set the redirect URI to `https://www.zoho.com/site24x7`.
3. Run the setup script (add `--dc eu` etc. for non-US datacenters):

```bash
python plugins/site24x7/setup.py
```

4. Visit the printed URL, authorize access, copy the `code` parameter from the redirect URL, and paste it back.
5. Copy the printed `SITE24X7_ZOHO_REFRESH_TOKEN` into your `.env`.

## Datacenter mapping

| `SITE24X7_DATACENTER` | Token endpoint | API base URL |
|------------------------|----------------|--------------|
| `us` (default) | `accounts.zoho.com` | `www.site24x7.com/api` |
| `eu` | `accounts.zoho.eu` | `www.site24x7.eu/api` |
| `in` | `accounts.zoho.in` | `www.site24x7.in/api` |
| `au` | `accounts.zoho.com.au` | `www.site24x7.com.au/api` |
| `cn` | `accounts.zoho.com.cn` | `www.site24x7.cn/api` |
| `jp` | `accounts.zoho.jp` | `www.site24x7.jp/api` |

## What it fetches

Three concurrent API calls per run:

| Endpoint | Purpose |
|----------|---------|
| `GET /alert_logs/summary?period=1d` | Alert events in the last 24 hours |
| `GET /current_status` | All monitors; filtered to DOWN or TROUBLE |
| `GET /sla/summary` | SLA entries; filtered to breached or at-risk |

## Payload shape

```json
{
  "window_hours": 24,
  "alerts": [
    { "monitor": "prod-api", "type": "DOWN", "status": "Critical", "occurred": "2026-04-23T03:12:00Z" }
  ],
  "down_monitors": [
    { "name": "prod-api", "type": "URL", "status": "DOWN", "last_checked": "2026-04-23T08:00:00Z", "unit": "" }
  ],
  "sla_at_risk": [
    { "monitor": "prod-api", "sla": "99.9% Uptime SLA", "availability_pct": 99.1, "target_pct": 99.9, "breached": true }
  ]
}
```

## Notes

- The Zoho access token is valid for 1 hour; Jarvis always exchanges a fresh one at startup using the stored refresh token.
- `redact()` is a no-op for this plugin — monitor names and availability figures are not considered sensitive.
