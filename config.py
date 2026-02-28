"""
config.py — Centralized configuration for the Polymarket Alert Bot.

All settings are loaded from environment variables.
Sensible defaults are provided so the bot works out of the box for testing;
tweak the thresholds to match your risk appetite.
"""

import os

# Try to load .env file if present, but don't fail if python-dotenv is missing
try:
    from dotenv import load_dotenv
    load_dotenv(override=False)  # Don't override existing env vars
except ImportError:
    pass

# ── Telegram Settings ────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.environ.get("TELEGRAM_CHAT_ID", "")

# Debug: print whether Telegram is configured (helps with Railway debugging)
import sys
print(f"[CONFIG DEBUG] TELEGRAM_BOT_TOKEN set: {bool(TELEGRAM_BOT_TOKEN)}", file=sys.stderr)
print(f"[CONFIG DEBUG] TELEGRAM_BOT_TOKEN length: {len(TELEGRAM_BOT_TOKEN)}", file=sys.stderr)
print(f"[CONFIG DEBUG] TELEGRAM_CHAT_ID set: {bool(TELEGRAM_CHAT_ID)}", file=sys.stderr)
print(f"[CONFIG DEBUG] All env vars with TELEGRAM: {[k for k in os.environ if 'TELEGRAM' in k.upper()]}", file=sys.stderr)

# ── Polymarket API Base URLs ─────────────────────────────────────────────────
GAMMA_API_BASE: str = "https://gamma-api.polymarket.com"
CLOB_API_BASE: str = "https://clob.polymarket.com"
DATA_API_BASE: str = "https://data-api.polymarket.com"

# ── Polling Interval ─────────────────────────────────────────────────────────
# How often (in seconds) the bot fetches fresh market data.
POLL_INTERVAL_SECONDS: int = int(os.environ.get("POLL_INTERVAL_SECONDS", "45"))

# ── Pagination ───────────────────────────────────────────────────────────────
# Maximum number of events to fetch per polling cycle (across all pages).
MAX_EVENTS_PER_CYCLE: int = int(os.environ.get("MAX_EVENTS_PER_CYCLE", "500"))
PAGE_SIZE: int = 100  # Gamma API max per request

# ── Detection Thresholds ─────────────────────────────────────────────────────

# 1. Sudden Odds Shift
#    Trigger when |oneDayPriceChange| exceeds this value (0.10 = 10%).
ODDS_SHIFT_THRESHOLD: float = float(os.environ.get("ODDS_SHIFT_THRESHOLD", "0.10"))

# 2. Volume Spike
#    Trigger when a market's 24h volume is this many times its average daily
#    volume (derived from volume1mo / 30).
VOLUME_SPIKE_MULTIPLIER: float = float(os.environ.get("VOLUME_SPIKE_MULTIPLIER", "3.0"))
#    Minimum absolute 24h volume (USD) to avoid noise from tiny markets.
MIN_VOLUME_24H: float = float(os.environ.get("MIN_VOLUME_24H", "5000"))

# 3. Markets About to Resolve
#    Flag markets whose endDate is within this many hours from now.
CLOSING_SOON_HOURS: int = int(os.environ.get("CLOSING_SOON_HOURS", "48"))
#    Only flag closing-soon markets with odds between these bounds (potential
#    edge — not already at 0 or 1).
CLOSING_EDGE_MIN: float = float(os.environ.get("CLOSING_EDGE_MIN", "0.10"))
CLOSING_EDGE_MAX: float = float(os.environ.get("CLOSING_EDGE_MAX", "0.90"))

# 4. New Markets (Early-Mover Advantage)
#    Flag markets created within the last N hours.
NEW_MARKET_HOURS: int = int(os.environ.get("NEW_MARKET_HOURS", "24"))
#    Minimum liquidity (USD) for a new market to be worth alerting on.
NEW_MARKET_MIN_LIQUIDITY: float = float(os.environ.get("NEW_MARKET_MIN_LIQUIDITY", "1000"))

# 5. Mispriced Markets (Complementary Odds Check)
#    In multi-market events the implied probabilities of all outcomes should
#    sum to ~1.0.  Flag when the deviation exceeds this threshold.
MISPRICE_SUM_DEVIATION: float = float(os.environ.get("MISPRICE_SUM_DEVIATION", "0.05"))
#    Minimum liquidity for mispricing check (avoid illiquid noise).
MISPRICE_MIN_LIQUIDITY: float = float(os.environ.get("MISPRICE_MIN_LIQUIDITY", "5000"))

# ── Alert Cooldown ───────────────────────────────────────────────────────────
# Minimum seconds between repeated alerts for the *same* market + signal type.
ALERT_COOLDOWN_SECONDS: int = int(os.environ.get("ALERT_COOLDOWN_SECONDS", "3600"))

# ── Topic Filters (optional) ────────────────────────────────────────────────
# Comma-separated list of keywords.  If set, only markets whose question or
# description contains at least one keyword will be monitored.
# Example: "bitcoin,trump,election,fed,ai"
TOPIC_KEYWORDS: str = os.environ.get("TOPIC_KEYWORDS", "")

# ── Logging ──────────────────────────────────────────────────────────────────
LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")

# ── HTTP Settings ────────────────────────────────────────────────────────────
REQUEST_TIMEOUT: int = int(os.environ.get("REQUEST_TIMEOUT", "30"))
MAX_RETRIES: int = int(os.environ.get("MAX_RETRIES", "3"))
