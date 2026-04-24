# Jarvis Plugin Spec — `osint` (Threat Intel / IoCs)

**Status:** Draft v0.1
**Owner:** Graham Brooks
**Last updated:** 2026-04-23
**Plugin name:** `osint`
**Display name:** Threat Intel
**Scope:** plugin-local. This document is subordinate to [`initial-spec.md`](./initial-spec.md) — when the two disagree, the initial spec wins.

---

## 1. Purpose

A daily "what new threats entered the public record overnight" section for the morning brief. The plugin pulls **free, keyless-where-possible** open-source threat intelligence and turns it into a short, executive-readable digest of the last 24 hours of IoC and vulnerability activity.

"OSINT" in the Jarvis sense is narrow: **threat intelligence and indicators of compromise**, not geopolitical OSINT. It answers "what new vulnerabilities are being exploited, what new malware/C2 infrastructure appeared, and what should Graham flag for the security team to chase." News-style cybersecurity journalism (Krebs, BleepingComputer, etc.) lives in its sibling plugin [`plugin-cybersec-news.md`](./plugin-cybersec-news.md) — this one deals with raw feeds, not articles.

### Success criteria

- The morning brief has a `Threat Intel` section with at most a handful of bullets: new KEV entries, notable new critical CVEs, and the few malicious URLs / IOCs that stand out from the volume.
- Runs with zero paid accounts. A fully-free configuration produces a useful section; optional API keys only lift caps.
- A source being down (CISA, NVD, abuse.ch, OTX) drops that source's sub-section with a "(unavailable)" note — the rest of the section still ships.
- No attempt at alerting or blocking — the plugin reports what's new and lets the human triage.

### Non-goals

- IOC enrichment, pivoting, or correlation across sources. Each source is summarized on its own.
- Writing IOCs to a SIEM, TIP, or any downstream system.
- Geopolitical OSINT / social media monitoring / dark-web crawling.
- Paid feeds (Mandiant, Recorded Future, VirusTotal Intelligence, etc.).
- Duplicating the `news` plugin's job — see `plugin-cybersec-news.md`.

---

## 2. Source selection

The threat-intel feed ecosystem is crowded and dominated by paid offerings. The plugin leans on a short list of high-signal, free feeds that are either keyless or offer a free API key with generous limits. Each source is cheap to query and returns a compact payload on the 24-hour scale.

### Sources chosen

| Source | What it gives us | Auth | Update cadence | Why it's in the mix |
|--------|------------------|------|----------------|---------------------|
| **CISA KEV** | Vulnerabilities actually known to be exploited in the wild, with remediation deadlines for federal agencies. | None | Added ad-hoc; typically US business hours weekdays | Highest-signal single feed in public existence. New KEV entry = active exploitation confirmed. |
| **NVD CVE 2.0** | Newly-published or modified CVE records (we filter to CVSS ≥ 7.0). | Optional API key | Continuous; public rate limit 5 req / 30s, 50 req / 30s with key | Covers the disclosure firehose. Filtered hard to avoid drowning the prompt. |
| **abuse.ch URLhaus** | Recently-submitted malware-distribution URLs. | None | Continuous | No-key, high-volume IoC stream. Community-verified. |
| **abuse.ch ThreatFox** | IoCs (IP/domain/hash/URL) tagged by malware family. | Free Auth-Key | Continuous | Covers the IoC space URLhaus doesn't — C2s, file hashes, named campaigns. |
| **abuse.ch Feodo Tracker** | Botnet C2 IPs (Dridex, Emotet, TrickBot descendants, QakBot, etc.). | None | Continuous | Small, focused, high-precision. Cheap to pull. |
| **AlienVault OTX** (optional) | New community "pulses" (threat reports with bundled IoCs) from subscribed authors. | Free API key | Continuous | Provides narrative framing around IoCs. Only queried when `OSINT_OTX_API_KEY` is set. |

### Sources considered and deliberately excluded

