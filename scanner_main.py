"""
ULTRA SPOT SCANNER — Binance SPOT торговля
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ТОЛЬКО СПОТ! Никаких фьючерсов и плеча!
Один качественный сигнал > много слабых
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import requests
import time
import json
import threading
import os
from datetime import datetime, timezone

# ──────────────────────────────────────────
# КОНФИГ
# ──────────────────────────────────────────
TOKEN    = os.environ.get("TELEGRAM_TOKEN", "")
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))

SCAN_INTERVAL = 900   # 15 минут
TAKE_PROFIT   = 10.0  # +10% → сигнал продавать
STOP_LOSS     = -5.0  # -5%  → стоп-лосс
MIN_SCORE     = 80    # минимальный балл для сигнала (строгий!)

# Только SPOT endpoints Binance
BINANCE_24H    = "https://api.binance.com/api/v3/ticker/24hr"
BINANCE_KLINES = "https://api.binance.com/api/v3/klines"
BINANCE_PRICE  = "https://api.binance.com/api/v3/ticker/price"
BINANCE_DEPTH  = "https://api.binance.com/api/v3/depth"
COINGECKO_URL  = "https://api.coingecko.com/api/v3/search/trending"

BLACKLIST = set(["LUNAUSDT","TERRAUSDT","USTUSDT","USDTUSDT"])

# ──────────────────────────────────────────
# СОСТОЯНИЕ
# ──────────────────────────────────────────
scanner_running  = False  # выключен по умолчанию — включаешь сам
active_position  = None   # { "symbol", "entry", "peak" } — только одна позиция
signal_history   = []     # история сигналов
last_update_id   = 0
scan_lock        = threading.Lock()

# ──────────────────────────────────────────
# TELEGRAM
# ──────────────────────────────────────────

def send_message(chat_id, text, buttons=None):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if buttons:
        payload["reply_markup"] = json.dumps({"inline_keyboard": buttons})
    try:
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        print(f"[scanner] send error: {e}")

def send_typing(chat_id):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendChatAction",
            data={"chat_id": chat_id, "action": "typing"}, timeout=5
        )
    except: pass

def answer_callback(callback_id, text=""):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/answerCallbackQuery",
            json={"callback_query_id": callback_id, "text": text}, timeout=5
        )
    except: pass

def get_updates():
    global last_update_id
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TOKEN}/getUpdates",
            params={"offset": last_update_id + 1, "timeout": 10},
            timeout=15
        )
        data = r.json()
        if data.get("ok"):
            return data.get("result", [])
    except Exception as e:
        print(f"[scanner] getUpdates error: {e}")
    return []

def delete_webhook():
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/deleteWebhook",
            json={"drop_pending_updates": True}, timeout=10
        )
        print(f"[scanner] deleteWebhook: {r.json().get('description','ok')}")
    except Exception as e:
        print(f"[scanner] deleteWebhook error: {e}")

# ──────────────────────────────────────────
# РЫНОЧНЫЕ ДАННЫЕ (ТОЛЬКО SPOT API)
# ──────────────────────────────────────────

def get_klines(symbol, interval, limit=50):
    """Получаем свечи с Binance SPOT /api/v3"""
    try:
        r = requests.get(
            f"{BINANCE_KLINES}",
            params={"symbol": symbol, "interval": interval, "limit": limit},
            timeout=10
        )
        data = r.json()
        if not isinstance(data, list) or len(data) < 10:
            return None
        return {
            "opens":   [float(x[1]) for x in data],
            "highs":   [float(x[2]) for x in data],
            "lows":    [float(x[3]) for x in data],
            "closes":  [float(x[4]) for x in data],
            "volumes": [float(x[5]) for x in data],
        }
    except:
        return None

def get_price(symbol):
    try:
        r = requests.get(f"{BINANCE_PRICE}", params={"symbol": symbol}, timeout=5)
        return float(r.json()["price"])
    except:
        return None

def get_top_pairs():
    """Топ SPOT пары по объёму — исключаем стейблкоины и проблемные токены"""
    try:
        data = requests.get(BINANCE_24H, timeout=10).json()
    except:
        return []

    pairs = []
    STABLES = {"BUSD","USDC","TUSD","USDP","DAI","FDUSD","UST","USDD"}
    for coin in data:
        sym = coin["symbol"]
        if not sym.endswith("USDT"): continue
        base = sym.replace("USDT","")
        if base in STABLES: continue
        if sym in BLACKLIST: continue
        # Фильтр: хороший объём, не перегрета
        vol    = float(coin["quoteVolume"])
        change = float(coin["priceChangePercent"])
        if vol < 10_000_000: continue   # минимум $10М объёма
        if change > 15: continue        # не берём уже улетевшие
        if change < -15: continue       # и сильно падающие
        pairs.append((sym, vol, change))

    pairs.sort(key=lambda x: x[1], reverse=True)
    return [p[0] for p in pairs[:100]]  # топ 100

def get_trending():
    try:
        data = requests.get(COINGECKO_URL, timeout=10).json()
        return set(c["item"]["symbol"].upper()+"USDT" for c in data.get("coins",[]))
    except:
        return set()

# ──────────────────────────────────────────
# ИНДИКАТОРЫ
# ──────────────────────────────────────────

def calc_rsi(closes, period=14):
    if len(closes) < period+1: return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains[-period:]) / period
    al = sum(losses[-period:]) / period
    if al == 0: return 100.0
    return round(100 - 100/(1 + ag/al), 1)

def calc_ema(closes, n):
    if len(closes) < n: return closes[-1]
    k = 2/(n+1)
    ema = closes[0]
    for p in closes[1:]: ema = p*k + ema*(1-k)
    return ema

def calc_macd(closes):
    """Возвращает (macd_val, signal_val, crossover_up)"""
    if len(closes) < 26: return 0, 0, False
    ema12 = calc_ema(closes[-26:], 12)
    ema26 = calc_ema(closes[-26:], 26)
    macd  = ema12 - ema26
    # Предыдущий MACD
    ema12p = calc_ema(closes[-27:-1], 12) if len(closes) >= 27 else ema12
    ema26p = calc_ema(closes[-27:-1], 26) if len(closes) >= 27 else ema26
    macd_prev = ema12p - ema26p
    crossover = macd_prev < 0 and macd > 0
    return round(macd,6), round(macd-macd_prev,6), crossover

def calc_supertrend(highs, lows, closes, period=10, mult=3.0):
    if len(closes) < period+1: return "neutral"
    tr_vals = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
               for i in range(1,len(closes))]
    atr = sum(tr_vals[-period:]) / period
    hl2 = (highs[-1]+lows[-1]) / 2
    upper = hl2 + mult*atr
    lower = hl2 - mult*atr
    if closes[-1] > lower: return "up"
    if closes[-1] < upper: return "down"
    return "neutral"

def calc_vwap(klines):
    closes  = klines["closes"]
    highs   = klines["highs"]
    lows    = klines["lows"]
    volumes = klines["volumes"]
    if not volumes or sum(volumes)==0: return None
    tp = [(highs[i]+lows[i]+closes[i])/3 for i in range(len(closes))]
    return sum(tp[i]*volumes[i] for i in range(len(closes))) / sum(volumes)

def calc_bollinger(closes, period=20, std_mult=2):
    if len(closes) < period: return None, None, None
    sma  = sum(closes[-period:]) / period
    std  = (sum((c-sma)**2 for c in closes[-period:]) / period) ** 0.5
    return sma, sma + std_mult*std, sma - std_mult*std

def volume_spike(volumes):
    if len(volumes) < 10: return 1.0
    avg = sum(volumes[-11:-1]) / 10
    return round(volumes[-1]/avg, 1) if avg > 0 else 1.0

def orderbook_ratio(symbol):
    try:
        data = requests.get(f"{BINANCE_DEPTH}", params={"symbol":symbol,"limit":20}, timeout=8).json()
        bids = sum(float(b[1]) for b in data.get("bids",[]))
        asks = sum(float(a[1]) for a in data.get("asks",[]))
        return round(bids/asks, 2) if asks > 0 else 1.0
    except:
        return 1.0

# ──────────────────────────────────────────
# МЕГА-АНАЛИЗ — СТРОГИЙ ФИЛЬТР
# ──────────────────────────────────────────

def analyze_coin(symbol, trending):
    """
    Комплексный анализ монеты.
    Возвращает (score, report) или (0, None) если данных нет.
    Высокий порог MIN_SCORE=80 — только лучшие сигналы!
    """
    # Получаем данные на разных таймфреймах
    k15m = get_klines(symbol, "15m", 50)
    k1h  = get_klines(symbol, "1h",  50)
    k4h  = get_klines(symbol, "4h",  30)

    if not k15m or not k1h:
        return 0, None

    c15 = k15m["closes"]
    c1h = k1h["closes"]
    c4h = k4h["closes"] if k4h else c1h

    score   = 0
    reasons = []
    warns   = []

    # ── 1. RSI (14) на 1ч ─────────────────────
    rsi = calc_rsi(c1h)
    if rsi < 30:
        score += 25
        reasons.append(f"RSI {rsi} 🟢 сильно перепродан")
    elif rsi < 40:
        score += 15
        reasons.append(f"RSI {rsi} 🟡 перепродан")
    elif rsi > 70:
        score -= 25
        warns.append(f"RSI {rsi} 🔴 перекуплен")
    else:
        reasons.append(f"RSI {rsi} нейтральный")

    # ── 2. MACD на 1ч ─────────────────────────
    macd_val, macd_diff, macd_cross = calc_macd(c1h)
    if macd_cross:
        score += 20
        reasons.append("MACD ✅ пересечение вверх")
    elif macd_val > 0:
        score += 8
        reasons.append("MACD 🟡 положительный")
    else:
        warns.append("MACD ➖ отрицательный")

    # ── 3. Supertrend на 1ч ───────────────────
    st = calc_supertrend(k1h["highs"], k1h["lows"], c1h)
    if st == "up":
        score += 20
        reasons.append("Supertrend 🟢 вверх")
    elif st == "down":
        score -= 20
        warns.append("Supertrend 🔴 вниз")

    # ── 4. EMA тренд (50 > 200 = бычий) ──────
    ema20 = calc_ema(c1h, 20)
    ema50 = calc_ema(c1h, 50)
    price = c1h[-1]
    if price > ema20 > ema50:
        score += 15
        reasons.append("EMA ✅ цена > EMA20 > EMA50")
    elif price < ema20:
        score -= 10
        warns.append("EMA ⬇️ цена ниже EMA20")

    # ── 5. VWAP ───────────────────────────────
    vwap = calc_vwap(k1h)
    if vwap and price > vwap:
        score += 15
        reasons.append(f"VWAP ✅ цена выше ({round(vwap,4)})")
    elif vwap and price < vwap:
        score -= 8
        warns.append(f"VWAP ⬇️ цена ниже ({round(vwap,4)})")

    # ── 6. Bollinger Bands ────────────────────
    bb_mid, bb_up, bb_low = calc_bollinger(c1h)
    if bb_low and price <= bb_low * 1.01:
        score += 20
        reasons.append("Bollinger 🟢 цена у нижней полосы")
    elif bb_up and price >= bb_up * 0.99:
        score -= 15
        warns.append("Bollinger 🔴 цена у верхней полосы")

    # ── 7. Объём — спайк ──────────────────────
    vol_spike = volume_spike(k15m["volumes"])
    if vol_spike >= 2.5:
        score += 20
        reasons.append(f"Объём 🐋 x{vol_spike} спайк!")
    elif vol_spike >= 1.5:
        score += 10
        reasons.append(f"Объём ✅ x{vol_spike}")
    elif vol_spike < 0.7:
        score -= 5
        warns.append(f"Объём ⬇️ x{vol_spike} низкий")

    # ── 8. Стакан ─────────────────────────────
    ob = orderbook_ratio(symbol)
    if ob >= 1.5:
        score += 15
        reasons.append(f"Стакан 💰 покупатели x{ob}")
    elif ob >= 1.2:
        score += 8
        reasons.append(f"Стакан ✅ перевес покупок x{ob}")
    elif ob < 0.8:
        score -= 10
        warns.append(f"Стакан ⬇️ продавцы x{ob}")

    # ── 9. Многотаймфреймный тренд ────────────
    mtf = 0
    for closes_tf, name in [(c15, "15м"), (c1h, "1ч"), (c4h, "4ч")]:
        if len(closes_tf) >= 5:
            if closes_tf[-1] > closes_tf[-5]:
                mtf += 1
    if mtf == 3:
        score += 20
        reasons.append("МТФ 🟢 все 3 таймфрейма вверх")
    elif mtf == 2:
        score += 10
        reasons.append(f"МТФ 🟡 {mtf}/3 таймфрейма вверх")
    else:
        warns.append(f"МТФ ⚠️ только {mtf}/3 вверх")

    # ── 10. CoinGecko trending ────────────────
    if symbol in trending:
        score += 15
        reasons.append("CoinGecko 🔥 Trending монета!")

    # ── Итог ─────────────────────────────────
    report = {
        "symbol":    symbol,
        "price":     round(price, 8),
        "score":     score,
        "rsi":       rsi,
        "macd":      macd_cross,
        "supertrend": st,
        "vwap":      round(vwap,4) if vwap else None,
        "vol_spike": vol_spike,
        "ob_ratio":  ob,
        "mtf":       mtf,
        "trending":  symbol in trending,
        "reasons":   reasons,
        "warns":     warns,
    }
    return score, report

# ──────────────────────────────────────────
# ФОРМАТ СИГНАЛА
# ──────────────────────────────────────────

def format_signal(report):
    sym   = report["symbol"]
    price = report["price"]
    score = report["score"]
    tp    = round(price * (1 + TAKE_PROFIT/100), 8)
    sl    = round(price * (1 + STOP_LOSS/100), 8)

    if score >= 110:   strength = "💎 ИСКЛЮЧИТЕЛЬНЫЙ"
    elif score >= 95:  strength = "🔥🔥🔥 ОЧЕНЬ СИЛЬНЫЙ"
    elif score >= 80:  strength = "🔥🔥 СИЛЬНЫЙ"
    else:              strength = "🔥 ХОРОШИЙ"

    reasons_text = "\n".join(f"  ✅ {r}" for r in report["reasons"])
    warns_text   = "\n".join(f"  ⚠️ {w}" for w in report["warns"]) if report["warns"] else "  Нет предупреждений"

    text = f"""
