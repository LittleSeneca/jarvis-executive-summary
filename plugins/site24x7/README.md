# Site24x7 Plugin

Fetches open alerts, server CPU/memory averages, and high-disk utilization from the [Site24x7 API](https://www.site24x7.com/help/api/) using Zoho OAuth2.

## Credentials

| Env var | Required | Notes |
|---------|----------|-------|
| `SITE24X7_ZOHO_REFRESH_TOKEN` | Yes | Obtained by running `setup.py` once |
| `SITE24X7_CLIENT_ID` | Yes | Zoho client ID from the Zoho API Console |
| `SITE24X7_CLIENT_SECRET` | Yes | Zoho client secret |
| `SITE24X7_DATACENTER` | No | `us` (default), `eu`, `in`, `au`, `cn`, or `jp` |

### First-time setup

1. Register a **Server-based Application** in the [Zoho API Console](https://api-console.zoho.com/).
2. Add `https://www.zoho.com/site24x7` as a redirect URI.
3. Run the setup script:

```bash
python plugins/site24x7/setup.py
```

4. Visit the printed URL, authorize, copy the `code` from the redirect URL's address bar (the page will show "resource not found" — that's expected), and paste it back.
5. Copy the printed `SITE24X7_ZOHO_REFRESH_TOKEN` into your `.env`.

## What it fetches

Two concurrent API calls per run:

| Endpoint | Purpose |
|----------|---------|
| `GET /current_status` | All monitors; filtered to DOWN/TROUBLE/UNKNOWN for open alerts |
| `GET /reports/performance?period=1` | 24h time-series for the SERVER group; averaged per server |

## Notes

- Only server monitors with the Site24x7 agent installed will have CPU/memory/disk data.
- Server monitors that are URL-only health checks appear in the SERVER group but show no metric data and are excluded.
- Disk threshold for high-utilization alert is 80%.

## Payload shape

```json
{
  "window_hours": 24,
  "open_alerts": [
    {"name": "prod-api", "type": "URL", "status": "DOWN", "last_polled": "2026-04-24T08:00:00-0400"}
  ],
  "server_performance": [
    {"name": "a-suite-0-staging.avatarfleet.com", "avg_cpu_pct": 8.7, "avg_mem_pct": 40.3, "max_disk_pct": 41.9}
  ],
  "high_disk_servers": []
}
```
