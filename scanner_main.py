import requests
import time
import json
import threading
import os
from flask import Flask, request
from datetime import datetime, timezone

# ---------------- КОНФИГ ---------------- #

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))
RENDER_URL = os.environ.get("RENDER_URL", "")

app = Flask(__name__)

SCAN_INTERVAL = 300  # каждые 5 минут

BINANCE_24H    = "https://api.binance.com/api/v3/ticker/24hr"
BINANCE_KLINES = "https://api.binance.com/api/v3/klines"
BINANCE_PRICE  = "https://api.binance.com/api/v3/ticker/price"
BINANCE_DEPTH  = "https://api.binance.com/api/v3/depth"
COINGECKO_TRENDING = "https://api.coingecko.com/api/v3/search/trending"

# УЛУЧШЕНИЕ 6: Blacklist монет
BLACKLIST = set(["LUNAUSDT", "TERRAUSDT", "USTUSDT"])

scanner_running = True
active_signals = []
active_signals_time = {}
tracked_coins = {}   # { symbol: {"entry": price, "peak": price} }
trade_history = []
win_count = 0
loss_count = 0

# ---------------- TELEGRAM ---------------- #

def send_message(chat_id, text, buttons=None):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if buttons:
        payload["reply_markup"] = json.dumps({"inline_keyboard": buttons})
    try:
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        print(f"Ошибка отправки: {e}")

def set_webhook():
    if not RENDER_URL:
        print("RENDER_URL не задан!")
        return
    url = f"https://api.telegram.org/bot{TOKEN}/setWebhook"
    try:
        r = requests.post(url, json={"url": RENDER_URL.rstrip("/") + "/scanner"}, timeout=10)
        print(f"Webhook: {r.json()}")
    except Exception as e:
        print(f"Ошибка webhook: {e}")

# ---------------- ДАННЫЕ ---------------- #

def get_klines(symbol, interval, limit=40):
    try:
        url = f"{BINANCE_KLINES}?symbol={symbol}&interval={interval}&limit={limit}"
        data = requests.get(url, timeout=10).json()
        if not isinstance(data, list) or len(data) < 5:
            return [], [], [], []
        highs   = [float(x[2]) for x in data]
        lows    = [float(x[3]) for x in data]
        closes  = [float(x[4]) for x in data]
        volumes = [float(x[5]) for x in data]
        return closes, volumes, highs, lows
    except Exception as e:
        print(f"Ошибка klines {symbol}: {e}")
        return [], [], [], []

def get_top_pairs():
    try:
        data = requests.get(BINANCE_24H, timeout=10).json()
    except Exception as e:
        print(f"Ошибка пар: {e}")
        return []
    pairs = []
    for coin in data:
        symbol = coin["symbol"]
        if not symbol.endswith("USDT"):
            continue
        if any(s in symbol for s in ["BUSD", "USDC", "TUSD", "USDP", "DAI", "FDUSD"]):
            continue
        if symbol in BLACKLIST:
            continue
        volume = float(coin["quoteVolume"])
        change = float(coin["priceChangePercent"])
        if volume < 25_000_000:
            continue
        if change > 8:
            continue
        pairs.append((symbol, volume))
    pairs.sort(key=lambda x: x[1], reverse=True)
    return [p[0] for p in pairs[:150]]

# ---------------- УЛУЧШЕНИЕ 3: BTC ФИЛЬТР ---------------- #

def get_btc_trend():
    try:
        closes, _, _, _ = get_klines("BTCUSDT", "1h")
        if not closes or len(closes) < 6:
            return "neutral"
        change = (closes[-1] - closes[-6]) / closes[-6] * 100
        if change <= -2:
            return "down"
        if change >= 1:
            return "up"
        return "neutral"
    except:
        return "neutral"