🚨 <b>СИГНАЛ ПОКУПКИ — СПОТ</b> 🚨

Монета: <b>{sym}</b>
Цена входа: <b>{price} USDT</b>

🎯 Цель: <b>{tp} USDT (+{TAKE_PROFIT}%)</b>
🛑 Стоп-лосс: <b>{sl} USDT ({STOP_LOSS}%)</b>

📊 <b>Качество сигнала: {score} баллов</b>
{strength}

✅ <b>Факторы ЗА:</b>
{reasons_text}

⚠️ <b>Риски:</b>
{warns_text}

⚠️ <b>ТОЛЬКО СПОТОВАЯ ТОРГОВЛЯ!</b>
Никаких фьючерсов и плеча!
"""
    return text

# ──────────────────────────────────────────
# СКАНЕР РЫНКА
# ──────────────────────────────────────────

def scan_market():
    """
    Сканирует рынок и находит ОДИН лучший сигнал.
    Строгий фильтр — MIN_SCORE=80.
    """
    global scanner_running

    # Проверка BTC тренда
    btc_klines = get_klines("BTCUSDT", "1h", 20)
    btc_trend  = "neutral"
    if btc_klines:
        btc_closes = btc_klines["closes"]
        btc_change = (btc_closes[-1] - btc_closes[-6]) / btc_closes[-6] * 100
        if btc_change <= -3:
            btc_trend = "down"
            send_message(OWNER_ID,
                "⚠️ <b>BTC падает сильно!</b>\n"
                f"Изменение: {round(btc_change,1)}%\n"
                "Сканирование приостановлено до стабилизации."
            )
            return
        elif btc_change >= 1:
            btc_trend = "up"

    send_message(OWNER_ID,
        f"🔍 <b>Сканирую рынок...</b>\n"
        f"BTC тренд: {'🟢 Растёт' if btc_trend=='up' else '🟡 Нейтральный'}\n"
        f"Ищу лучшую монету для покупки..."
    )

    pairs    = get_top_pairs()
    trending = get_trending()

    if not pairs:
        send_message(OWNER_ID, "❌ Не удалось получить данные с Binance. Попробую позже.")
        return

    print(f"[scanner] Анализирую {len(pairs)} пар...")
    candidates = []

    for symbol in pairs:
        try:
            score, report = analyze_coin(symbol, trending)
            if score >= MIN_SCORE:
                candidates.append((score, report))
                print(f"[scanner] ✅ {symbol}: {score} баллов")
        except Exception as e:
            print(f"[scanner] {symbol} error: {e}")
            continue

    if not candidates:
        send_message(OWNER_ID,
            "🔍 <b>Сканирование завершено</b>\n\n"
            f"Проверено пар: {len(pairs)}\n"
            f"Сигналов: 0\n\n"
            "Ни одна монета не прошла все фильтры.\n"
            f"Следующее сканирование через {SCAN_INTERVAL//60} минут."
        )
        return

    # Сортируем по score — берём лучший
    candidates.sort(key=lambda x: x[0], reverse=True)
    best_score, best_report = candidates[0]

    # Сохраняем в историю
    signal_history.append({
        "symbol": best_report["symbol"],
        "price":  best_report["price"],
        "score":  best_score,
        "time":   datetime.now().strftime("%d.%m %H:%M"),
    })
    if len(signal_history) > 20:
        signal_history.pop(0)

    # Отправляем сигнал
    text = format_signal(best_report)
    send_message(OWNER_ID, text, buttons=[[
        {"text": "✅ Купил!", "callback_data": f"buy_{best_report['symbol']}_{best_report['price']}"},
        {"text": "❌ Отклонить", "callback_data": f"skip_{best_report['symbol']}"},
    ]])

    # Если есть второй хороший сигнал — тоже показываем
    if len(candidates) > 1:
        second_score, second_report = candidates[1]
        if second_score >= MIN_SCORE + 10:  # только если значительно лучше порога
            text2 = format_signal(second_report)
            send_message(OWNER_ID,
                f"📊 <b>Альтернативный сигнал (#{2}):</b>",
            )
            send_message(OWNER_ID, text2, buttons=[[
                {"text": "✅ Купил!", "callback_data": f"buy_{second_report['symbol']}_{second_report['price']}"},
                {"text": "❌ Отклонить", "callback_data": f"skip_{second_report['symbol']}"},
            ]])

# ──────────────────────────────────────────
# ТРЕКЕР ПОЗИЦИИ
# ──────────────────────────────────────────

def track_position():
    """Следит за открытой позицией и шлёт сигнал продажи"""
    global active_position

    while True:
        if active_position:
            try:
                sym    = active_position["symbol"]
                entry  = active_position["entry"]
                peak   = active_position.get("peak", entry)
                price  = get_price(sym)

                if price is None:
                    time.sleep(60)
                    continue

                # Обновляем пик
                if price > peak:
                    active_position["peak"] = price
                    peak = price

                profit     = (price - entry) / entry * 100
                peak_profit = (peak - entry) / entry * 100

                print(f"[tracker] {sym}: {round(profit,2)}% (пик: {round(peak_profit,2)}%)")

                # Трейлинг стоп: если выросла на 5%+ и откатила на 3% от пика
                if peak_profit >= 5 and price <= peak * 0.97:
                    locked = round((price-entry)/entry*100, 2)
                    send_message(OWNER_ID, f"""🔒 <b>ТРЕЙЛИНГ СТОП!</b>

