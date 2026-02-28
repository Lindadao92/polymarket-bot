#!/usr/bin/env python3
"""
bot.py — Main entry point for the Polymarket Alert Bot.

Runs a continuous polling loop that:
  1. Fetches all active events and their markets from the Gamma API.
  2. Runs every detection strategy against the data.
  3. Applies the quality filter (MIN_CONFIDENCE + ALLOWED_ACTIONS).
  4. Sends qualifying alerts to Telegram (or prints to console if unconfigured).
  5. Sleeps for the configured interval and repeats.

Usage:
    python bot.py              # normal operation
    python bot.py --once       # single scan then exit (useful for testing)
    python bot.py --dry-run    # scan + detect but don't send Telegram messages
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
import traceback

import config
from polymarket_client import fetch_active_events
from detectors import run_all_detectors
from telegram_alerts import (
    send_alerts,
    send_startup_message,
    send_error_message,
    _passes_quality_filter,
)

# ── Logging setup ────────────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("polymarket_bot")

# ── Graceful shutdown ────────────────────────────────────────────────────────

_running = True


def _shutdown_handler(signum, frame):
    global _running
    logger.info("Received signal %s — shutting down gracefully.", signum)
    _running = False


signal.signal(signal.SIGINT, _shutdown_handler)
signal.signal(signal.SIGTERM, _shutdown_handler)


# ── Core loop ────────────────────────────────────────────────────────────────

def scan_once(dry_run: bool = False) -> int:
    """
    Execute a single scan cycle.

    Returns the number of alerts sent (or that would be sent, if dry_run).
    """
    logger.info("Starting scan cycle...")

    # 1. Fetch data
    events = fetch_active_events()
    if not events:
        logger.warning("No events returned — skipping this cycle.")
        return 0

    total_markets = sum(len(e.get("markets", [])) for e in events)
    logger.info("Scanning %d events containing %d markets.", len(events), total_markets)

    # 2. Detect opportunities
    alerts = run_all_detectors(events)

    if not alerts:
        logger.info("No opportunities detected this cycle.")
        return 0

    # 3. Apply quality filter for reporting
    qualified = [a for a in alerts if _passes_quality_filter(a)]
    logger.info(
        "Quality filter: %d raw alerts → %d pass (HIGH confidence + BUY YES/NO).",
        len(alerts), len(qualified),
    )

    if dry_run:
        logger.info("[DRY RUN] Would send %d alerts:", len(qualified))
        for a in qualified:
            logger.info("  • [%s] %s | %s | %s",
                        a.signal_type, a.action, a.confidence, a.market_question)
        return len(qualified)

    # 4. Send (send_alerts applies the filter internally too)
    sent = send_alerts(alerts)
    logger.info("Sent %d alert(s) to Telegram.", sent)
    return sent


def main() -> None:
    parser = argparse.ArgumentParser(description="Polymarket Alert Bot")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single scan cycle and exit.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Detect opportunities but don't send Telegram messages.",
    )
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("  Polymarket Alert Bot starting")
    logger.info("=" * 60)
    logger.info("  Poll interval   : %ds", config.POLL_INTERVAL_SECONDS)
    logger.info("  Odds shift      : %.0f%%", config.ODDS_SHIFT_THRESHOLD * 100)
    logger.info("  Volume spike    : %.1fx", config.VOLUME_SPIKE_MULTIPLIER)
    logger.info("  Closing soon    : %dh", config.CLOSING_SOON_HOURS)
    logger.info("  New markets     : %dh", config.NEW_MARKET_HOURS)
    logger.info("  Mispricing      : %.0f%%", config.MISPRICE_SUM_DEVIATION * 100)
    logger.info("  Topic filter    : %s", config.TOPIC_KEYWORDS or "(all)")
    logger.info("  Min confidence  : %s", config.MIN_CONFIDENCE)
    logger.info("  Allowed actions : %s", config.ALLOWED_ACTIONS)
    logger.info("  Telegram        : %s",
                "configured" if config.TELEGRAM_BOT_TOKEN else "NOT configured (console mode)")
    logger.info("=" * 60)

    if not args.dry_run:
        send_startup_message()

    if args.once:
        scan_once(dry_run=args.dry_run)
        return

    # Continuous loop
    consecutive_errors = 0
    while _running:
        try:
            scan_once(dry_run=args.dry_run)
            consecutive_errors = 0
        except Exception:
            consecutive_errors += 1
            tb = traceback.format_exc()
            logger.error("Scan cycle failed (attempt %d):\n%s", consecutive_errors, tb)

            if consecutive_errors == 1:
                try:
                    send_error_message(tb[-500:])
                except Exception:
                    pass

            backoff = min(60 * (2 ** (consecutive_errors - 1)), 600)
            logger.info("Backing off for %ds before retrying.", backoff)
            _interruptible_sleep(backoff)
            continue

        _interruptible_sleep(config.POLL_INTERVAL_SECONDS)

    logger.info("Bot stopped.")


def _interruptible_sleep(seconds: float) -> None:
    end = time.time() + seconds
    while _running and time.time() < end:
        time.sleep(min(1, end - time.time()))


if __name__ == "__main__":
    main()