def check_btc_crash():
    try:
        closes, _, _, _ = get_klines("BTCUSDT", "15m")
        if not closes or len(closes) < 5:
            return False
        drop = (closes[-1] - closes[-5]) / closes[-5] * 100
        return drop <= -3
    except:
        return False

# ---------------- УЛУЧШЕНИЕ 5: ВРЕМЯ СУТОК ---------------- #

def is_active_hours():
    hour = datetime.now(timezone.utc).hour
    return 14 <= hour <= 22

# ---------------- УЛУЧШЕНИЕ 8: TRENDING МОНЕТЫ ---------------- #

def get_trending_symbols():
    try:
        data = requests.get(COINGECKO_TRENDING, timeout=10).json()
        return [coin["item"]["symbol"].upper() + "USDT" for coin in data.get("coins", [])]
    except:
        return []

# ---------------- ИНДИКАТОРЫ ---------------- #

def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calc_macd(closes):
    if len(closes) < 26:
        return False
    def ema(data, n):
        k = 2 / (n + 1)
        result = [data[0]]
        for price in data[1:]:
            result.append(price * k + result[-1] * (1 - k))
        return result
    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)
    macd = [ema12[i] - ema26[i] for i in range(len(ema26))]
    return macd[-2] < 0 and macd[-1] > 0

def whale_tracker(volumes):
    if len(volumes) < 2:
        return 0
    avg = sum(volumes[:-1]) / len(volumes[:-1])
    if avg == 0:
        return 0
    return volumes[-1] / avg

def hidden_accumulation(closes, volumes):
    if len(closes) < 10 or len(volumes) < 10:
        return False
    price_change = abs(closes[-1] - closes[0]) / closes[0] * 100
    first_vol = sum(volumes[:10]) / 10
    last_vol  = sum(volumes[-10:]) / 10
    if first_vol == 0:
        return False
    return price_change < 2 and last_vol > first_vol * 1.4

def pre_pump_detector(closes):
    if len(closes) < 4 or closes[-4] == 0:
        return False
    momentum = (closes[-1] - closes[-4]) / closes[-4] * 100
    return 0.5 < momentum < 4

def orderbook_pressure(symbol):
    try:
        data = requests.get(f"{BINANCE_DEPTH}?symbol={symbol}&limit=50", timeout=10).json()
        bids = sum(float(b[1]) for b in data.get("bids", []))
        asks = sum(float(a[1]) for a in data.get("asks", []))
        return bids / asks if asks > 0 else 0
    except:
        return 0

# УЛУЧШЕНИЕ 1: МНОГОТАЙМФРЕЙМНЫЙ АНАЛИЗ
def multi_timeframe_trend(symbol):
    score = 0
    for interval in ["15m", "1h", "4h"]:
        try:
            closes, _, _, _ = get_klines(symbol, interval, limit=20)
            if closes and len(closes) >= 5:
                trend = (closes[-1] - closes[0]) / closes[0] * 100
                if trend > 0:
                    score += 1
        except:
            pass
    return score  # 0-3

# SUPERTREND
def calc_supertrend(highs, lows, closes, period=10, multiplier=3.0):
    """Supertrend — популярный индикатор тренда с TradingView"""
    if len(closes) < period + 1:
        return "neutral"
    # ATR
    tr_list = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i] - closes[i-1])
        )
        tr_list.append(tr)
    if len(tr_list) < period:
        return "neutral"
    atr = sum(tr_list[-period:]) / period
    # Basic bands
    hl2 = [(highs[i] + lows[i]) / 2 for i in range(len(closes))]
    upper = hl2[-1] + multiplier * atr
    lower = hl2[-1] - multiplier * atr
    # Определяем направление
    if closes[-1] > lower:
        return "up"    # цена выше нижней полосы = восходящий тренд
    elif closes[-1] < upper:
        return "down"  # цена ниже верхней полосы = нисходящий тренд
    return "neutral"

