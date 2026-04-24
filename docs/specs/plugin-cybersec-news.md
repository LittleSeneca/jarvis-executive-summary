# Jarvis Plugin Spec — `cybersec_news`

**Status:** Draft v0.1
**Owner:** operator-defined
**Last updated:** 2026-04-23
**Plugin name:** `cybersec_news`
**Display name:** Cybersec News
**Scope:** plugin-local. This document is subordinate to [`initial-spec.md`](./initial-spec.md) — when the two disagree, the initial spec wins.

---

## 1. Purpose

A daily roundup of the last 24 hours of **cybersecurity journalism**: what has the security press reported overnight — breaches, new malware campaigns covered by reporters, vendor zero-days, regulatory moves, industry drama, etc. This plugin reads from a curated set of free RSS feeds, dedupes across outlets, and produces a short "Cybersec News" section in the morning brief.

This is the journalism sibling to the [`osint`](./plugin-osint.md) plugin:

- **`osint`** = raw public feeds (CISA KEV, NVD, abuse.ch, OTX). "What IoCs appeared."
- **`cybersec_news`** = human-written reporting. "What did BleepingComputer and Krebs write about."

Overlap is expected and desirable — the same breach will show up as a NVD CVE in `osint` and a Dark Reading article in `cybersec_news` — and the prompt is written to complement, not duplicate, `osint`'s framing.

### Success criteria

- The morning brief has a `Cybersec News` section of 4–8 bullets that capture what the security press is paying attention to overnight.
- **Stories covered by multiple outlets float to the top.** A breach reported by Krebs, BleepingComputer, and The Record is a stronger signal than a single-outlet blog post.
- Runs with zero paid accounts, zero API keys. All sources are public RSS.
- Adding or removing a feed is an env-var edit, not a code change.
- A single outlet being down (or its RSS 500ing for a day) drops its contribution; other feeds still report.

### Non-goals

- Full-text article ingestion. Only what the RSS item carries (title + summary/description) is sent to the LLM.
- Paywall bypasses of any kind. If an outlet gates its RSS summaries, the summary is whatever the outlet chooses to publish.
- Per-article sentiment or "bias" analysis. The prompt describes what was reported; it does not characterize outlets.
- Threat-intel feeds (see `plugin-osint.md`) — this plugin is journalism-only.
- Aggregating the general-news `news` plugin's output. These are two different sections.

---

## 2. Relationship to the existing `news` plugin

The general-news `news` plugin already ships an RSS aggregator (`§6.8` of the initial spec) with cross-outlet dedupe, per-feed caps, and a widely-covered-story signal. Rather than re-invent that mechanism, **`cybersec_news` reuses the same shape**:

- Same fetch pattern: parallel `httpx` + `feedparser`, per-feed timeout, items capped per feed.
- Same dedupe strategy: Jaccard similarity over normalized title tokens, merge duplicates into one item carrying multiple sources.
- Same payload shape (see §5) — the two plugins are interchangeable in structure, distinct in data and prompt.

They are nonetheless **two plugins, not one plugin reading two feed lists**, because:

1. Each gets its own section and header in the Slack digest.
2. Each has a different prompt angle (general-world vs. industry-technical).
3. Each has a different default feed list curated for its domain.
4. Separation lets the operator disable one without the other — a Slack digest that's lost its RSS feed ingestion entirely would be painful to debug if both were jammed into the same plugin.

If the two plugins' code grows more than trivially duplicative, the shared RSS-aggregator logic should move into a small helper under `plugins/_rss/` (or into `jarvis/core/` if a third RSS-based plugin ever appears — per "duplicate twice before abstracting"). **Do not** pre-emptively build that helper for the first two plugins.

---

## 3. Source selection

Feed list was selected to balance: (a) high signal-to-noise for a morning exec brief, (b) independence from any single ownership or vendor, (c) breadth — investigative journalism, breaking news, enterprise-focused coverage, and thoughtful commentary — and (d) reliable, stable, keyless RSS.

### Default feed list

Shipped in `.env.example` as the default `CYBERSEC_NEWS_FEEDS` value:

| Outlet | Feed URL | Style / angle |
|--------|----------|---------------|
| **Krebs on Security** | `https://krebsonsecurity.com/feed/` | Investigative, cybercrime and fraud focus. Low volume, very high signal. |
| **BleepingComputer** | `https://www.bleepingcomputer.com/feed/` | High-volume breaking news: ransomware incidents, new malware, patches. |
| **The Hacker News** | `https://feeds.feedburner.com/TheHackersNews` | Aggregator-style daily roundup. Big volume; great for coverage signal. |
| **Dark Reading** | `https://www.darkreading.com/rss.xml` | Enterprise CISO audience. Heavier on analysis, lighter on breaking alerts. |
| **The Register — Security** | `https://www.theregister.com/security/headlines.atom` | UK industry coverage with an editorial voice. Often first on vendor screw-ups. |
| **The Record** | `https://therecord.media/feed` | Recorded Future's news arm. Strong on nation-state and policy reporting. |
| **SecurityWeek** | `https://www.securityweek.com/feed/` | Vendor-and-disclosure-heavy, but broad coverage. |
| **Schneier on Security** | `https://www.schneier.com/feed/atom/` | Low-volume, policy and cryptography commentary. |