- **AbuseIPDB.** Free tier is 1,000 lookups/day — good for enrichment of a known IP, poor for "what's new today." Not a feed. Skip.
- **GreyNoise Community API.** Same problem: it's a lookup API, not a new-events feed. Useful for enrichment in a different plugin.
- **MITRE CVE (cve.org).** Source of truth, but NVD is the enriched, scored, queryable mirror that fits the "last-24h" shape. No reason to hit both.
- **Spamhaus DROP/EDROP.** Long-lived blocklists, not a daily-events feed. Changes too slowly to be a morning-brief signal.
- **PhishTank.** Stagnant-feeling and the public dumps are large; URLhaus covers the "recent malicious URL" niche with better freshness.
- **VulnCheck KEV / NVD++.** Higher-quality mirrors of CISA/NVD, but gated behind a login (and some features behind paid plans). Stick with the authoritative free originals.
- **OpenCTI / MISP public instances.** Aggregator platforms, not feeds. Overkill for a morning brief.

---

## 3. What the plugin pulls

The plugin's `fetch()` runs all source queries concurrently with `asyncio.gather`. Each sub-fetch is wrapped so that an individual source failure degrades that section only; the combined payload still returns.

### 3.1 CISA KEV

- **Endpoint:** `https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json`
- **Filter:** `dateAdded >= now - RUN_WINDOW_HOURS`.
- **Fields kept:** `cveID`, `vendorProject`, `product`, `vulnerabilityName`, `dateAdded`, `shortDescription`, `requiredAction`, `dueDate`, `knownRansomwareCampaignUse`, `cwes`.
- **Volume:** 0–5 entries per day is typical. No chunking ever required.

### 3.2 NVD CVE 2.0

- **Endpoint:** `https://services.nvd.nist.gov/rest/json/cves/2.0`
- **Query params:** `lastModStartDate=<ISO8601 window start>`, `lastModEndDate=<ISO8601 window end>`, `resultsPerPage=2000`.
- **Client-side filter after fetch:** drop anything with CVSS v3.1 base score `< OSINT_NVD_MIN_CVSS` (default `7.0`). Drop CVEs with `vulnStatus == "Rejected"`. Drop CVEs where every CPE match is tagged `deprecated`.
- **Fields kept:** `id`, `published`, `lastModified`, CVSS v3.1 base score + severity, top-level `description` (English), `weaknesses`, `references[0..2]`.
- **Rate-limiting:** one request per run, authenticated with `OSINT_NVD_API_KEY` if set (lifts the unauthenticated 5-req/30s window — overkill for us but more polite). NVD occasionally 503s under load; the fetch retries twice with 10s backoff.
- **Volume caveat:** even with CVSS ≥ 7.0, NVD can produce 50–150 records for a 24h window. The payload is capped at `OSINT_NVD_MAX_CVES` (default 40), sorted by CVSS score descending, then recency.

### 3.3 abuse.ch URLhaus

- **Endpoint:** `https://urlhaus-api.abuse.ch/v1/urls/recent/` with `limit=<OSINT_URLHAUS_LIMIT or 100>`.
- **Filter:** `date_added >= now - RUN_WINDOW_HOURS`.
- **Fields kept:** `url` (defanged in the payload — see §6), `host`, `url_status`, `threat`, `tags`, `reporter`, `date_added`, `urlhaus_reference`.
- **Volume:** URLhaus can add hundreds of URLs per day. Capped at `OSINT_URLHAUS_MAX_ITEMS` (default 50) newest-first after window filtering.

### 3.4 abuse.ch ThreatFox

- **Endpoint:** `https://threatfox-api.abuse.ch/api/v1/` (POST)
- **Request body:** `{"query": "get_iocs", "days": 1}` — ThreatFox does not support sub-day windows. For `RUN_WINDOW_HOURS < 24` we still request `days=1` and filter client-side on `first_seen`.
- **Auth:** HTTP header `Auth-Key: <OSINT_THREATFOX_API_KEY>`. The plugin fails soft (section shows "unavailable — auth key not configured") rather than hard-failing the run if the key is missing; this keeps the fully-free configuration viable.
- **Fields kept:** `ioc`, `ioc_type`, `threat_type`, `malware` (name), `malware_alias`, `confidence_level`, `first_seen`, `tags`, `reference`.
- **Cap:** `OSINT_THREATFOX_MAX_ITEMS` (default 50) newest-first.

### 3.5 abuse.ch Feodo Tracker