# VWAP
def calc_vwap(closes, volumes):
    """VWAP — средневзвешенная цена по объёму"""
    if not closes or not volumes or len(closes) != len(volumes):
        return None
    total_pv = sum(closes[i] * volumes[i] for i in range(len(closes)))
    total_v  = sum(volumes)
    if total_v == 0:
        return None
    return total_pv / total_v

# SUPPORT / RESISTANCE
def calc_support_resistance(closes, highs, lows):
    """Автоматические уровни поддержки и сопротивления"""
    if len(closes) < 10:
        return None, None
    support    = min(lows[-10:])
    resistance = max(highs[-10:])
    return support, resistance

# ---------------- АНАЛИЗ ---------------- #

def analyze(symbol, trending_symbols):
    closes5,  vol5,  highs5,  lows5  = get_klines(symbol, "5m")
    closes15, vol15, highs15, lows15 = get_klines(symbol, "15m")

    if not closes5 or not vol5 or not closes15 or not highs15 or not lows15:
        return 0, {}

    whale        = whale_tracker(vol5)
    accumulation = hidden_accumulation(closes5, vol5)
    pre_pump     = pre_pump_detector(closes5)
    pressure     = orderbook_pressure(symbol)
    trend15      = (closes15[-1] - closes15[0]) / closes15[0] * 100
    rsi          = calc_rsi(closes15)
    macd_cross   = calc_macd(closes15)
    mtf_score    = multi_timeframe_trend(symbol)
    is_trending  = symbol in trending_symbols
    # Новые индикаторы TradingView уровня
    supertrend   = calc_supertrend(highs15, lows15, closes15)
    vwap         = calc_vwap(closes15, vol15)
    support, resistance = calc_support_resistance(closes15, highs15, lows15)
    price_now    = closes15[-1]
    above_vwap   = vwap is not None and price_now > vwap
    near_support = support is not None and abs(price_now - support) / price_now < 0.02

    # УЛУЧШЕНИЕ 2: малые монеты
    is_small_cap = False
    try:
        ticker = requests.get(f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}", timeout=5).json()
        vol_usd = float(ticker.get("quoteVolume", 0))
        is_small_cap = 1_000_000 < vol_usd < 20_000_000
    except:
        pass

    score = 0

    if whale > 2:        score += 25
    if whale > 3:        score += 15
    if accumulation:     score += 20
    if pre_pump:         score += 15
    if pressure > 1.3:   score += 15
    if trend15 > 0:      score += 5
    if rsi < 30:         score += 25
    elif rsi < 40:       score += 15
    elif rsi > 70:       score -= 20
    if macd_cross:       score += 20
    score += mtf_score * 10
    if is_small_cap:     score += 10
    if is_trending:      score += 15
    # Supertrend
    if supertrend == "up":    score += 25   # сильный сигнал тренда
    elif supertrend == "down": score -= 20  # против тренда — штраф
    # VWAP
    if above_vwap:       score += 15   # цена выше VWAP = бычий сигнал
    # Поддержка
    if near_support:     score += 15   # цена у поддержки = хорошая точка входа

    details = {
        "rsi":        round(rsi, 1),
        "macd":       macd_cross,
        "whale":      round(whale, 1),
        "pressure":   round(pressure, 2),
        "mtf":        mtf_score,
        "trending":   is_trending,
        "supertrend": supertrend,
        "vwap":       round(vwap, 6) if vwap else None,
        "above_vwap": above_vwap,
        "support":    round(support, 6) if support else None,
        "near_support": near_support,
    }
    return score, details

# ---------------- СИГНАЛ ---------------- #

