"""AWS Billing data-source plugin — Cost Explorer spending summary."""

import asyncio
import logging
import os
from datetime import UTC, date, datetime, timedelta
from typing import Any

from jarvis.core.exceptions import PluginAuthError, PluginFetchError
from jarvis.core.plugin import DataSourcePlugin, FetchResult

from .auth import get_client
from .chunker import billing_chunker

__all__ = ["AWSBillingPlugin"]

log = logging.getLogger(__name__)


def _currency() -> str:
    return os.environ.get("BILLING_CURRENCY", "USD").strip() or "USD"


def _group_by_dimension() -> str:
    return os.environ.get("BILLING_GROUP_BY", "SERVICE").strip() or "SERVICE"


def _date_str(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def _quarter_bounds(today: date) -> tuple[date, date]:
    """Return (quarter_start, quarter_end) for the calendar quarter containing today."""
    month = today.month
    q_start_month = ((month - 1) // 3) * 3 + 1
    q_start = date(today.year, q_start_month, 1)
    # Quarter end: last day of the third month in the quarter
    q_end_month = q_start_month + 2
    if q_end_month == 12:
        q_end = date(today.year, 12, 31)
    else:
        q_end = date(today.year, q_end_month + 1, 1) - timedelta(days=1)
    return q_start, q_end


def _prior_quarter_bounds(q_start: date) -> tuple[date, date]:
    """Return (prior_quarter_start, prior_quarter_end) given the current quarter start."""
    # Step back one quarter
    if q_start.month == 1:
        pq_start = date(q_start.year - 1, 10, 1)
        pq_end = date(q_start.year - 1, 12, 31)
    else:
        pq_start_month = q_start.month - 3
        pq_start = date(q_start.year, pq_start_month, 1)
        pq_end = q_start - timedelta(days=1)
    return pq_start, pq_end


def _parse_service_amounts(results: list[dict], group_by_dim: str) -> list[dict]:
    """Extract per-service cost rows from a GetCostAndUsage result set."""
    service_totals: dict[str, float] = {}
    for result in results:
        for group in result.get("Groups", []):
            keys = group.get("Keys", [])
            name = keys[0] if keys else "Unknown"
            amount_str = (
                group.get("Metrics", {})
                .get("UnblendedCost", {})
                .get("Amount", "0")
            )
            service_totals[name] = service_totals.get(name, 0.0) + float(amount_str)

    # Sort descending by cost
    return [
        {"name": name, "amount": round(amount, 2)}
        for name, amount in sorted(service_totals.items(), key=lambda x: -x[1])
    ]


def _total_from_results(results: list[dict]) -> float:
    total = 0.0
    for result in results:
        # Try grouped results first
        for group in result.get("Groups", []):
            amount_str = (
                group.get("Metrics", {})
                .get("UnblendedCost", {})
                .get("Amount", "0")
            )
            total += float(amount_str)
        # Fall back to top-level Total if no groups
        if not result.get("Groups"):
            amount_str = (
                result.get("Total", {})
                .get("UnblendedCost", {})
                .get("Amount", "0")
            )
            total += float(amount_str)
    return round(total, 2)


def _get_cost_and_usage(
    client: Any,
    start: str,
    end: str,
    granularity: str,
    group_by_dim: str,
    currency: str,
) -> list[dict]:
    """Synchronous Cost Explorer call — wrap in asyncio.to_thread."""
    response = client.get_cost_and_usage(
        TimePeriod={"Start": start, "End": end},
        Granularity=granularity,
        Metrics=["UnblendedCost"],
        GroupBy=[{"Type": "DIMENSION", "Key": group_by_dim}],
    )
    return response.get("ResultsByTime", [])


def _get_cost_forecast(
    client: Any,
    start: str,
    end: str,
    granularity: str,
    currency: str,
) -> float | None:
    """Synchronous Cost Explorer forecast call — wrap in asyncio.to_thread.

    Returns None if forecasting is unavailable (e.g. insufficient history).
    """
    try:
        response = client.get_cost_forecast(
            TimePeriod={"Start": start, "End": end},
            Metric="UNBLENDED_COST",
            Granularity=granularity,
        )
        amount_str = response.get("Total", {}).get("Amount", None)
        return round(float(amount_str), 2) if amount_str is not None else None
    except Exception as exc:
        log.warning("Cost forecast unavailable (%s) — skipping", exc)
        return None


class AWSBillingPlugin(DataSourcePlugin):
    """Fetch AWS spend summaries from Cost Explorer: today, MTD, QTD, and forecasts."""

    name = "aws_billing"
    display_name = "AWS Billing"
    required_env_vars = ["BILLING_AWS_REGION"]
    temperature = 0.1
    max_tokens = 500

    async def fetch(self, window_hours: int) -> FetchResult:
        """Run three parallel Cost Explorer queries plus optional forecasts."""
        currency = _currency()
        group_by_dim = _group_by_dimension()
        today = datetime.now(UTC).date()

        log.info(
            "Fetching AWS billing data (today=%s, currency=%s, group_by=%s)",
            today,
            currency,
            group_by_dim,
        )

        try:
            client = await get_client()
        except Exception as exc:
            log.exception("AWS Billing auth failed")
            raise PluginAuthError("AWS Billing auth failed: %s" % exc) from exc

        # Date math
        yesterday = today - timedelta(days=1)
        yesterday_str = _date_str(yesterday)
        today_str = _date_str(today)
        tomorrow_str = _date_str(today + timedelta(days=1))
        month_start_str = _date_str(date(today.year, today.month, 1))
        prior_month_start = (
            date(today.year, today.month - 1, 1)
            if today.month > 1
            else date(today.year - 1, 12, 1)
        )
        prior_month_start_str = _date_str(prior_month_start)
        # Prior MTD end is same elapsed days last month
        prior_mtd_end = min(
            prior_month_start.replace(day=today.day),
            # Clamp to end of prior month
            date(today.year, today.month, 1) - timedelta(days=1),
        )
        prior_mtd_end_str = _date_str(prior_mtd_end + timedelta(days=1))  # exclusive end

        q_start, q_end = _quarter_bounds(today)
        q_start_str = _date_str(q_start)
        pq_start, pq_end = _prior_quarter_bounds(q_start)
        # Same elapsed days into prior quarter
        elapsed_days = (today - q_start).days
        pq_same_day = pq_start + timedelta(days=elapsed_days)
        pq_same_day_str = _date_str(
            min(pq_same_day, pq_end) + timedelta(days=1)  # exclusive end
        )
        pq_start_str = _date_str(pq_start)

        # --- Three parallel main queries ---
        try:
            yesterday_results, mtd_results, qtd_results = await asyncio.gather(
                asyncio.to_thread(
                    _get_cost_and_usage,
                    client, yesterday_str, today_str, "DAILY", group_by_dim, currency,
                ),
                asyncio.to_thread(
                    _get_cost_and_usage,
                    client, month_start_str, tomorrow_str, "MONTHLY", group_by_dim, currency,
                ),
                asyncio.to_thread(
                    _get_cost_and_usage,
                    client, q_start_str, tomorrow_str, "MONTHLY", group_by_dim, currency,
                ),
            )
        except Exception as exc:
            log.exception("AWS Billing cost queries failed")
            raise PluginFetchError("AWS Billing fetch failed: %s" % exc) from exc

        # Prior-period queries (fail soft individually)
        try:
            prior_mtd_results, prior_qtd_results = await asyncio.gather(
                asyncio.to_thread(
                    _get_cost_and_usage,
                    client, prior_month_start_str, prior_mtd_end_str, "MONTHLY",
                    group_by_dim, currency,
                ),
                asyncio.to_thread(
                    _get_cost_and_usage,
                    client, pq_start_str, pq_same_day_str, "MONTHLY",
                    group_by_dim, currency,
                ),
            )
        except Exception as exc:
            log.warning("Prior-period queries failed (%s) — comparison unavailable", exc)
            prior_mtd_results = []
            prior_qtd_results = []

        # --- Forecasts (fail soft) ---
        month_end_str = _date_str(
            date(today.year, today.month + 1, 1) - timedelta(days=1)
            if today.month < 12
            else date(today.year, 12, 31)
        )
        q_end_str = _date_str(q_end)

        month_forecast, quarter_forecast = await asyncio.gather(
            asyncio.to_thread(
                _get_cost_forecast, client, tomorrow_str, month_end_str, "MONTHLY", currency
            ),
            asyncio.to_thread(
                _get_cost_forecast, client, tomorrow_str, q_end_str, "MONTHLY", currency
            ),
        )

        # --- Assemble payload ---
        yesterday_total = _total_from_results(yesterday_results)
        mtd_total = _total_from_results(mtd_results)
        qtd_total = _total_from_results(qtd_results)
        prior_mtd_total = _total_from_results(prior_mtd_results) if prior_mtd_results else None
        prior_qtd_total = _total_from_results(prior_qtd_results) if prior_qtd_results else None

        def _pct_delta(current: float, prior: float | None) -> float | None:
            if prior is None or prior == 0:
                return None
            return round((current - prior) / prior * 100, 1)

        yesterday_services = _parse_service_amounts(yesterday_results, group_by_dim)
        mtd_services = _parse_service_amounts(mtd_results, group_by_dim)
        qtd_services = _parse_service_amounts(qtd_results, group_by_dim)

        payload: dict[str, Any] = {
            "yesterday": {
                "total": yesterday_total,
                "by_service": yesterday_services[:10],
                "date": yesterday_str,
            },
            "mtd": {
                "total": mtd_total,
                "by_service": mtd_services,
                "prior_mtd": prior_mtd_total,
                "pct_delta": _pct_delta(mtd_total, prior_mtd_total),
            },
            "qtd": {
                "total": qtd_total,
                "by_service": qtd_services,
                "prior_qtd_sameperiod": prior_qtd_total,
                "pct_delta": _pct_delta(qtd_total, prior_qtd_total),
            },
            "forecast": {
                "month_end": month_forecast,
                "quarter_end": quarter_forecast,
            },
        }

        log.info(
            "AWS Billing: yesterday=$%.2f, MTD=$%.2f, QTD=$%.2f",
            yesterday_total,
            mtd_total,
            qtd_total,
        )

        return FetchResult(
            source_name=self.display_name,
            raw_payload=payload,
            metadata={
                "currency": currency,
                "group_by": group_by_dim,
                "yesterday": yesterday_str,
                "mtd_start": month_start_str,
                "qtd_start": q_start_str,
                "fetched_at": datetime.now(UTC).isoformat(),
            },
        )

    def chunker(self):
        """Return the billing-specific section-based chunker."""
        return billing_chunker

    def redact(self, payload: Any) -> Any:
        """No sensitive data in cost figures — pass through unchanged."""
        return payload

    def format_table(self, payload: Any) -> str | None:
        from tabulate import tabulate

        services = payload.get("yesterday", {}).get("by_service", [])
        if not services:
            return None
        rows = [[s["name"], f"${s['amount']:.2f}"] for s in services]
        table = tabulate(
            rows,
            headers=["Service", "Cost"],
            tablefmt="outline",
            colalign=("left", "right"),
        )
        return f"```\n{table}\n```"