- **Endpoint:** `https://feodotracker.abuse.ch/downloads/ipblocklist.json`
- **Filter:** `first_seen >= now - RUN_WINDOW_HOURS`.
- **Fields kept:** `ip_address` (defanged), `port`, `status`, `hostname`, `malware`, `first_seen`, `last_online`, `as_number`, `as_name`, `country`.
- **Volume:** usually 0–30 new C2s per day. No cap needed.

### 3.6 AlienVault OTX (optional)

- **Endpoint:** `https://otx.alienvault.com/api/v1/pulses/subscribed?modified_since=<ISO8601 window start>&limit=50`
- **Auth:** HTTP header `X-OTX-API-KEY: <OSINT_OTX_API_KEY>`. Skipped silently if not set.
- **Fields kept per pulse:** `id`, `name`, `description` (trimmed to 500 chars), `tags`, `adversary`, `targeted_countries`, `industries`, `created`, `modified`, `indicator_count`, `references[0..2]`. **IOC contents of the pulse are not expanded** — we'd blow the token budget. The prompt gets counts and metadata, not raw lists.

---

## 4. Configuration — plugin-local env vars

All `osint`-owned env vars are prefixed `OSINT_`. Nothing outside that prefix or the shared `GROQ_*` / `SLACK_*` / `RUN_WINDOW_HOURS` space is read.

```
# --- OSINT (threat intel) ---
# Source toggles — set any to "false" to skip that source in a given deployment.
OSINT_SOURCES=cisa_kev,nvd,urlhaus,threatfox,feodo,otx

# CISA KEV — no configuration. Either "cisa_kev" is in OSINT_SOURCES or it isn't.

# NVD
OSINT_NVD_API_KEY=                          # optional; lifts public rate limit
OSINT_NVD_MIN_CVSS=7.0                      # drop CVEs below this base score
OSINT_NVD_MAX_CVES=40                       # cap after filtering

# abuse.ch URLhaus
OSINT_URLHAUS_LIMIT=100                     # passed to the API
OSINT_URLHAUS_MAX_ITEMS=50                  # cap after window filtering

# abuse.ch ThreatFox
OSINT_THREATFOX_API_KEY=                    # free Auth-Key from abuse.ch account
OSINT_THREATFOX_MAX_ITEMS=50

# abuse.ch Feodo Tracker — no configuration.

# AlienVault OTX
OSINT_OTX_API_KEY=                          # free key from OTX account; leave blank to skip
```

All OSINT env vars are optional in the sense that the plugin starts cleanly without any of them set — sources without required credentials simply don't run. The `required_env_vars` list in the plugin contract is therefore empty; the plugin validates its own source-level preconditions inside `fetch()`.

---

## 5. Payload shape (plugin-defined)

```json
{
  "window_hours": 24,
  "generated_at": "2026-04-23T10:00:00Z",
  "sources": {
    "cisa_kev":  { "status": "ok", "count": 2,  "items": [ /* ... */ ] },
    "nvd":       { "status": "ok", "count": 37, "truncated": false, "items": [ /* ... */ ] },
    "urlhaus":   { "status": "ok", "count": 50, "truncated": true,  "items": [ /* ... */ ] },
    "threatfox": { "status": "skipped", "reason": "no auth key" },
    "feodo":     { "status": "ok", "count": 11, "items": [ /* ... */ ] },
    "otx":       { "status": "ok", "count": 4,  "items": [ /* ... */ ] }
  }
}
```

Per-source `items` entries are the trimmed records described in §3. Each source declares its own item shape; the prompt (§7) handles the mixed payload by iterating over `sources`.

### Per-source item examples

**cisa_kev item:**

```json
{
  "cve":        "CVE-2026-12345",
  "vendor":     "Acme",
  "product":    "EdgeGateway",
  "name":       "Acme EdgeGateway Authentication Bypass",
  "added":      "2026-04-22",
  "due":        "2026-05-13",
  "ransomware": true,
  "description":"A flaw in the admin API allows unauthenticated access...",
  "action":     "Apply updates per vendor instructions.",
  "cwes":       ["CWE-287"]
}
```

**nvd item:**

```json
{
  "cve":         "CVE-2026-45678",
  "cvss":        9.8,
  "severity":    "CRITICAL",
  "published":   "2026-04-22T14:12:00Z",
  "description": "Buffer overflow in Foo Bar 1.2.3 allows...",
  "weaknesses":  ["CWE-120"],
  "references":  ["https://vendor.example/advisory/..."]
}
```