Deliberately mixed across investigative (Krebs, The Record), breaking-news (BleepingComputer, Hacker News), enterprise (Dark Reading, SecurityWeek), and commentary (Register, Schneier). An outlet reports ransomware attacks? A second reports vendor exploitation? A third reports the policy response? The cross-outlet dedupe surfaces the stories that hit all three.

### Sources considered and deliberately excluded

- **Threatpost.** Defunct — no longer publishing.
- **SC Magazine / SC Media.** RSS exists but is inconsistent; content overlaps heavily with SecurityWeek.
- **WIRED Security.** Strong reporting but the `/threatlevel/` RSS is not reliably maintained; the general WIRED feed dilutes the cybersec signal too much.
- **NYT Cybersecurity.** Paywalled summaries; RSS carries only teaser text that isn't informative to the LLM.
- **Vendor blogs (Mandiant, Unit 42, Talos, CrowdStrike).** Excellent content but they each have a vendor angle and their posts are typically long-form research rather than 24h-pacing news. A `vendor_research` plugin could pull these separately; keeping this plugin journalism-only avoids confusion.
- **Hacker News (ycombinator).** Good signal for dev-adjacent security news, but Hacker News is not a cybersec outlet — using its front page as a source would dilute the scope. The existing general `news` plugin is a better home if someone wants it.
- **Reddit `r/netsec`, `r/cybersecurity`.** RSS exists but the signal is buried in low-effort posts; curation overhead outweighs the value.

---

## 4. Configuration — plugin-local env vars

All `cybersec_news` env vars are prefixed `CYBERSEC_NEWS_`. The shape mirrors the `NEWS_*` vars from the initial spec.

```
# --- Cybersec News (RSS aggregator) ---
# Comma-separated RSS feed URLs. The plugin reads <channel><title> from each feed
# for its label. Add/remove feeds by editing this list — no code change.
CYBERSEC_NEWS_FEEDS=https://krebsonsecurity.com/feed/,https://www.bleepingcomputer.com/feed/,https://feeds.feedburner.com/TheHackersNews,https://www.darkreading.com/rss.xml,https://www.theregister.com/security/headlines.atom,https://therecord.media/feed,https://www.securityweek.com/feed/,https://www.schneier.com/feed/atom/

CYBERSEC_NEWS_ITEMS_PER_FEED=10     # cap per source so one prolific outlet can't dominate
CYBERSEC_NEWS_DEDUPE=true           # collapse near-duplicate headlines across feeds
CYBERSEC_NEWS_FETCH_TIMEOUT=10      # per-feed HTTP timeout in seconds
```

`required_env_vars = ["CYBERSEC_NEWS_FEEDS"]` — if the feed list is missing, the loader hard-fails before any network call, matching the "fail loud on config" principle. The other vars have defaults.

---

## 5. Payload shape (plugin-defined)

Identical in structure to the general `news` plugin so reviewers can read both at a glance:

```json
{
  "window_hours": 24,
  "feed_count":   8,
  "items": [
    {
      "title":     "ClownFlare confirms customer data exposed in March breach",
      "summary":   "Summary lifted from the RSS <description> field, HTML stripped.",
      "published": "2026-04-22T21:15:00Z",
      "sources":   [
        { "outlet": "Krebs on Security",  "url": "https://krebsonsecurity.com/..." },
        { "outlet": "BleepingComputer",   "url": "https://www.bleepingcomputer.com/..." },
        { "outlet": "The Record",         "url": "https://therecord.media/..." }
      ],
      "source_count": 3
    }
  ]
}
```

Items are sorted by `source_count` descending, then by `published` descending.

### 5.1 Fetching

- All feeds fetched concurrently via `httpx.AsyncClient` + `feedparser`.
- Per-feed timeout: `CYBERSEC_NEWS_FETCH_TIMEOUT` (default 10s).
- Each feed contributes up to `CYBERSEC_NEWS_ITEMS_PER_FEED` (default 10) of its newest items whose `published` falls within `RUN_WINDOW_HOURS`.
- HTML in RSS descriptions is stripped with a small local helper (or `bleach` if already a dep; prefer not adding one for a one-liner).
- `User-Agent` is set explicitly (e.g. `Jarvis/0.1 (executive-summary-bot)`). Several of these outlets 403 default `httpx` UAs.

### 5.2 Dedupe

When `CYBERSEC_NEWS_DEDUPE=true` (default), the plugin merges items whose normalized titles have Jaccard similarity ≥ 0.6. Normalization: lowercase, strip punctuation, drop the outlet's name if it appears in the title, drop common filler tokens (`report`, `update`, `breaking`, etc. — a small stop-list kept in `plugins/cybersec_news/_dedupe.py`).

