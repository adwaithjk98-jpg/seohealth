"""Execution adapter for the standalone ``audit_scraper`` engine (Phase 4).

The engine lives in a sibling repo (``settings.audit_scraper_path``) and is
purpose-built for heavy-duty bulk discovery: a multi-stage pipeline that
filters Maps cards, async-fetches enrichment fields, and finally enriches
survivors with Selenium. It carries its own venv, its own logging, and its
own ``.env`` for proxy credentials — none of which we want pulled into the
FastAPI process.

So we shell out. ``run_competitor_scrape`` spawns
``python3 scrape_competitors.py "<query>" <num_leads> <fields> [filters]``
in a child process, captures its JSON stdout (the engine's contract), and
returns the parsed result. Stderr is logged for diagnostics but does not
block parsing — the engine streams progress narration there.

This is the Discovery-Scan-feature primitive. It does not touch the DB; the
caller decides what to persist (a future ``DiscoveryScan`` table) and which
tier limits to enforce.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

_SCRIPT_NAME = "scrape_competitors.py"


class CompetitorScraperError(RuntimeError):
    """Raised when the subprocess exits non-zero, times out, or emits bad JSON.

    The string form includes the exit code (when available) and a trimmed
    tail of stderr so the failure is debuggable without trawling worker logs.
    """


@dataclass
class CompetitorScrapeResult:
    """Structured return so callers don't dig through tuples.

    ``raw_stderr`` is preserved verbatim because the engine's progress lines
    on stderr are the most useful signal when a run "succeeded" but returned
    fewer leads than requested.
    """

    results: list[dict[str, Any]]
    raw_stderr: str
    elapsed_seconds: float


def _resolve_script_path() -> str:
    """Compute the absolute path to ``scrape_competitors.py``.

    Raised here (eagerly) rather than letting the subprocess fail later with
    a less obvious "no such file" — the most common deployment mistake is
    forgetting to set ``AUDIT_SCRAPER_PATH``.
    """
    script = os.path.join(settings.audit_scraper_path, _SCRIPT_NAME)
    if not os.path.isfile(script):
        raise CompetitorScraperError(
            f"audit_scraper script not found at {script!r}. "
            f"Set AUDIT_SCRAPER_PATH to the engine repo root."
        )
    return script


def _validate_args(query: str, num_leads: int, fields: list[str]) -> None:
    if not query or not query.strip():
        raise ValueError("query is required")
    if num_leads < 1:
        raise ValueError("num_leads must be >= 1")
    if not fields:
        raise ValueError("fields must be a non-empty list")


async def run_competitor_scrape(
    query: str,
    num_leads: int,
    fields: list[str],
    filters: str | None = None,
    *,
    timeout_seconds: int | None = None,
) -> CompetitorScrapeResult:
    """Spawn the audit_scraper engine and return its parsed JSON output.

    Args mirror the engine's CLI:
      - ``query``: search string passed to Google Maps (e.g. "cafes in Kochi").
      - ``num_leads``: target qualified result count.
      - ``fields``: column names the engine should populate per result
        (e.g. ``["name", "phone", "rating", "instagram_followers"]``).
      - ``filters``: optional filter DSL string (e.g. ``"rating>4.0"``);
        passed through verbatim as the engine's 4th positional argument.
      - ``timeout_seconds``: per-run wall-clock budget. Defaults to
        ``settings.audit_scraper_timeout_seconds``.

    The subprocess is asyncio-native (``create_subprocess_exec``) so a
    FastAPI route or RQ task can ``await`` it without blocking the event loop.
    """
    _validate_args(query, num_leads, fields)
    script = _resolve_script_path()
    python_bin = settings.audit_scraper_python
    timeout = timeout_seconds or settings.audit_scraper_timeout_seconds

    args: list[str] = [
        python_bin,
        script,
        query,
        str(num_leads),
        ",".join(fields),
    ]
    if filters:
        args.append(filters)

    logger.info(
        "competitor_scraper_adapter: spawning pid=? cwd=%s query=%r leads=%d",
        settings.audit_scraper_path,
        query,
        num_leads,
    )

    loop = asyncio.get_running_loop()
    started_at = loop.time()
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=settings.audit_scraper_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise CompetitorScraperError(
            f"failed to spawn scraper: {exc}. "
            f"Check AUDIT_SCRAPER_PYTHON={python_bin!r}."
        ) from exc

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        # ``proc`` is still running — kill it so we don't leak a headless
        # Chrome process. ``proc.wait()`` is a no-op once it's reaped.
        try:
            proc.kill()
            await proc.wait()
        except ProcessLookupError:
            pass
        raise CompetitorScraperError(
            f"audit_scraper timed out after {timeout}s for query={query!r}"
        )

    elapsed = loop.time() - started_at
    stderr_text = stderr_bytes.decode("utf-8", errors="replace")

    if proc.returncode != 0:
        # Trim stderr to the last ~2KB — full tails can be several MB.
        tail = stderr_text[-2048:] if stderr_text else "<empty>"
        raise CompetitorScraperError(
            f"audit_scraper exited with code {proc.returncode} after "
            f"{elapsed:.1f}s for query={query!r}. stderr tail:\n{tail}"
        )

    stdout_text = stdout_bytes.decode("utf-8", errors="replace").strip()
    if not stdout_text:
        raise CompetitorScraperError(
            f"audit_scraper returned empty stdout (elapsed={elapsed:.1f}s). "
            f"stderr tail:\n{stderr_text[-2048:]}"
        )

    try:
        parsed = json.loads(stdout_text)
    except json.JSONDecodeError as exc:
        raise CompetitorScraperError(
            f"audit_scraper produced invalid JSON: {exc}. "
            f"stdout head:\n{stdout_text[:512]}"
        ) from exc

    if not isinstance(parsed, list):
        raise CompetitorScraperError(
            f"audit_scraper JSON must be a list, got {type(parsed).__name__}"
        )

    logger.info(
        "competitor_scraper_adapter: completed query=%r leads=%d returned=%d elapsed=%.1fs",
        query,
        num_leads,
        len(parsed),
        elapsed,
    )

    return CompetitorScrapeResult(
        results=parsed,
        raw_stderr=stderr_text,
        elapsed_seconds=elapsed,
    )
