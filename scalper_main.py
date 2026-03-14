import time
import threading
import requests
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from tradingview_ta import TA_Handler, Interval

from config import (SYMBOLS, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID,
                    SCAN_INTERVAL, SIGNAL_COOLDOWN,
                    MIN_BUY_COUNT, MIN_SELL_COUNT,
                    BINANCE_BASE_URL,
                    TRADING_HOUR_START, TRADING_HOUR_END, TIMEZONE_OFFSET,
                    VOLUME_SPIKE_MIN, LEVEL_BUFFER_PCT,
                    BTC_DROP_BLOCK_PCT, BTC_PUMP_BLOCK_PCT)

# ─── Telegram ─────────────────────────────────
def send_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={
            "chat_id":    TELEGRAM_CHAT_ID,
            "text":       text,
            "parse_mode": "HTML"
        }, timeout=10)
    except Exception as e:
        print(f"[Telegram] {e}")


# ─── Binance данные ───────────────────────────
def get_price(symbol):
    try:
        r = requests.get(
            f"{BINANCE_BASE_URL}/fapi/v1/ticker/price",
            params={"symbol": symbol}, timeout=5
        )
        return float(r.json()["price"])
    except Exception:
        return 0.0

def get_klines(symbol, interval="15m", limit=50):
    try:
        r = requests.get(
            f"{BINANCE_BASE_URL}/fapi/v1/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit},
            timeout=10
        )
        data = r.json()
        return [
            {
                "open":   float(c[1]),
                "high":   float(c[2]),
                "low":    float(c[3]),
                "close":  float(c[4]),
                "volume": float(c[5]),
            }
            for c in data
        ]
    except Exception:
        return []


# ─── TradingView ──────────────────────────────
INTERVALS = {
    "15m": Interval.INTERVAL_15_MINUTES,
    "1h":  Interval.INTERVAL_1_HOUR,
    "4h":  Interval.INTERVAL_4_HOURS,
}

def get_tv_analysis(symbol, interval_key):
    try:
        sym = symbol.replace("USDT", "")
        handler = TA_Handler(
            symbol=f"{sym}USDT.P",
            screener="crypto",
            exchange="BINANCE",
            interval=INTERVALS[interval_key]
        )
        return handler.get_analysis()
    except Exception as e:
        print(f"[TV] {symbol} {interval_key}: {e}")
        return None

def parse_signal(analysis):
    if not analysis:
        return None
    rec     = analysis.summary["RECOMMENDATION"]
    buy     = analysis.summary["BUY"]
    sell    = analysis.summary["SELL"]
    neutral = analysis.summary["NEUTRAL"]
    total   = buy + sell + neutral
    ind     = analysis.indicators

    if rec in ("STRONG_BUY", "BUY") and buy >= MIN_BUY_COUNT:
        direction = "LONG"
    elif rec in ("STRONG_SELL", "SELL") and sell >= MIN_SELL_COUNT:
        direction = "SHORT"
    else:
        direction = "FLAT"

    return {
        "direction":  direction,
        "rec":        rec,
        "buy":        buy,
        "sell":       sell,
        "neutral":    neutral,
        "confidence": max(buy, sell) / total if total > 0 else 0,
        "rsi":        ind.get("RSI", 50),
        "macd":       ind.get("MACD.macd", 0),
        "macd_s":     ind.get("MACD.signal", 0),
        "ema20":      ind.get("EMA20", 0),
        "ema50":      ind.get("EMA50", 0),
        "close":      ind.get("close", 0),
        "adx":        ind.get("ADX", 0),
    }

def analyze_symbol(symbol):
    results = {}
    for tf in ["15m", "1h", "4h"]:
        a = get_tv_analysis(symbol, tf)
        p = parse_signal(a)
        if p:
            results[tf] = p
    return results

