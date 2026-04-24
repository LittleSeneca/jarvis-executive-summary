"""AWS SecurityHub data-source plugin — active findings over a rolling window."""

import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from jarvis.core.exceptions import PluginAuthError, PluginFetchError
from jarvis.core.plugin import DataSourcePlugin, FetchResult

from .auth import get_client

__all__ = ["SecurityHubPlugin"]

log = logging.getLogger(__name__)

# Matches a 12-digit AWS account ID inside an ARN segment
_ACCOUNT_ID_RE = re.compile(r"(\d{12})")

# Severities in priority order for deterministic sorting
_SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFORMATIONAL"]

# Map ProductArn substrings to a short standard label
_STANDARD_FRAGMENTS: list[tuple[str, str]] = [
    ("cis-aws-foundations-benchmark", "CIS"),
    ("pci-dss", "PCI"),
    ("aws-foundational-security", "FSBP"),
    ("nist-800-53", "NIST"),
    ("aws-control-tower", "ControlTower"),
]


def _parse_standard(product_arn: str) -> str:
    """Map a ProductArn to a human-readable standard abbreviation."""
    lower = product_arn.lower()
    for fragment, label in _STANDARD_FRAGMENTS:
        if fragment in lower:
            return label
    # Fall back to the last path component of the ARN
    return product_arn.rsplit("/", 1)[-1] if "/" in product_arn else product_arn


def _redact_arn(arn: str) -> str:
    """Replace 12-digit account IDs with [ACCOUNT_ID] in an ARN string."""
    return _ACCOUNT_ID_RE.sub("[ACCOUNT_ID]", arn)


def _collapse_resource_arn(arn: str) -> str:
    """Collapse a full resource ARN to a short service:resource form.

    arn:aws:iam::123456789012:role/admin -> iam:role/admin
    arn:aws:s3:::my-bucket             -> s3:my-bucket
    Falls back to the redacted ARN if parsing fails.
    """
    parts = arn.split(":", 5)
    if len(parts) < 6 or parts[0] != "arn":
        return _redact_arn(arn)
    service = parts[2]
    resource = parts[5]
    return "%s:%s" % (service, resource)


def _build_filters(cutoff_iso: str) -> dict:
    """Build GetFindings filters for active, non-suppressed findings updated since cutoff."""
    return {
        "UpdatedAt": [{"Start": cutoff_iso, "End": datetime.now(UTC).isoformat()}],
        "RecordState": [{"Value": "ACTIVE", "Comparison": "EQUALS"}],
        "WorkflowStatus": [
            {"Value": "SUPPRESSED", "Comparison": "NOT_EQUALS"},
            {"Value": "RESOLVED", "Comparison": "NOT_EQUALS"},
        ],
    }


def _extract_finding(raw: dict) -> dict:
    """Reduce a raw SecurityHub finding to the fields we care about."""
    severity_obj = raw.get("Severity", {})
    label = severity_obj.get("Label")
    if not label:
        normalized = severity_obj.get("Normalized")
        label = _normalised_to_label(normalized) if normalized is not None else "INFORMATIONAL"
    severity_label = label
    resources = [r.get("Id", "") for r in raw.get("Resources", [])]
    compliance_status = raw.get("Compliance", {}).get("Status", "")
    return {
        "id": raw.get("Id", ""),
        "title": raw.get("Title", ""),
        "severity": severity_label,
        "type": (raw.get("Types") or [""])[0],
        "resources": resources,
        "updated_at": raw.get("UpdatedAt", ""),
        "compliance_status": compliance_status,
    }


def _normalised_to_label(score: int) -> str:
    if score >= 90:
        return "CRITICAL"
    if score >= 70:
        return "HIGH"
    if score >= 40:
        return "MEDIUM"
    if score >= 1:
        return "LOW"
    return "INFORMATIONAL"


def _aggregate(findings: list[dict]) -> tuple[dict, dict]:
    """Return (counts_by_severity, counts_by_standard) from raw SecurityHub findings."""
    by_severity: dict[str, int] = {s: 0 for s in _SEVERITY_ORDER}
    by_standard: dict[str, int] = {}

    for f in findings:
        sev = (f.get("Severity", {}).get("Label") or "INFORMATIONAL").upper()
        if sev in by_severity:
            by_severity[sev] += 1
        else:
            by_severity[sev] = 1

        product_arn = f.get("ProductArn", "")
        standard = _parse_standard(product_arn)
        by_standard[standard] = by_standard.get(standard, 0) + 1

    # Drop zero-count severities to keep the payload clean
    by_severity = {k: v for k, v in by_severity.items() if v > 0}
    return by_severity, by_standard


