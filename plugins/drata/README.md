# Drata Plugin

Fetches compliance posture from the Drata public API: failing controls, overdue and due-soon personnel tasks, and new evidence requests.

## Required credentials

| Env var | Description |
|---------|-------------|
| `DRATA_API_KEY` | Drata API key — generate from **Settings → API** in the Drata UI |
| `DRATA_BASE_URL` | Optional. Defaults to `https://public-api.drata.com` |

## What it fetches

| Endpoint | Purpose |
|----------|---------|
| `GET /v1/controls?status=FAILING` | Controls currently in a failing state |
| `GET /v1/personnel/tasks?status=OVERDUE` | Compliance tasks past their due date |
| `GET /v1/personnel/tasks?status=DUE_SOON` | Compliance tasks coming due shortly |
| `GET /v1/evidence-requests?created_after=<window_start>` | Evidence requests opened in the run window |

All requests use `Authorization: Bearer <DRATA_API_KEY>`.

## Payload shape

```json
{
  "window_hours": 24,
  "failing_controls": [{ "id": "...", "name": "...", "status": "FAILING", "frameworks": ["SOC 2"] }],
  "overdue_tasks": [{ "id": "...", "title": "...", "assignee": "Alice", "due_date": "2026-04-20", "status": "OVERDUE" }],
  "due_soon_tasks": [{ "id": "...", "title": "...", "assignee": "Bob", "due_date": "2026-04-25", "status": "DUE_SOON" }],
  "evidence_requests": [{ "id": "...", "title": "...", "due_date": "2026-04-30", "status": "..." }]
}
```

## Redaction

Personnel email addresses in the `assignee` field are replaced with just the username portion (the part before `@`) before the payload is sent to Groq.

## Prompt focus

Controls that are currently failing, who has overdue compliance tasks, and upcoming audit deadlines within 7 days. Flags under **Attention** if more than 3 controls are failing or any task is overdue by more than 7 days.