def get_consensus(results):
    if len(results) < 2:
        return "FLAT", 0
    directions = [results[tf]["direction"] for tf in results if results[tf]["direction"] != "FLAT"]
    if not directions:
        return "FLAT", 0
    long_v  = directions.count("LONG")
    short_v = directions.count("SHORT")
    if long_v >= 2 and short_v == 0:
        conf = sum(results[tf]["confidence"] for tf in results if results[tf]["direction"] == "LONG") / long_v
        return "LONG", conf
    if short_v >= 2 and long_v == 0:
        conf = sum(results[tf]["confidence"] for tf in results if results[tf]["direction"] == "SHORT") / short_v
        return "SHORT", conf
    return "FLAT", 0


# ══════════════════════════════════════════════
#  ФИЛЬТРЫ
# ══════════════════════════════════════════════

# ─── Фильтр 1: Время ──────────────────────────
def filter_time():
    """
    Торгуем только 10:00-22:00 по Киеву.
    Ночью рынок мёртвый — много ложных сигналов.
    """
    now_utc  = datetime.now(timezone.utc)
    now_kyiv = now_utc + timedelta(hours=TIMEZONE_OFFSET)
    hour     = now_kyiv.hour
    if TRADING_HOUR_START <= hour < TRADING_HOUR_END:
        return True, f"Время {hour:02d}:00 — торговое окно"
    return False, f"Время {hour:02d}:00 — вне торгового окна (10-22 Киев)"


# ─── Фильтр 2: BTC корреляция ─────────────────
def filter_btc_correlation(direction):
    """
    Все альткоины следуют за BTC.
    Если BTC резко падает — не открываем LONG.
    Если BTC резко растёт — не открываем SHORT.
    """
    try:
        candles = get_klines("BTCUSDT", interval="1h", limit=6)
        if len(candles) < 5:
            return True, "BTC данные недоступны"
        change = (candles[-1]["close"] - candles[-5]["close"]) / candles[-5]["close"] * 100

        if direction == "LONG" and change < BTC_DROP_BLOCK_PCT:
            return False, f"BTC упал {change:.1f}% — LONG заблокирован!"
        if direction == "SHORT" and change > BTC_PUMP_BLOCK_PCT:
            return False, f"BTC вырос +{change:.1f}% — SHORT заблокирован!"

        return True, f"BTC {change:+.1f}% — норма"
    except Exception as e:
        return True, f"BTC фильтр недоступен: {e}"


# ─── Фильтр 3: Объём ──────────────────────────
def filter_volume(symbol, direction):
    """
    Движение должно подтверждаться объёмом.
    Если объём ниже среднего — сигнал слабый.
    """
    try:
        candles = get_klines(symbol, interval="1h", limit=25)
        if len(candles) < 20:
            return True, "Объём недоступен"

        volumes    = [c["volume"] for c in candles]
        avg_volume = sum(volumes[-21:-1]) / 20
        last_vol   = volumes[-1]
        ratio      = last_vol / avg_volume if avg_volume > 0 else 1.0

        if ratio < VOLUME_SPIKE_MIN:
            return False, f"Объём x{ratio:.1f} — слабый (нужно x{VOLUME_SPIKE_MIN})"
        return True, f"Объём x{ratio:.1f} — подтверждён"
    except Exception as e:
        return True, f"Объём недоступен: {e}"


# ─── Фильтр 4: Уровни поддержки/сопротивления ─
def filter_levels(symbol, direction, price):
    """
    Не входим если цена вплотную к уровню против нас.
    LONG у сопротивления = плохо
    SHORT у поддержки = плохо
    """
    try:
        candles = get_klines(symbol, interval="1h", limit=100)
        if len(candles) < 20:
            return True, "Уровни недоступны"

        highs  = [c["high"]  for c in candles[:-1]]
        lows   = [c["low"]   for c in candles[:-1]]

        # Ближайшее сопротивление — максимум последних свечей
        resistance = max(highs[-20:])
        support    = min(lows[-20:])

        buffer = price * LEVEL_BUFFER_PCT / 100

        if direction == "LONG":
            dist_to_resistance = resistance - price
            if 0 < dist_to_resistance < buffer:
                return False, f"Сопротивление {resistance:.4f} слишком близко!"
            return True, f"До сопротивления {((resistance-price)/price*100):.1f}%"

        if direction == "SHORT":
            dist_to_support = price - support
            if 0 < dist_to_support < buffer:
                return False, f"Поддержка {support:.4f} слишком близко!"
            return True, f"До поддержки {((price-support)/price*100):.1f}%"

        return True, "Уровни норма"
    except Exception as e:
        return True, f"Уровни недоступны: {e}"


