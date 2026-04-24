"""OSINT plugin — multi-source threat intelligence digest.

Fetches the last ``window_hours`` of data from up to six public/free-tier
threat intelligence feeds concurrently:

  - CISA Known Exploited Vulnerabilities (KEV)
  - NVD CVE 2.0
  - abuse.ch URLhaus
  - abuse.ch ThreatFox
  - abuse.ch Feodo Tracker
  - AlienVault OTX

Each source is isolated in its own async function. A failure in one source sets
``status: "error"`` for that source but never raises — the plugin only raises
``PluginFetchError`` when every enabled source fails or an unexpected error
occurs.
"""

import asyncio
import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from jarvis.core.exceptions import PluginFetchError
from jarvis.core.plugin import DataSourcePlugin, FetchResult

from .auth import OSINTClients, get_authenticated_clients

__all__ = ["OSINTPlugin"]

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Source URLs
# ---------------------------------------------------------------------------

_CISA_KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
_NVD_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"
_URLHAUS_URL = "https://urlhaus-api.abuse.ch/v1/urls/recent/"
_THREATFOX_URL = "https://threatfox-api.abuse.ch/api/v1/"
_FEODO_URL = "https://feodotracker.abuse.ch/downloads/ipblocklist.json"
_OTX_URL = "https://otx.alienvault.com/api/v1/pulses/subscribed"

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

_DEFAULT_SOURCES = "cisa_kev,nvd,urlhaus,threatfox,feodo,otx"


def _enabled_sources() -> set[str]:
    raw = os.environ.get("OSINT_SOURCES", _DEFAULT_SOURCES)
    return {s.strip() for s in raw.split(",") if s.strip()}


def _nvd_min_cvss() -> float:
    try:
        return float(os.environ.get("OSINT_NVD_MIN_CVSS", "7.0"))
    except ValueError:
        return 7.0


def _nvd_max_cves() -> int:
    try:
        return int(os.environ.get("OSINT_NVD_MAX_CVES", "40"))
    except ValueError:
        return 40


def _urlhaus_limit() -> int:
    try:
        return int(os.environ.get("OSINT_URLHAUS_LIMIT", "100"))
    except ValueError:
        return 100


def _urlhaus_max_items() -> int:
    try:
        return int(os.environ.get("OSINT_URLHAUS_MAX_ITEMS", "50"))
    except ValueError:
        return 50


def _threatfox_max_items() -> int:
    try:
        return int(os.environ.get("OSINT_THREATFOX_MAX_ITEMS", "50"))
    except ValueError:
        return 50


# ---------------------------------------------------------------------------
# Defanging helper
# ---------------------------------------------------------------------------

def _defang(value: str) -> str:
    """Defang a URL or IP/domain so it is safe to display in a brief.

    - ``http`` → ``hxxp``
    - ``https`` → ``hxxps``
    - ``.`` → ``[.]``  (after scheme substitution so ``://`` becomes ``:[//]``
      which is undesirable — we only dot-replace host/path portions)
    """
    if not value:
        return value
    # Replace scheme first to avoid corrupting ://
    value = value.replace("https://", "hxxps://").replace("http://", "hxxp://")
    # Replace remaining dots (in host and path)
    value = value.replace(".", "[.]")
    return value


# ---------------------------------------------------------------------------
# Individual source fetchers
# ---------------------------------------------------------------------------

async def _fetch_cisa_kev(
    client: httpx.AsyncClient,
    window_start: datetime,
) -> dict:
    """Fetch CISA Known Exploited Vulnerabilities added within the window."""
    try:
        resp = await client.get(_CISA_KEV_URL)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.exception("CISA KEV fetch failed")
        return {"status": "error", "reason": str(exc)}

    try:
        items: list[dict] = []
        for vuln in data.get("vulnerabilities", []):
            added_raw = vuln.get("dateAdded", "")
            try:
                added = datetime.fromisoformat(added_raw).replace(tzinfo=UTC)
            except ValueError:
                continue
            if added < window_start:
                continue

            cwes_raw = vuln.get("cwes", [])
            cwes = cwes_raw if isinstance(cwes_raw, list) else [cwes_raw] if cwes_raw else []

            items.append(
                {
                    "cve": vuln.get("cveID"),
                    "vendor": vuln.get("vendorProject"),
                    "product": vuln.get("product"),
                    "name": vuln.get("vulnerabilityName"),
                    "added": added_raw,
                    "description": vuln.get("shortDescription"),
                    "action": vuln.get("requiredAction"),
                    "due": vuln.get("dueDate"),
                    "ransomware": vuln.get("knownRansomwareCampaignUse", "Unknown").lower() == "known",
                    "cwes": cwes,
                }
            )

        log.info("CISA KEV: %d entries in window", len(items))
        return {"status": "ok", "count": len(items), "items": items}
    except Exception as exc:
        log.exception("CISA KEV processing failed")
        return {"status": "error", "reason": str(exc)}