Монета: <b>{sym}</b>
Цена входа: {entry}
Пик цены: {round(peak,8)}
Сейчас: <b>{price}</b>

Зафиксировано: <b>+{locked}%</b>
Рекомендую продать!""",
                    buttons=[[{"text":"💰 Продал по трейлингу","callback_data":f"sold_{sym}_{price}"}]])

                # Цель достигнута +10%
                elif profit >= TAKE_PROFIT:
                    send_message(OWNER_ID, f"""💰 <b>ЦЕЛЬ ДОСТИГНУТА!</b>

Монета: <b>{sym}</b>
Цена входа: {entry}
Сейчас: <b>{price}</b>

Прибыль: <b>+{round(profit,2)}%</b> 🎉

Рекомендую продать!""",
                    buttons=[[{"text":f"💰 Продал +{round(profit,1)}%","callback_data":f"sold_{sym}_{price}"}]])

                # Стоп-лосс -5%
                elif profit <= STOP_LOSS:
                    send_message(OWNER_ID, f"""🛑 <b>СТОП-ЛОСС!</b>

Монета: <b>{sym}</b>
Цена входа: {entry}
Сейчас: <b>{price}</b>

Убыток: <b>{round(profit,2)}%</b>
Продай сейчас чтобы не потерять больше!""",
                    buttons=[[{"text":f"🛑 Продал {round(profit,1)}%","callback_data":f"sold_{sym}_{price}"}]])

            except Exception as e:
                print(f"[tracker] error: {e}")

        time.sleep(60)

# ──────────────────────────────────────────
# СКАНЕР ЦИКЛ
# ──────────────────────────────────────────

def scanner_cycle():
    """Основной цикл сканирования"""
    global scanner_running

    while True:
        if scanner_running and not active_position:
            try:
                with scan_lock:
                    scan_market()
            except Exception as e:
                print(f"[scanner_cycle] error: {e}")
                send_message(OWNER_ID, f"❌ Ошибка сканирования: {e}")

        elif active_position:
            # Есть открытая позиция — не сканируем
            sym    = active_position["symbol"]
            entry  = active_position["entry"]
            price  = get_price(sym) or entry
            profit = round((price-entry)/entry*100, 2)
            print(f"[scanner_cycle] Позиция открыта: {sym} {profit}% — сканирование на паузе")

        time.sleep(SCAN_INTERVAL)

# ──────────────────────────────────────────
# КОМАНДЫ
# ──────────────────────────────────────────

def handle_message(text, chat_id):
    global scanner_running

    cmd = text.split("@")[0].strip().lower()

    if cmd == "/start":
        status     = "🟢 Работает" if scanner_running else "🔴 Остановлен"
        pos_status = f"📈 Открыта: {active_position['symbol']}" if active_position else "📭 Нет позиций"
        send_message(chat_id, f"""🤖 <b>Бот для SPOT торговли Binance запущен!</b>

