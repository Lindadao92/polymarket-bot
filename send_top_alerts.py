"""
send_top_alerts.py — One-shot live run: fetch Polymarket data, pick the top
10 highest-quality alerts (2 per signal type), and send them to Telegram
using the new enriched alert format.

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
from telegram_alerts import format_alert_html

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
    """Higher score = better quality signal."""
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
            bucket = by_type[sig]
            if i < len(bucket):
                selected.append(bucket[i])
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

    # ── Fetch & detect ────────────────────────────────────────────────────────
    log.info("Fetching active events from Polymarket …")
    events = fetch_active_events()
    total_markets = sum(len(e.get("markets", [])) for e in events)
    log.info("Fetched %d events / %d markets. Running detectors …",
             len(events), total_markets)

    all_alerts = run_all_detectors(events)
    log.info("Total raw alerts: %d", len(all_alerts))

    top = pick_top_alerts(all_alerts, per_type=2)
    log.info("Selected top %d alerts.", len(top))

    # ── Count by type for the intro ───────────────────────────────────────────
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
        f"Total opportunities found: <b>{len(all_alerts):,}</b>\n\n"
        f"<b>Sending top {len(top)} highest-quality signals:</b>\n{summary}\n\n"
        "<b>Alert format:</b>\n"
        "  🟢 BUY YES / 🔴 BUY NO / 🟡 WATCH / ⚪ SKIP\n"
        "  🔥 HIGH / 📌 MEDIUM / 💭 LOW confidence\n"
        "  Bet size: SMALL ($5–10) / MEDIUM ($20–50) / LARGE ($50–100)\n\n"
        "<i>All data is live from Polymarket right now.</i>"
    )
    await send(bot, intro)
    log.info("Sent intro message.")
    time.sleep(0.8)

    # ── Send each alert ───────────────────────────────────────────────────────
    sent = 0
    for i, alert in enumerate(top, 1):
        html = format_alert_html(alert)
        ok   = await send(bot, html)
        if ok:
            sent += 1
            log.info("  [%d/%d] ✓ [%s] %s | %s | %s",
                     i, len(top),
                     alert.signal_type,
                     alert.action,
                     alert.confidence,
                     alert.market_question[:55])
        time.sleep(0.8)

    # ── Closing message ───────────────────────────────────────────────────────
    closing = (
        f"<b>✅ Live scan complete — {sent}/{len(top)} alerts delivered.</b>\n\n"
        f"In continuous mode the bot checks Polymarket every "
        f"<b>{config.POLL_INTERVAL_SECONDS}s</b> and sends new alerts as they "
        f"appear (1-hour cooldown per market/signal to avoid spam).\n\n"
        "<b>To run 24/7:</b> see <code>DEPLOY_GUIDE.md</code> for Railway setup."
    )
    await send(bot, closing)
    log.info("Done. %d alert messages + intro + closing sent.", sent)


if __name__ == "__main__":
    asyncio.run(main())