**urlhaus item:**

```json
{
  "url":       "hxxp://malicious[.]example/path",
  "host":      "malicious[.]example",
  "threat":    "malware_download",
  "tags":      ["lumma", "exe"],
  "status":    "online",
  "added":     "2026-04-23T02:14:00Z",
  "reference": "https://urlhaus.abuse.ch/url/1234567/"
}
```

**threatfox item:**

```json
{
  "ioc":        "194[.]0[.]2[.]45",
  "ioc_type":   "ip:port",
  "threat":     "botnet_cc",
  "malware":    "AsyncRAT",
  "confidence": 90,
  "first_seen": "2026-04-23T04:22:00Z",
  "tags":       ["asyncrat", "c2"],
  "reference":  "https://threatfox.abuse.ch/ioc/9876543/"
}
```

**feodo item:**

```json
{
  "ip":         "203[.]0[.]113[.]44",
  "port":       443,
  "malware":    "QakBot",
  "first_seen": "2026-04-23T07:01:00Z",
  "asn":        "AS64500",
  "as_name":    "Example Hosting LLC",
  "country":    "RU"
}
```

**otx item:**

```json
{
  "id":               "6620abc123456789",
  "name":             "New Lumma Stealer campaign targeting European orgs",
  "description":      "Campaign observed from 2026-04-20 onward targeting...",
  "adversary":        "",
  "targeted_countries": ["DE", "FR", "NL"],
  "industries":       ["Finance"],
  "tags":             ["lumma", "infostealer"],
  "indicator_count":  47,
  "modified":         "2026-04-23T06:30:00Z",
  "references":       ["https://example.com/report/..."]
}
```

---

## 6. Payload handling

### 6.1 Defanging

All IP addresses, domains, and URLs in the payload are **defanged** before being sent to Groq (`.` → `[.]`, `http` → `hxxp`). This serves two purposes:

1. Prevents any downstream Slack client, preview-bot, or inference provider's logging pipeline from auto-fetching a live malicious URL.
2. Makes it obvious at a glance, in the Slack message, that a string is being called out as malicious rather than shared as a reference.

Defanging is done by the plugin itself in a small helper under `plugins/osint/` and lives inside `fetch()` — it's not a cross-cutting core concern.

### 6.2 Token budget and chunking

The full payload after caps is bounded at roughly:

- CISA KEV: typically ≤ 1k tokens
- NVD (40 items × ~80 tokens): ≤ 3.5k tokens
- URLhaus (50 × ~40): ≤ 2.5k tokens
- ThreatFox (50 × ~50): ≤ 3k tokens
- Feodo: ≤ 1k tokens
- OTX (~10 pulses at metadata-only): ≤ 1.5k tokens

Total worst-case: ~12k tokens, comfortably under the default `llama-3.3-70b-versatile` context window. **No map-reduce chunker needed**; the default JSON-array chunker would mis-shape this payload anyway since it's a dict-of-lists. If a future deployment blows the budget (e.g. NVD caps raised), the plugin should ship a custom `chunker.py` that splits per source rather than per record.

### 6.3 Redaction

`redact()` is a no-op. Threat intel data is already public by construction — it's the whole point — and there are no secrets, account IDs, or personal data that could leak. The standard `jarvis/core/redaction.py` regex pass (AWS keys, JWTs, etc.) is not composed in; there's nothing plausible to catch.

### 6.4 Inference parameters

- `temperature: 0.1` — factual, numerical. The prompt must not invent CVE numbers.
- `max_tokens: 600` — the output is a short section.
- `model_override: None` — use the run's `GROQ_MODEL` default.

---

## 7. Prompt focus