def send_signal(symbol, price, score, details):
    if score >= 100:   strength = "🔥🔥🔥 ОЧЕНЬ СИЛЬНЫЙ"
    elif score >= 75:  strength = "🔥🔥 СИЛЬНЫЙ"
    else:              strength = "🔥 СРЕДНИЙ"

    rsi_text   = f"{details['rsi']} {'🟢 перепродана' if details['rsi'] < 40 else '🟡 норма'}"
    macd_text  = "✅ Да" if details["macd"] else "➖ Нет"
    whale_text = f"x{details['whale']} {'🐋' if details['whale'] > 3 else ''}"
    press_text = f"{details['pressure']} {'✅' if details['pressure'] > 1.3 else '➖'}"
    mtf_text   = f"{details['mtf']}/3 таймфреймов вверх"
    trend_text = "🔥 Trending!" if details["trending"] else "➖"
    st_emoji   = "🟢 Вверх" if details["supertrend"] == "up" else ("🔴 Вниз" if details["supertrend"] == "down" else "🟡 Нейтрально")
    vwap_text  = f"{details['vwap']} {'✅ Выше VWAP' if details['above_vwap'] else '⬇️ Ниже VWAP'}" if details["vwap"] else "➖"
    sup_text   = f"{details['support']} {'🎯 Цена у поддержки!' if details['near_support'] else ''}" if details["support"] else "➖"

    text = f"""
🚨 <b>СИГНАЛ ПОКУПКИ (СПОТ)</b>

Монета: <b>{symbol}</b>
Цена входа: <b>{price} USDT</b>
Стоп-лосс: <b>{round(price * 0.95, 8)} USDT (-5%)</b>
Цель: <b>{round(price * 1.12, 8)} USDT (+12%)</b>

📊 <b>Базовый анализ:</b>
• RSI: {rsi_text}
• MACD crossover: {macd_text}
• Объём кита: {whale_text}
• Давление стакана: {press_text}
• Тренд МТФ: {mtf_text}
• CoinGecko: {trend_text}

📈 <b>TradingView индикаторы:</b>
• Supertrend: {st_emoji}
• VWAP: {vwap_text}
• Поддержка: {sup_text}

AI Score: <b>{score}</b>
Сила сигнала: {strength}

⚠️ Только спотовая торговля!
"""
    buttons = [[
        {"text": "✅ Купил", "callback_data": f"buy_{symbol}"},
        {"text": "❌ Пропустить", "callback_data": f"skip_{symbol}"}
    ]]
    send_message(OWNER_ID, text, buttons)

# ---------------- СКАНЕР ---------------- #

def scanner():
    global scanner_running, active_signals, active_signals_time
    last_clear = time.time()
    last_btc_alert = 0

    while True:
        print("Scanner loop...")

        # УЛУЧШЕНИЕ 10: уведомление о резком падении BTC
        if check_btc_crash():
            now = time.time()
            if now - last_btc_alert > 3600:
                last_btc_alert = now
                send_message(OWNER_ID, "⚠️ <b>ВНИМАНИЕ!</b>\n\nBTC резко упал на 3%+!\nБудь осторожен с позициями!")

        if time.time() - last_clear > 7200:
            active_signals.clear()
            active_signals_time.clear()
            last_clear = time.time()
            print("Active signals очищены")

        if scanner_running:
            # УЛУЧШЕНИЕ 3: BTC тренд
            btc_trend = get_btc_trend()
            if btc_trend == "down":
                print("BTC падает — пропускаем скан")
                time.sleep(SCAN_INTERVAL)
                continue

            # УЛУЧШЕНИЕ 5: активные часы
            if not is_active_hours():
                print("Нет активных часов (14-22 UTC)")
                time.sleep(SCAN_INTERVAL)
                continue

            print(f"Сканирую... BTC: {btc_trend}")

            try:
                pairs    = get_top_pairs()
                trending = get_trending_symbols()
                print(f"Пар: {len(pairs)}, Trending: {len(trending)}")

                candidates = []
                for symbol in pairs:
                    if symbol in BLACKLIST:
                        continue
                    try:
                        score, details = analyze(symbol, trending)
                        if score > 60:
                            price = float(requests.get(
                                f"{BINANCE_PRICE}?symbol={symbol}", timeout=10
                            ).json()["price"])
                            candidates.append((symbol, price, score, details))
                    except Exception as e:
                        print(f"Ошибка {symbol}: {e}")
                        continue

                candidates.sort(key=lambda x: x[2], reverse=True)
                signals = candidates[:2]
                print(f"Кандидатов: {len(candidates)}, сигналов: {len(signals)}")

                for s in signals:
                    if s[0] not in active_signals:
                        active_signals.append(s[0])
                        active_signals_time[s[0]] = time.time()
                        send_signal(*s)

            except Exception as e:
                print(f"Ошибка сканера: {e}")

        time.sleep(SCAN_INTERVAL)

