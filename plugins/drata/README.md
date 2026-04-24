# Drata Plugin

Fetches compliance monitor health and unhealthy personnel from the Drata public API.

Note: The `/public/controls` endpoint only exposes the Drata Starter control subset (~50 controls),
which does not match the full framework control library visible in the UI. Controls are therefore
not included — monitors provide complete and accurate compliance signal.

## Required credentials

| Env var | Description |
|---------|-------------|
| `DRATA_API_KEY` | Drata API key — generate from **Settings → API** in the Drata UI |
| `DRATA_BASE_URL` | Optional. Defaults to `https://public-api.drata.com` |

## What it fetches

| Endpoint | Purpose |
|----------|---------|
| `GET /public/monitors` | All compliance monitors with check results (paginated, up to 300) |
| `GET /public/personnel` | Current employees and contractors; filtered to those failing `FULL_COMPLIANCE` |

All requests use `Authorization: Bearer <DRATA_API_KEY>`.

## Notes

- The Drata public API max page size is 50. Pages are fetched concurrently after the first.
- Personnel are deduplicated by ID (Drata returns duplicates across pages).
- Personnel names are extracted from the Google identity connection; falls back to email.
- Only `CURRENT_EMPLOYEE` and `CURRENT_CONTRACTOR` records are considered.
- A person is "unhealthy" when their `FULL_COMPLIANCE` check is `FAIL`.

## Payload shape

```json
{
  "window_hours": 24,
  "monitors": {
    "total": 300,
    "by_status": {"FAILED": 54, "PASSED": 246},
    "all_failed": [
      {
        "id": 31,
        "name": "MFA on Identity Provider",
        "status": "FAILED",
        "priority": "HIGH",
        "last_check": "2026-04-24",
        "failed_description": "There are identities without MFA enabled.",
        "remedy": "Send email reminders from within Drata..."
      }
    ]
  },
  "personnel": {
    "unhealthy": [
      {
        "name": "David Frayser",
        "employment_status": "CURRENT_CONTRACTOR",
        "failing_checks": ["ACCEPTED_POLICIES", "IDENTITY_MFA", "SECURITY_TRAINING"]
      }
    ],
    "check_summary": {
      "ACCEPTED_POLICIES": 1,
      "IDENTITY_MFA": 1
    }
  }
}
```
