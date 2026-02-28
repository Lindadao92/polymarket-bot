"""
send_top_alerts.py — One-shot live run: fetch Polymarket data, apply the
quality filter (HIGH confidence + BUY YES/NO only), pick the top 10 best
signals, and send them to Telegram.

Usage:
    python send_top_alerts.py
"""

import asyncio
import logging
import time

from dotenv import load_dotenv
load_dotenv()

import telegram
from telegram.constants import ParseMode

import config
from polymarket_client import fetch_active_events
from detectors import Alert, run_all_detectors
from telegram_alerts import format_alert_html, _passes_quality_filter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("top_alerts")

SIGNAL_ORDER = ["odds_shift", "volume_spike", "closing_soon", "new_market", "mispricing"]

SIGNAL_LABELS = {
    "odds_shift":   "📊 Sudden Odds Shift",
    "volume_spike": "📈 Volume Spike",
    "closing_soon": "⏰ Closing Soon",
    "new_market":   "🆕 New Market",
    "mispricing":   "⚖️ Potential Mispricing",
}


def score_alert(alert: Alert) -> float:
    d = alert.details
    if alert.signal_type == "odds_shift":
        return abs(d.get("price_change_24h", 0))
    if alert.signal_type == "volume_spike":
        return d.get("spike_ratio", 0)
    if alert.signal_type == "closing_soon":
        hours = d.get("hours_until_close", 9999)
        return 1000 / max(hours, 0.1)
    if alert.signal_type == "new_market":
        return d.get("liquidity", 0)
    if alert.signal_type == "mispricing":
        return d.get("deviation", 0)
    return 0.0


def pick_top_alerts(all_alerts: list[Alert], per_type: int = 2) -> list[Alert]:
    """Select the best `per_type` alerts per signal type, interleaved."""
    by_type: dict[str, list[Alert]] = {s: [] for s in SIGNAL_ORDER}
    for a in all_alerts:
        if a.signal_type in by_type:
            by_type[a.signal_type].append(a)
    for sig in by_type:
        by_type[sig].sort(key=score_alert, reverse=True)
    selected: list[Alert] = []
    for i in range(per_type):
        for sig in SIGNAL_ORDER:
            if i < len(by_type[sig]):
                selected.append(by_type[sig][i])
    return selected


async def send(bot: telegram.Bot, text: str) -> bool:
    try:
        await bot.send_message(
            chat_id=config.TELEGRAM_CHAT_ID,
            text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return True
    except telegram.error.TelegramError as exc:
        log.error("Send failed: %s", exc)
        return False


async def main():
    bot = telegram.Bot(token=config.TELEGRAM_BOT_TOKEN)

    log.info("Fetching active events from Polymarket …")
    events = fetch_active_events()
    total_markets = sum(len(e.get("markets", [])) for e in events)
    log.info("Fetched %d events / %d markets. Running detectors …",
             len(events), total_markets)

    all_alerts = run_all_detectors(events)
    log.info("Total raw alerts: %d", len(all_alerts))

    # Apply quality filter: HIGH confidence + BUY YES/NO only
    qualified = [a for a in all_alerts if _passes_quality_filter(a)]
    log.info("After quality filter (HIGH + BUY): %d alerts remain.", len(qualified))

    top = pick_top_alerts(qualified, per_type=2)
    log.info("Selected top %d alerts to send.", len(top))

    if not top:
        log.warning("No HIGH-confidence BUY alerts found this cycle. Nothing to send.")
        await send(bot,
            "🤖 <b>Polymarket scan complete</b>\n\n"
            "No HIGH-confidence BUY YES / BUY NO opportunities found right now.\n"
            "The bot will keep scanning and alert you when something strong appears."
        )
        return

    # Count by type for intro
    type_counts: dict[str, int] = {}
    for a in top:
        type_counts[a.signal_type] = type_counts.get(a.signal_type, 0) + 1

    summary = "\n".join(
        f"  • {SIGNAL_LABELS[s]}: {c} alert{'s' if c > 1 else ''}"
        for s, c in type_counts.items()
    )

    intro = (
        "<b>🤖 Polymarket Alert Bot — Live Scan Results</b>\n\n"
        f"Scanned <b>{len(events):,}</b> events · <b>{total_markets:,}</b> markets\n"
        f"Total raw signals: <b>{len(all_alerts):,}</b>\n"
        f"After quality filter (HIGH + BUY only): <b>{len(qualified):,}</b>\n\n"
        f"<b>Sending top {len(top)} highest-quality signals:</b>\n{summary}\n\n"
        "<i>Only HIGH confidence BUY YES / BUY NO alerts shown.</i>"
    )
    await send(bot, intro)
    log.info("Sent intro message.")
    time.sleep(0.8)

    sent = 0
    for i, alert in enumerate(top, 1):
        html = format_alert_html(alert)
        ok   = await send(bot, html)
        if ok:
            sent += 1
            log.info("  [%d/%d] ✓ [%s] %s | %s | %s",
                     i, len(top), alert.signal_type,
                     alert.action, alert.confidence,
                     alert.market_question[:55])
        time.sleep(0.8)

    closing = (
        f"<b>✅ Done — {sent}/{len(top)} alerts delivered.</b>\n\n"
        f"In continuous mode the bot checks every <b>{config.POLL_INTERVAL_SECONDS}s</b> "
        f"and only pings you when it finds a HIGH-confidence BUY signal.\n\n"
        "<b>To adjust sensitivity:</b> change <code>MIN_CONFIDENCE</code> or "
        "<code>ALLOWED_ACTIONS</code> in your Railway environment variables."
    )
    await send(bot, closing)
    log.info("Done. %d alert messages + intro + closing sent.", sent)


if __name__ == "__main__":
    asyncio.run(main())