When items merge, `sources` accumulates, `source_count` is the accumulator, and the earliest `published` wins. The `title` and `summary` come from the outlet with the longest summary (more context for the prompt).

### 5.3 Redaction

`redact()` is a no-op. All input is already public journalism. The standard `jarvis/core/redaction.py` scrub is not composed in.

### 5.4 Inference parameters

- `temperature: 0.2` — consistent with the general `news` plugin.
- `max_tokens: 700` — the section is slightly denser than general news because headlines carry more technical detail.
- `model_override: None` — use the run's `GROQ_MODEL` default.

---

## 6. Payload handling

Typical size, 8 feeds × 10 items with moderate summary length, is 4–8k tokens after dedupe. Comfortably inside context; no chunking needed. The core's default JSON-array chunker (split on top-level array elements) Just Works if someone adds enough feeds to exceed the budget — which should not happen with the default list.

---

## 7. Prompt focus

Prompt lives at `plugins/cybersec_news/prompt.md` and must produce output in the [§3.4 output contract](./initial-spec.md#34-summarizer) of the initial spec.

**Angle:** "Here's what the security press wrote about overnight, weighted toward stories multiple outlets are covering, avoiding duplication of the `Threat Intel` section that precedes this one."

**Prompt instructions (summary):**

- **Lead** with the 2–3 stories with the highest `source_count`. For each, include the one-line headline and which outlets covered it (e.g. _"ClownFlare data exposure — per Krebs, BleepingComputer, The Record"_).
- **Then** 3–5 additional bullets from single-outlet items that still look meaningful — new vulnerability disclosures, policy/regulatory news, notable incident reporting.
- **Do not duplicate** items already likely reported in the `Threat Intel` section. If a bullet is essentially _"CVE-2026-12345 published"_ and that CVE appeared in this morning's KEV or NVD pull, drop it — the journalism angle is redundant. (This dedup is advisory in the prompt; the plugin does not cross-reference payloads between plugins.)
- **Do not editorialize**, do not characterize outlets (no "the left-leaning Guardian" / "the conservative Register" framing — these are tech outlets and the kind of political framing the general `news` plugin also avoids).
- Under **Attention**, flag: any story explicitly naming your organization, any story about a vendor matching your organization is known to use (the prompt doesn't have a vendor list; the LLM uses context from the payload only), any disclosed active exploitation that isn't already in the KEV, any major breach (>1M records).
- Keep the total output to ≤ 8 bullets.

---

## 8. Authentication

`plugins/cybersec_news/auth.py` returns an `httpx.AsyncClient` with:

- A descriptive `User-Agent` header.
- A reasonable default timeout.
- No headers, no keys, no tokens, no OAuth.

Effectively a no-op, like the `news` and `trump` plugins. No `setup.py`.

---

## 9. Reliability & failure modes

| Failure | Behavior |
|---------|----------|
| A single feed times out or 5xx's | That feed contributes zero items; other feeds still report |
| All feeds fail | Plugin returns a `FetchResult` with `items: []` and metadata noting the outage; the digest section reads "Cybersec News — all feeds unavailable" |
| RSS includes malformed dates | Item is dropped silently; no crashing on a vendor's accidentally-broken feed |
| Feed returns HTML content-type despite the RSS URL | Feed contributes zero items; logged at `WARNING` once per run |
| Dedupe algorithm merges things it shouldn't | Operator disables with `CYBERSEC_NEWS_DEDUPE=false`; each outlet's item stands alone |
| Outlet moves their RSS | Update `CYBERSEC_NEWS_FEEDS` — no code change required |

Every feed fetch is wrapped in `try/except` and never propagates out of the plugin.

---

## 10. Testing

- **Fixtures:** `plugins/cybersec_news/fixtures/` holds one recorded RSS XML blob per default outlet, trimmed to 3–5 items each. Safe to commit — already public.
- **Unit tests:** dedupe Jaccard math, HTML-stripping helper, per-feed parsing.
- **Contract test:** standard plugin-contract test applies.
- **Integration test:** drives `fetch()` with all outlets mocked to serve their fixtures, asserts the merged payload has `source_count` set correctly for the intentionally-overlapping fixture item ("a fake story planted in 3 fixtures to verify dedupe").

---

## 11. Open questions

- **Should we cap total items post-dedupe?** The general `news` plugin doesn't — it leans on the prompt to pick 6–10. Behavior for `cybersec_news` is the same until proven otherwise.
- **Do we want a small allow/deny list for outlet domains referenced in summaries?** No in v1. If an outlet is untrustworthy, remove it from `CYBERSEC_NEWS_FEEDS`.
- **Is Schneier's low volume worth including at all?** Probably yes — he posts ~3x/week and when he does it's high-signal commentary that the other outlets don't produce. Will revisit if he's consistently silent.
- **Do we want to enrich items with the CVE IDs they mention (regex over the summary) and cross-reference the `osint` CVE list in-prompt?** Not in v1 — that's the kind of cross-plugin state Jarvis deliberately avoids. The prompt's "don't duplicate threat-intel" instruction is soft; if it's not enough, revisit later.