Prompt lives at `plugins/osint/prompt.md` and must produce output in the [§3.4 output contract](./initial-spec.md#34-summarizer) of the initial spec.

**Angle:** "Here's what's new in public threat-intel feeds in the last 24 hours, ranked by what most plausibly needs eyes today."

**Prompt instructions (summary):**

- Open with a one-line headline: total counts across sources, e.g. _"2 new KEV entries, 37 critical CVEs, 11 new botnet C2s, 4 new OTX pulses."_
- Lead with **CISA KEV** — each new entry gets its own bullet with CVE, product, and the ransomware-flag if set. KEV entries are always individually listed.
- Then **critical CVEs from NVD**: pick the 3–5 highest-CVSS items that aren't already a KEV entry and bullet them with `CVE — score — one-line description`. Do not list all 40.
- Then **infrastructure activity**: one combined bullet line per source describing volume and any notable clusters (e.g. _"ThreatFox added 38 new AsyncRAT IoCs overnight"_). Do not dump IP lists into the digest — if the operator wants them they'll click through.
- Under **Attention**, flag: any KEV with `ransomware: true`, any NVD CVE with CVSS ≥ 9.5, any cluster of 10+ IoCs tied to a single malware family, or any OTX pulse whose `targeted_industries` overlaps `["Finance"]` . These criteria are spelled out in the prompt text, not in code — the LLM applies them.
- Do not editorialize, do not add remediation advice beyond what the source provides verbatim, and do not link to sources that aren't in the payload.

IoC values referenced in the output must remain defanged — the prompt reinforces this since the payload is already defanged.

---

## 8. Authentication

`plugins/osint/auth.py` returns a small dataclass of configured clients — one `httpx.AsyncClient` per source, each pre-configured with the appropriate base URL, headers, and timeout. No OAuth flows, no refresh dance, no `setup.py`. The handful of free API keys are passed via env vars and injected as headers at construction time.

```python
# plugins/osint/auth.py (sketch)
@dataclass
class OSINTClients:
    kev:       httpx.AsyncClient   # no auth
    nvd:       httpx.AsyncClient   # optional apiKey query param
    urlhaus:   httpx.AsyncClient   # no auth
    threatfox: Optional[httpx.AsyncClient]  # None if no auth key
    feodo:     httpx.AsyncClient   # no auth
    otx:       Optional[httpx.AsyncClient]  # None if no API key

async def get_authenticated_client() -> OSINTClients: ...
```

The plugin's `fetch()` iterates through `OSINT_SOURCES`, skips sources whose client is `None`, and records a `"status": "skipped"` entry in the payload for them.

---

## 9. Reliability & failure modes

| Failure | Behavior |
|---------|----------|
| A single source times out or 5xx's | That source's `status` becomes `error`, rest of the payload proceeds |
| All sources fail | Plugin returns a `FetchResult` with all statuses `error`; the digest section shows "Threat Intel — all sources unavailable" |
| NVD 503 (common) | Two retries with 10s backoff, then drop to `error` |
| ThreatFox auth rejected | Source marked `status: skipped` with `reason: "auth rejected"` — not a hard failure |
| Payload bigger than expected | Per-source caps already bound it; if a cap is raised and we blow context, ship a per-source chunker |
| CISA KEV schema changes | Schema has been stable for years; if it breaks, the source degrades to `error` and the rest of the brief is unaffected |

Every source fetch is wrapped in a `try/except` inside `fetch()` and never propagates an exception out of the plugin; the orchestrator therefore never sees this plugin as a timeout/crash even when individual feeds are broken.

---

## 10. Testing

- **Fixtures:** `plugins/osint/fixtures/` holds one recorded JSON response per source — KEV, NVD, URLhaus, ThreatFox, Feodo, OTX. These are real public responses lightly trimmed; nothing sensitive, so safe to commit.
- **Unit tests:** per-source parser tests run against the fixtures; defanging helper has its own coverage.
- **Contract test:** the shared plugin-contract test (every plugin runs with mock env and satisfies the `DataSourcePlugin` ABC) applies unchanged.
- **Integration test:** `test_osint_plugin.py` drives `fetch()` with all sources mocked to return fixtures, asserts the merged payload shape and that a disabled/unauthed source shows `status: skipped` rather than crashing.

---

## 11. Open questions

- **Is the free ThreatFox Auth-Key worth requiring?** It's free but gate-kept behind a forum account. If it becomes friction, drop ThreatFox from the default source list and lean on URLhaus + Feodo. (Leaning toward: keep it optional, as specified.)
- **Do we ever want to enrich (e.g. VirusTotal lookups)?** No in v1. If a future version lets the operator click an IoC and get a threaded enrichment, that's a different plugin.
- **Should NVD filter by `cveTags` or `vulnStatus == "Analyzed"` only?** Currently we filter only on CVSS and rejection. May need tightening if early-analysis noise dominates the prompt.