⚠️ Только спотовая торговля!
Никаких фьючерсов и плеча!

Статус сканера: {status}
Позиция: {pos_status}

<b>Команды:</b>
/scan — запустить сканирование
/stop — остановить сканирование
/status — статус бота
/history — последние сигналы
/active — активный сигнал
/ping — проверка что бот жив""")

    elif cmd == "/scan":
        if active_position:
            sym = active_position["symbol"]
            send_message(chat_id,
                f"⏸ <b>Сканирование на паузе</b>\n\n"
                f"У тебя открыта позиция по <b>{sym}</b>\n"
                f"Сначала продай монету — тогда начну искать новую!"
            )
        else:
            scanner_running = True
            send_message(chat_id,
                "🚀 <b>Сканирование включено!</b>\n\n"
                f"Проверяю рынок каждые {SCAN_INTERVAL//60} минут.\n"
                "Ищу только качественные сигналы — жди! 🔍"
            )
            # Запускаем сканирование сразу
            threading.Thread(target=scan_market, daemon=True).start()

    elif cmd == "/stop":
        scanner_running = False
        send_message(chat_id, "⛔ <b>Сканирование остановлено</b>")

    elif cmd == "/ping":
        now = datetime.now().strftime("%H:%M:%S")
        send_message(chat_id, f"🏓 Бот живой! Время: {now}")

    elif cmd == "/status":
        status    = "🟢 Работает" if scanner_running else "🔴 Остановлен"
        btc_klines = get_klines("BTCUSDT","1h",10)
        btc_price  = round(btc_klines["closes"][-1],0) if btc_klines else "N/A"
        if active_position:
            sym    = active_position["symbol"]
            entry  = active_position["entry"]
            price  = get_price(sym) or entry
            profit = round((price-entry)/entry*100, 2)
            pos_text = f"📈 <b>{sym}</b>: {profit}% (вход: {entry})"
        else:
            pos_text = "📭 Нет открытых позиций"
        send_message(chat_id, f"""📊 <b>Статус бота</b>