async def _fetch_nvd(
    client: httpx.AsyncClient,
    window_start: datetime,
    now: datetime,
    min_cvss: float,
    max_cves: int,
    nvd_key: str,
) -> dict:
    """Fetch recent CVEs from NVD CVE 2.0 API."""
    params: dict[str, str] = {
        "lastModStartDate": window_start.strftime("%Y-%m-%dT%H:%M:%S.000") + " UTC",
        "lastModEndDate": now.strftime("%Y-%m-%dT%H:%M:%S.000") + " UTC",
        "resultsPerPage": "2000",
    }
    if nvd_key:
        params["apiKey"] = nvd_key

    # Retry on 503/429/5xx; fail immediately on other 4xx
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            resp = await client.get(_NVD_URL, params=params)
            if 400 <= resp.status_code < 500 and resp.status_code != 429:
                log.error("NVD returned %d — not retrying", resp.status_code)
                return {"status": "error", "reason": "HTTP %d from NVD API" % resp.status_code}
            if (resp.status_code == 503 or resp.status_code == 429) and attempt < 2:
                log.warning("NVD returned %d, retrying in 10s (attempt %d)", resp.status_code, attempt + 1)
                await asyncio.sleep(10)
                continue
            resp.raise_for_status()
            data = resp.json()
            break
        except Exception as exc:
            last_exc = exc
            if attempt < 2:
                log.warning("NVD fetch error on attempt %d: %s", attempt + 1, exc)
                await asyncio.sleep(10)
            else:
                log.exception("NVD fetch failed after retries")
                return {"status": "error", "reason": str(exc)}
    else:
        return {"status": "error", "reason": str(last_exc)}

    try:
        items: list[dict] = []
        for vuln in data.get("vulnerabilities", []):
            cve = vuln.get("cve", {})

            if cve.get("vulnStatus") in ("Rejected", "Awaiting Analysis", "Undergoing Analysis"):
                continue

            # Extract CVSS v3.1 score and severity
            score: float | None = None
            severity: str | None = None
            metrics = cve.get("metrics", {})
            for metric in metrics.get("cvssMetricV31", []):
                cvss_data = metric.get("cvssData", {})
                raw_score = cvss_data.get("baseScore")
                if raw_score is not None:
                    score = float(raw_score)
                    severity = cvss_data.get("baseSeverity")
                    break

            if score is not None and score < min_cvss:
                continue

            # English description — skip placeholder/reserved entries
            description = ""
            for desc in cve.get("descriptions", []):
                if desc.get("lang") == "en":
                    description = desc.get("value", "")
                    break
            if not description or description.startswith("** "):
                continue

            # Weaknesses
            weaknesses: list[str] = []
            for weakness in cve.get("weaknesses", []):
                for desc in weakness.get("description", []):
                    if desc.get("lang") == "en":
                        weaknesses.append(desc.get("value", ""))

            # First 2 references
            refs = [
                r.get("url") for r in cve.get("references", [])[:2] if r.get("url")
            ]

            items.append(
                {
                    "id": cve.get("id"),
                    "published": cve.get("published"),
                    "cvss_score": score,
                    "cvss_severity": severity,
                    "description": description,
                    "weaknesses": weaknesses,
                    "references": refs,
                }
            )

        # Sort by CVSS desc, cap
        items.sort(key=lambda x: (x["cvss_score"] or 0.0), reverse=True)
        truncated = len(items) > max_cves
        items = items[:max_cves]

        log.info("NVD: %d CVEs in window (after filter, capped at %d)", len(items), max_cves)
        return {
            "status": "ok",
            "count": len(items),
            "truncated": truncated,
            "items": items,
        }
    except Exception as exc:
        log.exception("NVD processing failed")
        return {"status": "error", "reason": str(exc)}


