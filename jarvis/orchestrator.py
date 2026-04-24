"""Run-once orchestration pipeline."""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from jarvis.core.exceptions import GroqError, PluginFetchError, SlackDeliveryError
from jarvis.core.groq_queue import GroqQueue
from jarvis.core.plugin import DataSourcePlugin, FetchResult
from jarvis.core.slack import PluginSummary, build_message, post_message, write_markdown_file
from jarvis.core.summarizer import summarize, synthesize_executive_summary

__all__ = ["PluginOutcome", "run"]

log = logging.getLogger(__name__)

_PLUGIN_TIMEOUT_S = 60


@dataclass(slots=True)
class PluginOutcome:
    plugin: DataSourcePlugin
    result: FetchResult | None = None
    summary: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


async def _fetch_one(plugin: DataSourcePlugin, window_hours: int) -> PluginOutcome:
    outcome = PluginOutcome(plugin=plugin)
    t0 = time.monotonic()
    try:
        result = await asyncio.wait_for(plugin.fetch(window_hours), timeout=_PLUGIN_TIMEOUT_S)
        outcome.result = result
        log.info("Fetched '%s' in %.2fs", plugin.name, time.monotonic() - t0)
    except asyncio.TimeoutError:
        outcome.error = f"fetch timed out after {_PLUGIN_TIMEOUT_S}s"
        log.warning("Plugin '%s' timed out", plugin.name)
    except PluginFetchError as exc:
        outcome.error = str(exc)
        log.exception("Plugin '%s' fetch error", plugin.name)
    except Exception:
        outcome.error = "unexpected error during fetch"
        log.exception("Plugin '%s' raised unexpected exception", plugin.name)
    return outcome


async def run(
    plugins: list[DataSourcePlugin],
    groq_queue: GroqQueue,
    settings: Any,
) -> None:
    """Execute the full fetch → summarize → post pipeline once."""
    t_start = time.monotonic()
    log.info(
        "Run started: plugins=%s",
        [p.name for p in plugins],
    )

    # Fetch all plugins concurrently
    outcomes: list[PluginOutcome] = await asyncio.gather(
        *[_fetch_one(p, settings.run_window_hours) for p in plugins]
    )

    # Summarize successful fetches through the queue, then synthesize an overview
    exec_summary: str | None = None
    async with groq_queue:
        summarize_tasks = []
        for outcome in outcomes:
            if outcome.ok and outcome.result is not None:
                summarize_tasks.append(
                    _summarize_one(outcome, groq_queue, settings.groq_model, settings.run_window_hours)
                )
        if summarize_tasks:
            await asyncio.gather(*summarize_tasks)

        successful_summaries = [o.summary for o in outcomes if o.ok and o.summary]
        if successful_summaries:
            try:
                exec_summary = await synthesize_executive_summary(
                    successful_summaries, groq_queue, settings.groq_model
                )
            except Exception:
                log.warning("Executive summary generation failed; proceeding without it")

    # Build per-plugin summary objects for Slack
    plugin_summaries: list[PluginSummary] = []
    for outcome in outcomes:
        if outcome.ok and outcome.summary:
            markdown = outcome.summary
            if outcome.result is not None:
                try:
                    table_str = outcome.plugin.format_table(outcome.result.raw_payload)
                    if table_str:
                        markdown = f"{markdown}\n\n{table_str}"
                except Exception:
                    log.warning("format_table() failed for '%s'", outcome.plugin.name)
            ps = PluginSummary(
                display_name=outcome.plugin.display_name,
                markdown=markdown,
                ok=True,
                links=outcome.result.links if outcome.result else [],
            )
        else:
            reason = outcome.error or "summary unavailable"
            ps = PluginSummary(
                display_name=outcome.plugin.display_name,
                markdown=f"*{outcome.plugin.display_name}*\n_{reason}_",
                ok=False,
            )
        plugin_summaries.append(ps)

    run_duration = time.monotonic() - t_start
    blocks = build_message(
        plugin_summaries,
        run_duration_s=run_duration,
        model=settings.groq_model,
        total_tokens=groq_queue.total_tokens,
        exec_summary=exec_summary,
    )

    log.info(
        "Run complete: duration=%.2fs groq_tokens=%d groq_requests=%d",
        run_duration,
        groq_queue.total_tokens,
        groq_queue.total_requests,
    )

    if settings.jarvis_dry_run:
        import json
        print(json.dumps(blocks, indent=2))
        log.info("Dry-run mode: digest printed to stdout, Slack skipped")
        return

    if not settings.slack_bot_token:
        path = write_markdown_file(
            plugin_summaries,
            run_duration_s=run_duration,
            model=settings.groq_model,
            total_tokens=groq_queue.total_tokens,
            exec_summary=exec_summary,
            output_path=settings.jarvis_output_file,
            output_dir=settings.jarvis_output_dir,
        )
        log.info("No SLACK_BOT_TOKEN configured — digest written to %s", path)
        return

    try:
        t_slack = time.monotonic()
        await post_message(
            blocks,
            bot_token=settings.slack_bot_token,
            target_type=settings.slack_target_type,
            target_id=settings.slack_target_id,
            username=settings.slack_username,
            icon_emoji=settings.slack_icon_emoji,
        )
        log.info("Slack post latency: %.2fs", time.monotonic() - t_slack)
    except SlackDeliveryError:
        log.error("Slack delivery failed; digest written to stdout as fallback")


async def _summarize_one(
    outcome: PluginOutcome,
    queue: GroqQueue,
    default_model: str,
    window_hours: int,
) -> None:
    try:
        outcome.summary = await summarize(
            outcome.plugin, outcome.result, queue, default_model, window_hours
        )
    except GroqError as exc:
        outcome.error = str(exc)
        log.exception("Groq summarization failed for plugin '%s'", outcome.plugin.name)
    except Exception:
        outcome.error = "unexpected summarization error"
        log.exception("Unexpected error summarizing plugin '%s'", outcome.plugin.name)