Сканер: {status}
BTC: ${btc_price}
Позиция: {pos_text}
Сигналов найдено: {len(signal_history)}""")

    elif cmd in ("/history", "/aktiv signal", "/active"):
        if signal_history:
            text_h = "📜 <b>Последние сигналы:</b>\n\n"
            for s in reversed(signal_history[-10:]):
                text_h += f"• <b>{s['symbol']}</b> @ {s['price']} | {s['score']} баллов | {s['time']}\n"
            send_message(chat_id, text_h)
        else:
            send_message(chat_id, "📭 Сигналов ещё не было.\nЗапусти /scan чтобы найти первую монету!")

    else:
        send_message(chat_id,
            "❓ Неизвестная команда.\n\n"
            "/start — показать все команды"
        )

def handle_callback(q, callback_id, chat_id):
    global active_position, scanner_running

    answer_callback(callback_id)

    # Купить монету
    if q.startswith("buy_"):
        parts  = q.split("_")
        symbol = parts[1]
        try:
            entry = float(parts[2])
        except:
            entry = get_price(symbol) or 0

        active_position = {"symbol": symbol, "entry": entry, "peak": entry}
        scanner_running = False  # пауза сканирования

        tp = round(entry * (1+TAKE_PROFIT/100), 8)
        sl = round(entry * (1+STOP_LOSS/100), 8)

        send_message(OWNER_ID, f"""✅ <b>Позиция открыта!</b>