# ─── Применяем все фильтры ────────────────────
def apply_all_filters(symbol, direction, price):
    """
    Возвращает (passed, reasons_list, block_reason)
    """
    reasons = []
    blocked = ""

    # Фильтр 1: Время
    ok, reason = filter_time()
    reasons.append(("Время", ok, reason))
    if not ok:
        blocked = reason
        return False, reasons, blocked

    # Фильтр 2: BTC корреляция
    ok, reason = filter_btc_correlation(direction)
    reasons.append(("BTC", ok, reason))
    if not ok:
        blocked = reason
        return False, reasons, blocked

    # Фильтр 3: Объём
    ok, reason = filter_volume(symbol, direction)
    reasons.append(("Объём", ok, reason))
    if not ok:
        blocked = reason
        return False, reasons, blocked

    # Фильтр 4: Уровни
    ok, reason = filter_levels(symbol, direction, price)
    reasons.append(("Уровни", ok, reason))
    if not ok:
        blocked = reason
        return False, reasons, blocked

    return True, reasons, ""


# ─── Форматирование сигнала ───────────────────
def format_signal(symbol, direction, conf, results, price, filter_reasons):
    sl_pct  = 1.5
    tp1_pct = 1.5
    tp2_pct = 3.0
    tp3_pct = 5.0

    if direction == "LONG":
        sl  = price * (1 - sl_pct  / 100)
        tp1 = price * (1 + tp1_pct / 100)
        tp2 = price * (1 + tp2_pct / 100)
        tp3 = price * (1 + tp3_pct / 100)
    else:
        sl  = price * (1 + sl_pct  / 100)
        tp1 = price * (1 - tp1_pct / 100)
        tp2 = price * (1 - tp2_pct / 100)
        tp3 = price * (1 - tp3_pct / 100)

    now = datetime.now().strftime("%H:%M:%S")

    tf_lines = ""
    for tf in ["15m", "1h", "4h"]:
        if tf not in results:
            continue
        r = results[tf]
        tf_lines += (
            f"  {tf}: {r['direction']} | "
            f"BUY:{r['buy']} SELL:{r['sell']} | "
            f"RSI:{r['rsi']:.0f}\n"
        )

    filter_lines = ""
    for name, ok, reason in filter_reasons:
        icon = "OK" if ok else "BLOCK"
        filter_lines += f"  [{icon}] {name}: {reason}\n"

    r1h = results.get("1h", {})
    adx = r1h.get("adx", 0)
    trend_str = "Сильный" if adx > 25 else "Слабый"

    return (
        f"СИГНАЛ | {symbol} | {now}\n"
        f"{'━'*30}\n"
        f"{direction}\n"
        f"TradingView уверенность: {conf*100:.0f}%\n\n"
        f"Таймфреймы:\n{tf_lines}\n"
        f"ADX: {adx:.0f} ({trend_str} тренд)\n\n"
        f"Фильтры пройдены:\n{filter_lines}\n"
        f"ВХОД: {price:.4f} USDT | Плечо: 3x\n\n"
        f"ТЕЙК-ПРОФИТЫ:\n"
        f"  TP1: {tp1:.4f} (+{tp1_pct}%) — 50%\n"
        f"  TP2: {tp2:.4f} (+{tp2_pct}%) — 30%\n"
        f"  TP3: {tp3:.4f} (+{tp3_pct}%) — 20%\n\n"
        f"СТОП-ЛОСС: {sl:.4f} (-{sl_pct}%)\n\n"
        f"Позиция: $250 | Риск: $3.75"
    )


# ─── Тренд рынка ──────────────────────────────
def get_market_trend():
    try:
        a = get_tv_analysis("BTCUSDT", "1h")
        if not a:
            return "UNKNOWN"
        rec = a.summary["RECOMMENDATION"]
        if "BUY"  in rec: return "BULL"
        if "SELL" in rec: return "BEAR"
        return "SIDE"
    except Exception:
        return "UNKNOWN"