def _paginate_findings(client: Any, filters: dict) -> list[dict]:
    """Synchronous paginator — must be called inside asyncio.to_thread."""
    findings: list[dict] = []
    paginator = client.get_paginator("get_findings")
    page_iterator = paginator.paginate(Filters=filters, PaginationConfig={"PageSize": 100})
    for page in page_iterator:
        findings.extend(page.get("Findings", []))
    return findings


class SecurityHubPlugin(DataSourcePlugin):
    """Fetch active SecurityHub findings updated in the last N hours."""

    name = "securityhub"
    display_name = "AWS SecurityHub"
    required_env_vars = ["SECURITYHUB_AWS_REGION"]
    temperature = 0.1
    max_tokens = 800

    async def fetch(self, window_hours: int) -> FetchResult:
        """Pull active, non-suppressed findings updated in the last window_hours."""
        cutoff = datetime.now(UTC) - timedelta(hours=window_hours)
        cutoff_iso = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

        log.info(
            "Fetching SecurityHub findings (window=%dh, cutoff=%s)",
            window_hours,
            cutoff_iso,
        )

        try:
            client = await get_client()
        except Exception as exc:
            log.exception("SecurityHub auth failed")
            raise PluginAuthError("SecurityHub auth failed: %s" % exc) from exc

        filters = _build_filters(cutoff_iso)

        try:
            raw_findings = await asyncio.to_thread(
                _paginate_findings, client, filters
            )
        except client.exceptions.InvalidAccessException as exc:
            raise PluginAuthError("SecurityHub access denied: %s" % exc) from exc
        except Exception as exc:
            log.exception("SecurityHub findings fetch failed")
            raise PluginFetchError("SecurityHub fetch failed: %s" % exc) from exc

        counts_by_severity, counts_by_standard = _aggregate(raw_findings)
        extracted = [_extract_finding(f) for f in raw_findings]

        # Sort: CRITICAL first, then HIGH, then by updated_at descending
        sev_rank = {s: i for i, s in enumerate(_SEVERITY_ORDER)}
        extracted.sort(
            key=lambda f: (sev_rank.get(f["severity"], 99), f["updated_at"]),
            reverse=False,
        )

        payload = {
            "window_hours": window_hours,
            "total_fetched": len(extracted),
            "counts_by_severity": counts_by_severity,
            "counts_by_standard": counts_by_standard,
            "findings": extracted,
        }

        log.info(
            "SecurityHub: %d findings fetched (CRITICAL=%d, HIGH=%d)",
            len(extracted),
            counts_by_severity.get("CRITICAL", 0),
            counts_by_severity.get("HIGH", 0),
        )

        return FetchResult(
            source_name=self.display_name,
            raw_payload=payload,
            metadata={
                "window_hours": window_hours,
                "total_fetched": len(extracted),
                "counts_by_severity": counts_by_severity,
                "fetched_at": datetime.now(UTC).isoformat(),
            },
        )

    def format_table(self, payload: Any) -> str | None:
        from tabulate import tabulate

        counts = payload.get("counts_by_severity", {})
        if not counts:
            return None
        order = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFORMATIONAL"]
        rows = [[sev, counts[sev]] for sev in order if sev in counts]
        table = tabulate(rows, headers=["Severity", "Count"], tablefmt="outline", colalign=("left", "right"))
        return f"```\n{table}\n```"

    def redact(self, payload: Any) -> Any:
        """Replace account IDs in ARNs, collapse resource ARNs, and filter to CRITICAL/HIGH only."""
        if not isinstance(payload, dict):
            return payload

        findings = payload.get("findings", [])
        redacted_findings = []
        for finding in findings:
            if finding.get("severity") not in {"CRITICAL", "HIGH"}:
                continue
            f = dict(finding)
            f["id"] = _redact_arn(f.get("id", ""))
            f["resources"] = [_collapse_resource_arn(r) for r in f.get("resources", [])]
            redacted_findings.append(f)

        return {**payload, "findings": redacted_findings}