Монета: <b>{symbol}</b>
Цена входа: <b>{entry} USDT</b>
Цель: <b>{tp} USDT (+{TAKE_PROFIT}%)</b>
Стоп-лосс: <b>{sl} USDT ({STOP_LOSS}%)</b>

⏸ Сканирование остановлено.
Слежу только за <b>{symbol}</b>...
Пришлю сигнал когда продавать! 👀""")

    # Отклонить сигнал
    elif q.startswith("skip_"):
        symbol = q.split("_")[1]
        send_message(OWNER_ID,
            f"⏭ <b>{symbol}</b> отклонён\n\n"
            "🔍 Продолжаю поиск лучших вариантов..."
        )
        # Запускаем новое сканирование через паузу
        def delayed_scan():
            time.sleep(30)
            if scanner_running and not active_position:
                scan_market()
        threading.Thread(target=delayed_scan, daemon=True).start()

    # Продать монету
    elif q.startswith("sold_"):
        parts  = q.split("_")
        symbol = parts[1]
        try:
            sell_price = float(parts[2])
        except:
            sell_price = get_price(symbol) or 0

        if active_position and active_position["symbol"] == symbol:
            entry  = active_position["entry"]
            profit = round((sell_price-entry)/entry*100, 2)
            emoji  = "✅" if profit > 0 else "❌"

            signal_history.append({
                "symbol": f"{symbol} ПРОДАНО",
                "price":  sell_price,
                "score":  profit,
                "time":   datetime.now().strftime("%d.%m %H:%M"),
            })

            active_position = None
            scanner_running = True

            send_message(OWNER_ID, f"""{emoji} <b>Сделка закрыта!</b>