# ---------------- ТРЕКЕР ПРИБЫЛИ ---------------- #

def tracker():
    global win_count, loss_count

    while True:
        for symbol in list(tracked_coins.keys()):
            try:
                data   = tracked_coins[symbol]
                entry  = data["entry"]
                peak   = data.get("peak", entry)

                price  = float(requests.get(
                    f"{BINANCE_PRICE}?symbol={symbol}", timeout=10
                ).json()["price"])

                profit = (price - entry) / entry * 100

                # УЛУЧШЕНИЕ 7: обновляем пик и трейлинг стоп
                if price > peak:
                    tracked_coins[symbol]["peak"] = price
                    peak = price

                peak_profit = (peak - entry) / entry * 100
                if peak_profit >= 5:
                    dynamic_stop = peak * 0.97
                    if price <= dynamic_stop:
                        locked = (price - entry) / entry * 100
                        text = f"""
🔒 <b>ТРЕЙЛИНГ СТОП (СПОТ)</b>

Монета: <b>{symbol}</b>
Вход: {entry} USDT
Пик: {round(peak, 8)} USDT
Цена сейчас: <b>{price} USDT</b>

Зафиксировано: <b>+{round(locked, 2)}%</b> 💰
Рекомендую продать!
"""
                        buttons = [[{"text": "💰 Продал", "callback_data": f"sold_{symbol}"}]]
                        send_message(OWNER_ID, text, buttons)
                        time.sleep(300)
                        continue

                if profit >= 12:
                    text = f"""
💰 <b>СИГНАЛ ПРОДАЖИ (СПОТ)</b>

Монета: <b>{symbol}</b>
Цена входа: {entry} USDT
Цена сейчас: <b>{price} USDT</b>

Прибыль: <b>+{round(profit, 2)}%</b> 🎉
"""
                    buttons = [[{"text": "💰 Продал", "callback_data": f"sold_{symbol}"}]]
                    send_message(OWNER_ID, text, buttons)

                elif profit <= -5:
                    text = f"""
🛑 <b>СТОП-ЛОСС (СПОТ)</b>

Монета: <b>{symbol}</b>
Цена входа: {entry} USDT
Цена сейчас: <b>{price} USDT</b>

Убыток: <b>{round(profit, 2)}%</b>
Рекомендую продать сейчас!
"""
                    buttons = [[{"text": "🛑 Продал", "callback_data": f"sold_{symbol}"}]]
                    send_message(OWNER_ID, text, buttons)

            except Exception as e:
                print(f"Ошибка трекера {symbol}: {e}")

        time.sleep(60)

# ---------------- WEBHOOK ---------------- #

