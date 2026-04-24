# OSINT Plugin — Threat Intel

Aggregates the last 24 hours of threat intelligence from up to six public and free-tier feeds, then summarises the landscape for the executive brief.

## What it does

- Fetches all enabled sources **concurrently** with a 30-second per-source timeout.
- Each source failure is isolated: a single source going down sets `status: "error"` for that source without affecting the rest of the digest.
- IoC values (IPs, URLs, domains) are **defanged** before reaching the LLM (`http` → `hxxp`, `.` → `[.]`).
- Only raises `PluginFetchError` when every enabled source fails, or on a catastrophic unexpected error.

## Sources

| Source | What it provides | Auth required |
|--------|-----------------|---------------|
| CISA KEV | Known exploited vulnerabilities | None |
| NVD CVE 2.0 | Recent CVEs with CVSS scores | None (optional key lifts rate limit) |
| abuse.ch URLhaus | Malicious URLs reported in the wild | None |
| abuse.ch ThreatFox | IoCs (IPs, domains, hashes) with malware attribution | Free key from abuse.ch account |
| abuse.ch Feodo Tracker | Botnet C2 IP blocklist | None |
| AlienVault OTX | Threat pulses from subscribed feeds | Free key from OTX account |

## Authentication

`auth.py` returns one `httpx.AsyncClient` per source. Clients for ThreatFox and OTX are `None` when their keys are absent; the plugin marks those sources as `skipped` rather than erroring.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `OSINT_SOURCES` | `cisa_kev,nvd,urlhaus,threatfox,feodo,otx` | Comma-separated list of enabled sources |
| `OSINT_NVD_API_KEY` | *(unset)* | Optional NVD API key; lifts anonymous rate limit |
| `OSINT_NVD_MIN_CVSS` | `7.0` | Drop CVEs below this CVSS v3.1 base score |
| `OSINT_NVD_MAX_CVES` | `40` | Maximum CVEs to include after filtering |
| `OSINT_URLHAUS_LIMIT` | `100` | Number of recent URLs to request from URLhaus |
| `OSINT_URLHAUS_MAX_ITEMS` | `50` | Cap on URLhaus items after window filter |
| `OSINT_THREATFOX_API_KEY` | *(unset)* | Free key from [abuse.ch](https://abuse.ch/account); source skipped without it |
| `OSINT_THREATFOX_MAX_ITEMS` | `50` | Cap on ThreatFox IoCs |
| `OSINT_OTX_API_KEY` | *(unset)* | Free key from [OTX](https://otx.alienvault.com); source skipped without it |

## Payload shape

```json
{
  "window_hours": 24,
  "generated_at": "2026-04-23T10:00:00Z",
  "sources": {
    "cisa_kev":  { "status": "ok", "count": 2,  "items": [...] },
    "nvd":       { "status": "ok", "count": 37, "truncated": false, "items": [...] },
    "urlhaus":   { "status": "ok", "count": 50, "truncated": true,  "items": [...] },
    "threatfox": { "status": "skipped", "reason": "no auth key" },
    "feodo":     { "status": "ok", "count": 11, "items": [...] },
    "otx":       { "status": "ok", "count": 4,  "items": [...] }
  }
}
```

## Failures

- A single source failure → `status: "error"` in the payload, rest of the run continues.
- All enabled sources fail → `PluginFetchError` is raised and the digest shows "unavailable" for the Threat Intel section.
- Sources without required keys → `status: "skipped"` in the payload, no error logged.

## Getting API keys

- **ThreatFox**: create a free account at https://abuse.ch and generate a key under your profile.
- **OTX**: register at https://otx.alienvault.com and copy your API key from Settings.
- **NVD**: request a key at https://nvd.nist.gov/developers/request-an-api-key (optional; anonymous requests are rate-limited to 5 req/30s).