Монета: <b>{symbol}</b>
Вход: {entry} USDT
Выход: <b>{sell_price} USDT</b>
Результат: <b>{'+' if profit>0 else ''}{profit}%</b>

🔍 <b>Сканирование возобновлено!</b>
Ищу следующую монету...""")

            # Сразу начинаем поиск
            threading.Thread(target=scan_market, daemon=True).start()

        else:
            send_message(OWNER_ID, f"✅ {symbol} продан. Ищу новую монету...")
            active_position = None
            scanner_running = True
            threading.Thread(target=scan_market, daemon=True).start()

# ──────────────────────────────────────────
# POLLING LOOP
# ──────────────────────────────────────────

def polling_loop():
    global last_update_id

    delete_webhook()
    time.sleep(2)

    # Запускаем фоновые потоки
    threading.Thread(target=scanner_cycle, daemon=True).start()
    threading.Thread(target=track_position, daemon=True).start()

    print("[scanner] ✅ Polling запущен!")
    send_message(OWNER_ID,
        "🤖 <b>Спот Бот запущен!</b>\n\n"
        "Напиши /scan чтобы начать сканирование рынка!\n"
        "Ищу только КАЧЕСТВЕННЫЕ сигналы 💎"
    )

    while True:
        try:
            updates = get_updates()
            for update in updates:
                last_update_id = update["update_id"]

                if "message" in update:
                    msg  = update["message"]
                    text = msg.get("text","")
                    chat = msg["chat"]["id"]
                    if text:
                        handle_message(text, chat)

                elif "callback_query" in update:
                    q    = update["callback_query"]["data"]
                    cid  = update["callback_query"]["id"]
                    chat = update["callback_query"]["message"]["chat"]["id"]
                    handle_callback(q, cid, chat)

        except Exception as e:
            print(f"[scanner] polling error: {e}")
            time.sleep(5)

        time.sleep(1)

if __name__ == "__main__":
    polling_loop()