# ─── Состояние ────────────────────────────────
last_signal_ts = defaultdict(float)
auto_mode      = False
auto_thread    = None
last_update_id = 0
signal_stats   = {"sent": 0, "blocked": 0}

def should_send(symbol):
    return time.time() - last_signal_ts[symbol] >= SIGNAL_COOLDOWN


# ─── Команды ──────────────────────────────────
def run_best():
    # Сначала проверяем время
    time_ok, time_reason = filter_time()
    if not time_ok:
        send_message(
            f"Время {time_reason}\n\n"
            f"Торговое окно: 10:00-22:00 Киев.\n"
            f"Ночью слишком много ложных сигналов!"
        )
        return

    send_message(f"Анализирую {len(SYMBOLS)} пар через TradingView...\nЖди 1-2 минуты.")
    market = get_market_trend()
    send_message(f"Тренд BTC: {market}")

    candidates = []
    for symbol in SYMBOLS:
        try:
            results   = analyze_symbol(symbol)
            direction, conf = get_consensus(results)
            if direction == "FLAT":
                continue
            if market == "BULL"  and direction == "SHORT":
                continue
            if market == "BEAR"  and direction == "LONG":
                continue

            price = get_price(symbol)
            passed, reasons, blocked = apply_all_filters(symbol, direction, price)

            if not passed:
                signal_stats["blocked"] += 1
                print(f"[best] {symbol} заблокирован: {blocked}")
                continue

            candidates.append({
                "symbol":    symbol,
                "direction": direction,
                "conf":      conf,
                "results":   results,
                "price":     price,
                "reasons":   reasons,
            })
        except Exception as e:
            print(f"[best] {symbol}: {e}")

    if not candidates:
        send_message(
            "Нет сигналов прошедших все 4 фильтра.\n\n"
            "Это хорошо — бот защищает твой депозит!\n"
            "Попробуй через 30 минут."
        )
        return

    candidates.sort(key=lambda x: x["conf"], reverse=True)
    best = candidates[0]
    msg  = format_signal(
        best["symbol"], best["direction"],
        best["conf"], best["results"],
        best["price"], best["reasons"]
    )
    send_message(msg)
    last_signal_ts[best["symbol"]] = time.time()
    signal_stats["sent"] += 1

    if len(candidates) > 1:
        alt = ""
        for c in candidates[1:4]:
            alt += f"  {c['symbol']}: {c['direction']} {c['conf']*100:.0f}%\n"
        send_message(f"Альтернативы:\n{alt}")


def run_scan():
    time_ok, time_reason = filter_time()
    if not time_ok:
        send_message(f"{time_reason}\nСканирование в торговое окно 10:00-22:00 Киев.")
        return

    send_message(f"Сканирую {len(SYMBOLS)} пар...\nЖди 2-3 минуты.")
    market = get_market_trend()
    found  = []
    blocked_count = 0

    for symbol in SYMBOLS:
        try:
            results   = analyze_symbol(symbol)
            direction, conf = get_consensus(results)
            if direction == "FLAT":
                continue
            price  = get_price(symbol)
            passed, reasons, blocked = apply_all_filters(symbol, direction, price)
            if passed:
                found.append({"symbol": symbol, "direction": direction,
                              "conf": conf, "results": results})
            else:
                blocked_count += 1
        except Exception:
            pass

    if not found:
        send_message(
            f"Нет сигналов после всех фильтров.\n"
            f"Заблокировано фильтрами: {blocked_count}\n"
            f"Тренд BTC: {market}"
        )
        return

    lines = ""
    for f in sorted(found, key=lambda x: x["conf"], reverse=True):
        r1h = f["results"].get("1h", {})
        rsi = r1h.get("rsi", 0)
        lines += f"  {f['symbol']}: {f['direction']} {f['conf']*100:.0f}% | RSI:{rsi:.0f}\n"

    send_message(
        f"Результаты сканирования\n"
        f"Тренд BTC: {market}\n"
        f"Прошли фильтры: {len(found)}\n"
        f"Заблокировано: {blocked_count}\n"
        f"{'━'*25}\n"
        f"{lines}"
    )