async def _fetch_urlhaus(
    client: httpx.AsyncClient,
    window_start: datetime,
    limit: int,
    max_items: int,
) -> dict:
    """Fetch recent malicious URLs from abuse.ch URLhaus."""
    try:
        resp = await client.get(_URLHAUS_URL, params={"limit": str(limit)})
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.exception("URLhaus fetch failed")
        return {"status": "error", "reason": str(exc)}

    try:
        items: list[dict] = []
        for entry in data.get("urls", []):
            date_added_raw = entry.get("date_added", "")
            try:
                # Format: "2024-01-15 10:00:00 UTC"
                date_added = datetime.strptime(date_added_raw, "%Y-%m-%d %H:%M:%S UTC").replace(
                    tzinfo=UTC
                )
            except ValueError:
                try:
                    date_added = datetime.fromisoformat(date_added_raw.replace(" UTC", "+00:00"))
                except ValueError:
                    continue

            if date_added < window_start:
                continue

            items.append(
                {
                    "url": _defang(entry.get("url", "")),
                    "host": _defang(entry.get("host", "")),
                    "url_status": entry.get("url_status"),
                    "threat": entry.get("threat"),
                    "tags": entry.get("tags") or [],
                    "reporter": entry.get("reporter"),
                    "date_added": date_added_raw,
                    "urlhaus_reference": entry.get("urlhaus_reference"),
                }
            )

            if len(items) >= max_items:
                break

        truncated = len(items) >= max_items
        log.info("URLhaus: %d items in window", len(items))
        return {
            "status": "ok",
            "count": len(items),
            "truncated": truncated,
            "items": items,
        }
    except Exception as exc:
        log.exception("URLhaus processing failed")
        return {"status": "error", "reason": str(exc)}


async def _fetch_threatfox(
    client: httpx.AsyncClient,
    window_start: datetime,
    window_hours: int,
    max_items: int,
) -> dict:
    """Fetch recent IoCs from abuse.ch ThreatFox."""
    try:
        resp = await client.post(_THREATFOX_URL, json={"query": "get_iocs", "days": 1})
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.exception("ThreatFox fetch failed")
        return {"status": "error", "reason": str(exc)}

    try:
        items: list[dict] = []
        for entry in data.get("data", []) or []:
            # Client-side window filter when window < 24h
            if window_hours < 24:
                first_seen_raw = entry.get("first_seen", "")
                try:
                    first_seen = datetime.fromisoformat(first_seen_raw.replace(" ", "T")).replace(
                        tzinfo=UTC
                    )
                    if first_seen < window_start:
                        continue
                except (ValueError, AttributeError):
                    pass

            items.append(
                {
                    "ioc": _defang(entry.get("ioc", "")),
                    "ioc_type": entry.get("ioc_type"),
                    "threat_type": entry.get("threat_type"),
                    "malware": entry.get("malware"),
                    "malware_alias": entry.get("malware_alias"),
                    "confidence_level": entry.get("confidence_level"),
                    "first_seen": entry.get("first_seen"),
                    "tags": entry.get("tags") or [],
                    "reference": entry.get("reference"),
                }
            )

            if len(items) >= max_items:
                break

        log.info("ThreatFox: %d IoCs in window", len(items))
        return {"status": "ok", "count": len(items), "items": items}
    except Exception as exc:
        log.exception("ThreatFox processing failed")
        return {"status": "error", "reason": str(exc)}


async def _fetch_feodo(
    client: httpx.AsyncClient,
    window_start: datetime,
) -> dict:
    """Fetch botnet C2 IPs from abuse.ch Feodo Tracker.

    Returns all currently-online C2s (the actionable intel), with a flag on
    entries first seen within the window. first_seen is when the C2 was
    originally discovered — most entries predate the 24h window, so filtering
    by first_seen alone would return nothing.
    """
    try:
        resp = await client.get(_FEODO_URL)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.exception("Feodo Tracker fetch failed")
        return {"status": "error", "reason": str(exc)}

    try:
        online_items: list[dict] = []
        new_in_window = 0
        malware_counts: dict[str, int] = {}

        for entry in data if isinstance(data, list) else []:
            status = entry.get("status", "")

            first_seen_raw = entry.get("first_seen", "")
            first_seen: datetime | None = None
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
                try:
                    first_seen = datetime.strptime(first_seen_raw, fmt).replace(tzinfo=UTC)
                    break
                except ValueError:
                    continue

            is_new = first_seen is not None and first_seen >= window_start

            malware = entry.get("malware") or "Unknown"
            malware_counts[malware] = malware_counts.get(malware, 0) + 1

            if is_new:
                new_in_window += 1

            if status != "online":
                continue

            online_items.append(
                {
                    "ip_address": _defang(entry.get("ip_address", "")),
                    "port": entry.get("port"),
                    "hostname": entry.get("hostname"),
                    "malware": malware,
                    "first_seen": first_seen_raw,
                    "last_online": entry.get("last_online"),
                    "asn": entry.get("as_number"),
                    "as_name": entry.get("as_name"),
                    "country": entry.get("country"),
                    "new_in_window": is_new,
                }
            )

        # Prioritise newly discovered, then cap to limit token spend
        online_items.sort(key=lambda x: (not x["new_in_window"], x["malware"]))
        capped = online_items[:50]

        log.info(
            "Feodo Tracker: %d online C2s (%d new in window)",
            len(online_items),
            new_in_window,
        )
        return {
            "status": "ok",
            "total_online": len(online_items),
            "new_in_window": new_in_window,
            "malware_counts": malware_counts,
            "items": capped,
        }
    except Exception as exc:
        log.exception("Feodo processing failed")
        return {"status": "error", "reason": str(exc)}