@app.route("/scanner", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        return "✅ Ultra Spot Scanner работает!"

    try:
        data = request.json
    except:
        return "ok"

    if not data:
        return "ok"
    global scanner_running, win_count, loss_count

    if "message" in data:
        msg  = data["message"]
        text = msg.get("text", "")
        chat = msg["chat"]["id"]



        if text == "/start":
            status   = "🟢 Включён" if scanner_running else "🔴 Выключен"
            active_h = is_active_hours()
            btc      = get_btc_trend()
            btc_emoji = "🟢" if btc == "up" else ("🔴" if btc == "down" else "🟡")
            send_message(chat, f"""🤖 <b>Ultra Binance Spot Scanner</b>

Сканер: {status}
Часы рынка: {"🟢 Активные" if active_h else "🟡 Тихие"}
BTC тренд: {btc_emoji} {btc}

Команды:
/scan — запустить сканирование
/stop — остановить
/status — статус и статистика
/active — мои позиции
/history — история сделок
/stats — винрейт
/blacklist SYMBOL — добавить в чёрный список
/ping — проверка""")

        elif text == "/scan":
            scanner_running = True
            send_message(chat, "🚀 Сканирование <b>включено!</b>\nИщу сигналы каждые 5 минут...\n\n⏰ Активные часы: 14:00-22:00 UTC")

        elif text == "/stop":
            scanner_running = False
            send_message(chat, "⛔ Сканирование <b>остановлено</b>")

        elif text == "/ping":
            send_message(chat, "🏓 Бот работает нормально!")

        elif text == "/status":
            status   = "🟢 Включён" if scanner_running else "🔴 Выключен"
            btc      = get_btc_trend()
            active_h = is_active_hours()
            total    = win_count + loss_count
            winrate  = round(win_count / total * 100) if total > 0 else 0
            send_message(chat, f"""📊 <b>Статус бота</b>

Сканер: {status}
BTC тренд: {btc}
Часы рынка: {"Активные ✅" if active_h else "Тихие ⏸"}
Позиций открыто: {len(tracked_coins)}
Сигналов в очереди: {len(active_signals)}
Сделок в истории: {len(trade_history)}
Винрейт: {winrate}% ({win_count}✅/{loss_count}❌)""")

        elif text == "/active":
            if tracked_coins:
                msg_text = "📈 <b>Активные позиции:</b>\n\n"
                for sym, d in tracked_coins.items():
                    try:
                        current = float(requests.get(
                            f"{BINANCE_PRICE}?symbol={sym}", timeout=5
                        ).json()["price"])
                        pnl   = (current - d["entry"]) / d["entry"] * 100
                        peak  = d.get("peak", d["entry"])
                        pk_pnl = (peak - d["entry"]) / d["entry"] * 100
                        emoji = "📈" if pnl > 0 else "📉"
                        msg_text += f"{emoji} <b>{sym}</b>: {round(pnl,2)}% (пик: +{round(pk_pnl,2)}%)\n"
                    except:
                        msg_text += f"❓ {sym}: ошибка\n"
                send_message(chat, msg_text)
            else:
                send_message(chat, "📭 Нет активных позиций")

        elif text == "/history":
            if trade_history:
                msg_text = "📜 <b>История последних сделок:</b>\n\n"
                for trade in trade_history[-10:]:
                    emoji = "✅" if trade["profit"] > 0 else "❌"
                    msg_text += f"{emoji} {trade['symbol']}: {trade['profit']}%\n"
                total_pnl = sum(t["profit"] for t in trade_history)
                msg_text += f"\n💰 Суммарно: {round(total_pnl, 2)}%"
                send_message(chat, msg_text)
            else:
                send_message(chat, "📭 История пуста")

        # УЛУЧШЕНИЕ 9: статистика
        elif text == "/stats":
            total      = win_count + loss_count
            winrate    = round(win_count / total * 100) if total > 0 else 0
            avg_profit = round(sum(t["profit"] for t in trade_history) / len(trade_history), 2) if trade_history else 0
            best       = max((t["profit"] for t in trade_history), default=0)
            worst      = min((t["profit"] for t in trade_history), default=0)
            send_message(chat, f"""📊 <b>Статистика торговли</b>

Всего сделок: {total}
Прибыльных: {win_count} ✅
Убыточных: {loss_count} ❌
Винрейт: <b>{winrate}%</b>

Средняя сделка: {avg_profit}%
Лучшая сделка: +{best}% 🏆
Худшая сделка: {worst}%""")

        # УЛУЧШЕНИЕ 6: blacklist
        elif text and text.startswith("/blacklist "):
            parts = text.split(" ")
            if len(parts) > 1:
                symbol = parts[1].upper()
                if not symbol.endswith("USDT"):
                    symbol += "USDT"
                BLACKLIST.add(symbol)
                send_message(chat, f"🚫 {symbol} добавлен в чёрный список\nВсего в блоке: {len(BLACKLIST)}")

    if "callback_query" in data:


        q           = data["callback_query"]["data"]
        callback_id = data["callback_query"]["id"]

        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/answerCallbackQuery",
            json={"callback_query_id": callback_id},
            timeout=5
        )

        if q.startswith("buy_"):
            symbol = q.split("_")[1]
            try:
                price = float(requests.get(
                    f"{BINANCE_PRICE}?symbol={symbol}", timeout=10
                ).json()["price"])
                tracked_coins[symbol] = {"entry": price, "peak": price}
                scanner_running = False
                active_signals.clear()
                send_message(OWNER_ID, f"""✅ <b>Позиция открыта!</b>

Монета: <b>{symbol}</b>
Цена входа: <b>{price} USDT</b>
Стоп-лосс: <b>{round(price * 0.95, 8)} USDT (-5%)</b>
Цель: <b>{round(price * 1.12, 8)} USDT (+12%)</b>

⏸ Сканирование остановлено.
Слежу только за {symbol}...
Пришлю сигнал когда продавать! 👀""")
            except Exception as e:
                send_message(OWNER_ID, f"❌ Ошибка: {e}")

        elif q.startswith("skip_"):
            symbol = q.split("_")[1]
            if symbol in active_signals:
                active_signals.remove(symbol)
            send_message(OWNER_ID, f"⏭ {symbol} пропущен\n🔍 Продолжаю поиск...")

        elif q.startswith("sold_"):
            symbol = q.split("_")[1]
            if symbol in tracked_coins:
                entry = tracked_coins[symbol]["entry"]
                try:
                    price  = float(requests.get(
                        f"{BINANCE_PRICE}?symbol={symbol}", timeout=10
                    ).json()["price"])
                    profit = (price - entry) / entry * 100
                    trade_history.append({
                        "symbol": symbol,
                        "entry":  entry,
                        "exit":   price,
                        "profit": round(profit, 2)
                    })
                    if profit > 0:
                        win_count += 1
                    else:
                        loss_count += 1

                    del tracked_coins[symbol]
                    if symbol in active_signals:
                        active_signals.remove(symbol)

                    emoji = "✅" if profit > 0 else "❌"
                    scanner_running = True
                    total   = win_count + loss_count
                    winrate = round(win_count / total * 100) if total > 0 else 0

                    send_message(OWNER_ID, f"""{emoji} <b>Сделка закрыта!</b>

Монета: {symbol}
Вход: {entry} USDT
Выход: {price} USDT
Результат: <b>{round(profit, 2)}%</b>

📊 Винрейт: {winrate}% ({win_count}✅/{loss_count}❌)

🔍 Сканирование возобновлено!
Ищу следующую монету...""")
                except Exception as e:
                    send_message(OWNER_ID, f"❌ Ошибка закрытия: {e}")

    return "ok"

# ---------------- ПОТОКИ ---------------- #

def run():
    threading.Thread(target=scanner, daemon=True).start()
    threading.Thread(target=tracker, daemon=True).start()

# ---------------- ЗАПУСК ---------------- #

def delayed_start():
    """Запускаем webhook и сканер после старта Flask"""
    time.sleep(3)
    set_webhook()
    run()

if __name__ == "__main__":
    print("🚀 Запуск Ultra Spot Scanner v2.0...")
    PORT = int(os.environ.get("PORT", 10000))
    threading.Thread(target=delayed_start, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT)