def run_market():
    try:
        lines = ""
        for tf in ["15m", "1h", "4h"]:
            a = get_tv_analysis("BTCUSDT", tf)
            if a:
                rec = a.summary["RECOMMENDATION"]
                b   = a.summary["BUY"]
                s   = a.summary["SELL"]
                rsi = a.indicators.get("RSI", 0)
                lines += f"  {tf}: {rec}\n      BUY:{b} SELL:{s} | RSI:{rsi:.0f}\n"

        price = get_price("BTCUSDT")
        time_ok, time_reason = filter_time()
        time_str = "Торговое окно ОТКРЫТО" if time_ok else "Торговое окно ЗАКРЫТО"

        send_message(
            f"Рынок BTC | {datetime.now().strftime('%H:%M')}\n"
            f"Цена: {price:.1f} USDT\n"
            f"{'━'*25}\n"
            f"{lines}\n"
            f"{time_str}\n"
            f"Источник: TradingView"
        )
    except Exception as e:
        send_message(f"Ошибка: {e}")


def run_pumps():
    send_message("Ищу сильные движения (15м)...")
    found = []
    for symbol in SYMBOLS:
        try:
            a = get_tv_analysis(symbol, "15m")
            if not a:
                continue
            rec  = a.summary["RECOMMENDATION"]
            buy  = a.summary["BUY"]
            sell = a.summary["SELL"]
            rsi  = a.indicators.get("RSI", 50)
            if rec == "STRONG_BUY"  and buy  >= 18:
                found.append({"symbol": symbol, "type": "PUMP", "count": buy,  "rsi": rsi})
            elif rec == "STRONG_SELL" and sell >= 18:
                found.append({"symbol": symbol, "type": "DUMP", "count": sell, "rsi": rsi})
        except Exception:
            pass

    if not found:
        send_message("Нет сильных движений на 15м.")
        return

    lines = ""
    for f in sorted(found, key=lambda x: x["count"], reverse=True):
        lines += f"  {f['symbol']}: {f['type']} ({f['count']}/26) | RSI:{f['rsi']:.0f}\n"
    send_message(f"Сильные движения:\n{lines}")


def auto_loop():
    global auto_mode
    send_message(
        f"Авто-режим v6.1!\n"
        f"TradingView: 15м + 1ч + 4ч\n"
        f"Фильтры: Время + BTC + Объём + Уровни\n"
        f"Сканирую каждые {SCAN_INTERVAL//60} минут.\n"
        f"/stop чтобы остановить."
    )
    while auto_mode:
        try:
            time_ok, time_reason = filter_time()
            if not time_ok:
                print(f"[auto] {time_reason} — пропускаю")
                for _ in range(SCAN_INTERVAL):
                    if not auto_mode: break
                    time.sleep(1)
                continue

            market = get_market_trend()
            for symbol in SYMBOLS:
                if not auto_mode:
                    break
                try:
                    results   = analyze_symbol(symbol)
                    direction, conf = get_consensus(results)
                    if direction == "FLAT":
                        continue
                    if market == "BULL" and direction == "SHORT":
                        continue
                    if market == "BEAR" and direction == "LONG":
                        continue
                    if not should_send(symbol):
                        continue

                    price  = get_price(symbol)
                    passed, reasons, blocked = apply_all_filters(symbol, direction, price)
                    if not passed:
                        signal_stats["blocked"] += 1
                        continue

                    msg = format_signal(symbol, direction, conf, results, price, reasons)
                    send_message(msg)
                    last_signal_ts[symbol] = time.time()
                    signal_stats["sent"]  += 1
                except Exception as e:
                    print(f"[auto] {symbol}: {e}")

        except Exception as e:
            print(f"[auto_loop] {e}")

        for _ in range(SCAN_INTERVAL):
            if not auto_mode: break
            time.sleep(1)


