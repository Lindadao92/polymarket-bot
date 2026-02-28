"""
config.py — Centralized configuration for the Polymarket Alert Bot.

All settings are loaded from environment variables (or a .env file via
python-dotenv).  Sensible defaults are provided so the bot works out of the
box for testing; tweak the thresholds to match your risk appetite.
"""

import os
from dotenv import load_dotenv

# ── Load .env file if present ────────────────────────────────────────────────
load_dotenv()

# ── Telegram Settings ────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Polymarket API Base URLs ─────────────────────────────────────────────────
GAMMA_API_BASE: str = "https://gamma-api.polymarket.com"
CLOB_API_BASE: str = "https://clob.polymarket.com"
DATA_API_BASE: str = "https://data-api.polymarket.com"

# ── Polling Interval ─────────────────────────────────────────────────────────
# How often (in seconds) the bot fetches fresh market data.
POLL_INTERVAL_SECONDS: int = int(os.getenv("POLL_INTERVAL_SECONDS", "45"))

# ── Pagination ───────────────────────────────────────────────────────────────
# Maximum number of events to fetch per polling cycle (across all pages).
MAX_EVENTS_PER_CYCLE: int = int(os.getenv("MAX_EVENTS_PER_CYCLE", "500"))
PAGE_SIZE: int = 100  # Gamma API max per request

# ── Detection Thresholds ─────────────────────────────────────────────────────

# 1. Sudden Odds Shift
#    Trigger when |oneDayPriceChange| exceeds this value (0.10 = 10%).
ODDS_SHIFT_THRESHOLD: float = float(os.getenv("ODDS_SHIFT_THRESHOLD", "0.10"))

# 2. Volume Spike
#    Trigger when a market's 24h volume is this many times its average daily
#    volume (derived from volume1mo / 30).
VOLUME_SPIKE_MULTIPLIER: float = float(os.getenv("VOLUME_SPIKE_MULTIPLIER", "3.0"))
#    Minimum absolute 24h volume (USD) to avoid noise from tiny markets.
MIN_VOLUME_24H: float = float(os.getenv("MIN_VOLUME_24H", "5000"))

# 3. Markets About to Resolve
#    Flag markets whose endDate is within this many hours from now.
CLOSING_SOON_HOURS: int = int(os.getenv("CLOSING_SOON_HOURS", "48"))
#    Only flag closing-soon markets with odds between these bounds (potential
#    edge — not already at 0 or 1).
CLOSING_EDGE_MIN: float = float(os.getenv("CLOSING_EDGE_MIN", "0.10"))
CLOSING_EDGE_MAX: float = float(os.getenv("CLOSING_EDGE_MAX", "0.90"))

# 4. New Markets (Early-Mover Advantage)
#    Flag markets created within the last N hours.
NEW_MARKET_HOURS: int = int(os.getenv("NEW_MARKET_HOURS", "24"))
#    Minimum liquidity (USD) for a new market to be worth alerting on.
NEW_MARKET_MIN_LIQUIDITY: float = float(os.getenv("NEW_MARKET_MIN_LIQUIDITY", "1000"))

# 5. Mispriced Markets (Complementary Odds Check)
#    In multi-market events the implied probabilities of all outcomes should
#    sum to ~1.0.  Flag when the deviation exceeds this threshold.
MISPRICE_SUM_DEVIATION: float = float(os.getenv("MISPRICE_SUM_DEVIATION", "0.05"))
#    Minimum liquidity for mispricing check (avoid illiquid noise).
MISPRICE_MIN_LIQUIDITY: float = float(os.getenv("MISPRICE_MIN_LIQUIDITY", "5000"))

# ── Alert Quality Filter ─────────────────────────────────────────────────────
# Only send alerts that meet BOTH of these criteria.
#
# MIN_CONFIDENCE: minimum confidence level to send.
#   Options (case-sensitive): "HIGH", "MEDIUM", "LOW"
#   Default: "HIGH" — only send the strongest signals.
#   Set to "MEDIUM" to also receive medium-confidence alerts.
#   Set to "LOW" to receive everything (not recommended — very noisy).
MIN_CONFIDENCE: str = os.getenv("MIN_CONFIDENCE", "HIGH")

# ALLOWED_ACTIONS: comma-separated list of actions to send.
#   Options: "BUY YES", "BUY NO", "WATCH", "SKIP"
#   Default: "BUY YES,BUY NO" — only actionable buy signals, no WATCH/SKIP.
#   Set to "BUY YES,BUY NO,WATCH" to also receive watch alerts.
ALLOWED_ACTIONS: str = os.getenv("ALLOWED_ACTIONS", "BUY YES,BUY NO")

# ── Daily Alert Cap ─────────────────────────────────────────────────────────
# Maximum number of alerts to send per calendar day (UTC midnight resets).
# The bot will rank all qualifying opportunities by edge strength and only
# send the best ones up to this limit.  Set to 0 to disable the cap.
# Default: 5 — only the top 5 opportunities per day.
MAX_ALERTS_PER_DAY: int = int(os.getenv("MAX_ALERTS_PER_DAY", "5"))

# ── Alert Cooldown ───────────────────────────────────────────────────────────
# Minimum seconds between repeated alerts for the *same* market + signal type.
ALERT_COOLDOWN_SECONDS: int = int(os.getenv("ALERT_COOLDOWN_SECONDS", "3600"))

# ── Topic Filters (optional) ────────────────────────────────────────────────
# Comma-separated list of keywords.  If set, only markets whose question or
# description contains at least one keyword will be monitored.
# Example: "bitcoin,trump,election,fed,ai"
TOPIC_KEYWORDS: str = os.getenv("TOPIC_KEYWORDS", "")

# ── Logging ──────────────────────────────────────────────────────────────────
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# ── HTTP Settings ────────────────────────────────────────────────────────────
REQUEST_TIMEOUT: int = int(os.getenv("REQUEST_TIMEOUT", "30"))
MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))
