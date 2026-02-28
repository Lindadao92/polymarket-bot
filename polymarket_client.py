"""
polymarket_client.py — Thin wrapper around the Polymarket public APIs.

Handles pagination, retries, and rate-limit back-off so the rest of the bot
can work with clean Python objects.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config

logger = logging.getLogger(__name__)


def _build_session() -> requests.Session:
    """Return a requests Session with automatic retries and back-off."""
    session = requests.Session()
    retries = Retry(
        total=config.MAX_RETRIES,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


_session = _build_session()


# ── Gamma API helpers ────────────────────────────────────────────────────────

def fetch_active_events(max_events: int | None = None) -> list[dict[str, Any]]:
    """
    Fetch all active, non-closed events from the Gamma API.

    Each event object includes its nested ``markets`` array.  Results are
    ordered by 24-hour volume descending so the most active events come first.

    Parameters
    ----------
    max_events : int, optional
        Cap on the total number of events to retrieve.  Defaults to
        ``config.MAX_EVENTS_PER_CYCLE``.

    Returns
    -------
    list[dict]
        A list of event dictionaries straight from the Gamma API.
    """
    if max_events is None:
        max_events = config.MAX_EVENTS_PER_CYCLE

    events: list[dict[str, Any]] = []
    offset = 0

    while len(events) < max_events:
        limit = min(config.PAGE_SIZE, max_events - len(events))
        url = (
            f"{config.GAMMA_API_BASE}/events"
            f"?active=true&closed=false"
            f"&order=volume24hr&ascending=false"
            f"&limit={limit}&offset={offset}"
        )
        try:
            resp = _session.get(url, timeout=config.REQUEST_TIMEOUT)
            resp.raise_for_status()
            page = resp.json()
        except requests.RequestException as exc:
            logger.error("Gamma API /events request failed (offset=%d): %s", offset, exc)
            break

        if not page:
            break  # no more results

        events.extend(page)
        offset += limit

        # If we got fewer results than requested, we've exhausted the data.
        if len(page) < limit:
            break

        # Polite pause between pages to avoid hammering the API.
        time.sleep(0.25)

    logger.info("Fetched %d active events from Gamma API.", len(events))
    return events


def fetch_active_markets(max_markets: int = 500) -> list[dict[str, Any]]:
    """
    Fetch active markets directly from the /markets endpoint.

    Useful as a fallback or for flat iteration when event grouping is not
    needed.
    """
    markets: list[dict[str, Any]] = []
    offset = 0

    while len(markets) < max_markets:
        limit = min(config.PAGE_SIZE, max_markets - len(markets))
        url = (
            f"{config.GAMMA_API_BASE}/markets"
            f"?active=true&closed=false"
            f"&order=volume24hr&ascending=false"
            f"&limit={limit}&offset={offset}"
        )
        try:
            resp = _session.get(url, timeout=config.REQUEST_TIMEOUT)
            resp.raise_for_status()
            page = resp.json()
        except requests.RequestException as exc:
            logger.error("Gamma API /markets request failed (offset=%d): %s", offset, exc)
            break

        if not page:
            break

        markets.extend(page)
        offset += limit

        if len(page) < limit:
            break

        time.sleep(0.25)

    logger.info("Fetched %d active markets from Gamma API.", len(markets))
    return markets


def fetch_market_by_slug(slug: str) -> dict[str, Any] | None:
    """Fetch a single market by its slug identifier."""
    url = f"{config.GAMMA_API_BASE}/markets/slug/{slug}"
    try:
        resp = _session.get(url, timeout=config.REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        logger.error("Failed to fetch market slug=%s: %s", slug, exc)
        return None


def fetch_tags() -> list[dict[str, Any]]:
    """Return the list of available market tags/categories."""
    url = f"{config.GAMMA_API_BASE}/tags"
    try:
        resp = _session.get(url, timeout=config.REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        logger.error("Failed to fetch tags: %s", exc)
        return []


# ── CLOB API helpers ─────────────────────────────────────────────────────────

def fetch_midpoint(token_id: str) -> float | None:
    """Get the midpoint price for a CLOB token."""
    url = f"{config.CLOB_API_BASE}/midpoint?token_id={token_id}"
    try:
        resp = _session.get(url, timeout=config.REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        return float(data.get("mid", 0))
    except (requests.RequestException, ValueError, TypeError) as exc:
        logger.debug("Midpoint fetch failed for token %s: %s", token_id[:20], exc)
        return None


def fetch_spread(token_id: str) -> dict[str, Any] | None:
    """Get the bid-ask spread for a CLOB token."""
    url = f"{config.CLOB_API_BASE}/spread?token_id={token_id}"
    try:
        resp = _session.get(url, timeout=config.REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        logger.debug("Spread fetch failed for token %s: %s", token_id[:20], exc)
        return None


def fetch_orderbook(token_id: str) -> dict[str, Any] | None:
    """Get the full order book for a CLOB token."""
    url = f"{config.CLOB_API_BASE}/book?token_id={token_id}"
    try:
        resp = _session.get(url, timeout=config.REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        logger.debug("Order book fetch failed for token %s: %s", token_id[:20], exc)
        return None