# ─── Polling ──────────────────────────────────
def handle_command(text):
    global auto_mode, auto_thread
    cmd = text.strip().lower().split()[0]

    if cmd == "/start":
        time_ok, time_reason = filter_time()
        time_str = "Торговое окно ОТКРЫТО" if time_ok else "Торговое окно ЗАКРЫТО (10-22 Киев)"
        send_message(
            f"Бот готов! v6.1\n\n"
            f"Источник: TradingView\n"
            f"Анализ: 15м + 1ч + 4ч\n\n"
            f"Фильтры защиты:\n"
            f"  1. Время (10-22 Киев)\n"
            f"  2. BTC корреляция\n"
            f"  3. Объём подтверждение\n"
            f"  4. Уровни поддержки/сопротивления\n\n"
            f"{time_str}\n\n"
            f"/market — тренд BTC\n"
            f"/best   — лучший сигнал\n"
            f"/scan   — все пары\n"
            f"/pumps  — сильные движения\n"
            f"/auto   — авто-режим\n"
            f"/stop   — остановить авто\n"
            f"/status — статус"
        )

    elif cmd == "/market":
        threading.Thread(target=run_market, daemon=True).start()

    elif cmd == "/best":
        threading.Thread(target=run_best, daemon=True).start()

    elif cmd == "/scan":
        threading.Thread(target=run_scan, daemon=True).start()

    elif cmd == "/pumps":
        threading.Thread(target=run_pumps, daemon=True).start()

    elif cmd == "/auto":
        if auto_mode:
            send_message("Авто-режим уже работает! /stop чтобы остановить.")
            return
        auto_mode   = True
        auto_thread = threading.Thread(target=auto_loop, daemon=True)
        auto_thread.start()

    elif cmd == "/stop":
        if not auto_mode:
            send_message("Авто-режим не был включён.")
            return
        auto_mode = False
        send_message("Авто-режим остановлен.")

    elif cmd == "/status":
        mode = "Работает" if auto_mode else "Остановлен"
        time_ok, time_reason = filter_time()
        send_message(
            f"Статус бота v6.1\n"
            f"Авто-режим: {mode}\n"
            f"Пар: {len(SYMBOLS)}\n"
            f"Сигналов отправлено: {signal_stats['sent']}\n"
            f"Заблокировано фильтрами: {signal_stats['blocked']}\n"
            f"{'━'*20}\n"
            f"Фильтры:\n"
            f"  Время: {'OK' if time_ok else 'ЗАКРЫТО'}\n"
            f"  BTC корреляция: активен\n"
            f"  Объём (x{VOLUME_SPIKE_MIN}): активен\n"
            f"  Уровни ({LEVEL_BUFFER_PCT}%): активен\n"
            f"Источник: TradingView 15м+1ч+4ч"
        )


def get_updates():
    global last_update_id
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    try:
        r = requests.get(url, params={
            "offset": last_update_id + 1, "timeout": 10
        }, timeout=15)
        data = r.json()
        if data.get("ok"):
            return data.get("result", [])
    except Exception:
        pass
    return []


def polling_loop():
    global last_update_id
    print("[Bot] Запущен v6.1")
    send_message(
        "AI Scalper Bot v6.1!\n\n"
        "TradingView + 4 фильтра защиты:\n"
        "  1. Время (10-22 Киев)\n"
        "  2. BTC корреляция\n"
        "  3. Объём подтверждение\n"
        "  4. Уровни поддержки/сопротивления\n\n"
        "Напиши /best для первого сигнала!"
    )
    while True:
        try:
            updates = get_updates()
            for update in updates:
                last_update_id = update["update_id"]
                msg     = update.get("message", {})
                chat_id = str(msg.get("chat", {}).get("id", ""))
                text    = msg.get("text", "")
                if chat_id == str(TELEGRAM_CHAT_ID) and text.startswith("/"):
                    print(f"[Bot] {text}")
                    handle_command(text)
        except Exception as e:
            print(f"[Polling] {e}")
        time.sleep(1)


if __name__ == "__main__":
    print("=" * 50)
    print("  AI Crypto Scalper v6.1")
    print(f"  TradingView | 4 фильтра | {len(SYMBOLS)} пар")
    print("=" * 50)
    polling_loop()