async def _fetch_otx(
    client: httpx.AsyncClient,
    window_start: datetime,
) -> dict:
    """Fetch subscribed OTX pulses modified within the window."""
    params = {
        "modified_since": window_start.strftime("%Y-%m-%dT%H:%M:%S"),
        "limit": "50",
    }
    try:
        resp = await client.get(_OTX_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.exception("AlienVault OTX fetch failed")
        return {"status": "error", "reason": str(exc)}

    try:
        items: list[dict] = []
        for pulse in data.get("results", []):
            description = (pulse.get("description") or "")[:500]
            raw_refs = pulse.get("references") or []
            # OTX references may be plain strings or {"url": "..."} dicts
            refs = [
                (r if isinstance(r, str) else r.get("url", ""))
                for r in raw_refs[:2]
                if r
            ]
            refs = [r for r in refs if r]

            items.append(
                {
                    "id": pulse.get("id"),
                    "name": pulse.get("name"),
                    "description": description,
                    "tags": pulse.get("tags") or [],
                    "adversary": pulse.get("adversary"),
                    "targeted_countries": pulse.get("targeted_countries") or [],
                    "industries": pulse.get("industries") or [],
                    "created": pulse.get("created"),
                    "modified": pulse.get("modified"),
                    "indicator_count": pulse.get("indicator_count", 0),
                    "references": refs,
                }
            )

        log.info("OTX: %d pulses in window", len(items))
        return {"status": "ok", "count": len(items), "items": items}
    except Exception as exc:
        log.exception("OTX processing failed")
        return {"status": "error", "reason": str(exc)}


# ---------------------------------------------------------------------------
# Plugin class
# ---------------------------------------------------------------------------

class OSINTPlugin(DataSourcePlugin):
    """Aggregate threat intelligence from CISA KEV, NVD, URLhaus, ThreatFox, Feodo, and OTX."""

    name = "osint"
    display_name = "Threat Intel"
    required_env_vars: list[str] = []
    temperature = 0.1
    max_tokens = 600

    async def fetch(self, window_hours: int) -> FetchResult:
        """Fetch the last ``window_hours`` of threat intelligence from all enabled sources."""
        now = datetime.now(tz=UTC)
        window_start = now - timedelta(hours=window_hours)
        enabled = _enabled_sources()

        nvd_key = os.environ.get("OSINT_NVD_API_KEY", "").strip()
        threatfox_key = os.environ.get("OSINT_THREATFOX_API_KEY", "").strip()
        otx_key = os.environ.get("OSINT_OTX_API_KEY", "").strip()

        log.info(
            "OSINT fetch starting: window=%dh, sources=%s",
            window_hours,
            sorted(enabled),
        )

        clients: OSINTClients | None = None
        results: tuple = ()
        try:
            clients = await get_authenticated_clients()

            # Build coroutine list — sources not in `enabled` skip immediately.
            async def _maybe_cisa() -> dict:
                if "cisa_kev" not in enabled:
                    return {"status": "skipped", "reason": "not in OSINT_SOURCES"}
                return await _fetch_cisa_kev(clients.kev, window_start)

            async def _maybe_nvd() -> dict:
                if "nvd" not in enabled:
                    return {"status": "skipped", "reason": "not in OSINT_SOURCES"}
                return await _fetch_nvd(
                    clients.nvd,
                    window_start,
                    now,
                    _nvd_min_cvss(),
                    _nvd_max_cves(),
                    nvd_key,
                )

            async def _maybe_urlhaus() -> dict:
                if "urlhaus" not in enabled:
                    return {"status": "skipped", "reason": "not in OSINT_SOURCES"}
                if clients.urlhaus is None:
                    return {"status": "skipped", "reason": "no auth key"}
                return await _fetch_urlhaus(
                    clients.urlhaus,
                    window_start,
                    _urlhaus_limit(),
                    _urlhaus_max_items(),
                )

            async def _maybe_threatfox() -> dict:
                if "threatfox" not in enabled:
                    return {"status": "skipped", "reason": "not in OSINT_SOURCES"}
                if not threatfox_key:
                    return {"status": "skipped", "reason": "no auth key"}
                if clients.threatfox is None:
                    return {"status": "skipped", "reason": "no auth key"}
                return await _fetch_threatfox(
                    clients.threatfox,
                    window_start,
                    window_hours,
                    _threatfox_max_items(),
                )

            async def _maybe_feodo() -> dict:
                if "feodo" not in enabled:
                    return {"status": "skipped", "reason": "not in OSINT_SOURCES"}
                return await _fetch_feodo(clients.feodo, window_start)

            async def _maybe_otx() -> dict:
                if "otx" not in enabled:
                    return {"status": "skipped", "reason": "not in OSINT_SOURCES"}
                if not otx_key:
                    return {"status": "skipped", "reason": "no auth key"}
                if clients.otx is None:
                    return {"status": "skipped", "reason": "no auth key"}
                return await _fetch_otx(clients.otx, window_start)

            results = await asyncio.gather(
                _maybe_cisa(),
                _maybe_nvd(),
                _maybe_urlhaus(),
                _maybe_threatfox(),
                _maybe_feodo(),
                _maybe_otx(),
                return_exceptions=True,
            )

        except Exception as exc:
            log.exception("Catastrophic error during OSINT fetch")
            raise PluginFetchError(f"OSINT fetch failed: {exc}") from exc
        finally:
            if clients is not None:
                # Close all open clients
                for field_name in ("kev", "nvd", "feodo"):
                    c = getattr(clients, field_name, None)
                    if c is not None:
                        await c.aclose()
                for field_name in ("urlhaus", "threatfox", "otx"):
                    c = getattr(clients, field_name, None)
                    if c is not None:
                        await c.aclose()

        source_keys = ("cisa_kev", "nvd", "urlhaus", "threatfox", "feodo", "otx")
        sources: dict[str, Any] = {}
        error_count = 0
        ok_count = 0

        for key, result in zip(source_keys, results):
            if isinstance(result, Exception):
                log.warning("OSINT source %s raised unexpectedly: %s", key, result)
                sources[key] = {"status": "error", "reason": str(result)}
                error_count += 1
            else:
                sources[key] = result
                if result.get("status") == "ok":
                    ok_count += 1
                elif result.get("status") == "error":
                    error_count += 1

        # All enabled sources failed → raise
        enabled_count = sum(
            1 for k in source_keys
            if k in enabled and sources[k].get("status") != "skipped"
        )
        if enabled_count > 0 and ok_count == 0 and error_count == enabled_count:
            raise PluginFetchError(
                "All OSINT sources failed. Check network connectivity or API keys."
            )

        payload: dict[str, Any] = {
            "window_hours": window_hours,
            "generated_at": now.isoformat(),
            "sources": sources,
        }

        # Surface KEV and high-CVSS CVE links
        links: list[str] = []
        for item in (sources.get("cisa_kev") or {}).get("items", []):
            cve_id = item.get("cve")
            if cve_id:
                links.append(f"https://www.cisa.gov/known-exploited-vulnerabilities-catalog#{cve_id.lower()}")
        for item in (sources.get("nvd") or {}).get("items", []):
            for ref in item.get("references", []):
                links.append(ref)
            if len(links) >= 10:
                break

        total_items = sum(
            s.get("count", 0)
            for s in sources.values()
            if isinstance(s, dict) and s.get("status") == "ok"
        )

        return FetchResult(
            source_name=self.display_name,
            raw_payload=payload,
            metadata={
                "window_hours": window_hours,
                "total_items": total_items,
                "sources_ok": ok_count,
                "sources_error": error_count,
                "sources_skipped": len(source_keys) - ok_count - error_count,
            },
            links=links[:10],
        )

    def redact(self, payload: Any) -> Any:
        """No-op — threat intel is public by construction."""
        return payload

    def format_table(self, payload: Any) -> str | None:
        from tabulate import tabulate

        sources = payload.get("sources", {})
        labels = {
            "cisa_kev": "CISA KEV",
            "nvd": "NVD CVEs",
            "urlhaus": "URLhaus",
            "threatfox": "ThreatFox",
            "feodo": "Feodo",
            "otx": "OTX",
        }
        rows = []
        for key, label in labels.items():
            src = sources.get(key, {})
            status = src.get("status", "—")
            if status == "skipped":
                continue
            count = src.get("count", src.get("total_online")) if status == "ok" else "—"
            rows.append([label, count, status])

        if not rows:
            return None
        table = tabulate(rows, headers=["Source", "Items", "Status"], tablefmt="outline", colalign=("left", "right", "left"))
        return f"```\n{table}\n```"
