"""
MASTER LAUNCHER — запускает все 6 ботов в одном Render сервисе
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Боты:
1. football-telegram-bot  — анализ футбола (PTB polling)
2. crypto-scalper-bot     — фьючерсные сигналы (polling loop)
3. crypto-scanner-bot     — спотовый трейдинг (Flask webhook)
4. neuro-academy-bot      — курс по нейросетям (PTB polling)
5. meta-bot               — создаёт других ботов (Flask webhook)
6. tiktok-bot             — TikTok контент генератор (Flask webhook)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import threading
import asyncio
import os
import time
import sys
from flask import Flask

# ──────────────────────────────────────────────
# HEALTH SERVER (Render требует открытый порт)
# ──────────────────────────────────────────────
health_app = Flask(__name__)

@health_app.route("/")
def health():
    status = []
    for name, running in bot_status.items():
        icon = "✅" if running else "❌"
        status.append(f"{icon} {name}")
    return "<br>".join(["<h2>🤖 Master Bot Launcher</h2>"] + status)

@health_app.route("/tiktok", methods=["GET", "POST"])
def tiktok_webhook():
    import tiktok_main as tm
    return tm.webhook()

@health_app.route("/scanner", methods=["GET", "POST"])
def scanner_webhook():
    import scanner_main as sm
    return sm.webhook()

@health_app.route("/meta", methods=["GET", "POST"])
def meta_webhook():
    import meta_main as mm
    return mm.webhook()

bot_status = {
    "football-bot": False,
    "scalper-bot":  False,
    "scanner-bot":  False,
    "neuro-bot":    False,
    "meta-bot":     False,
    "tiktok-bot":   False,
}

# ──────────────────────────────────────────────
# УТИЛИТЫ
# ──────────────────────────────────────────────

def run_thread(name, func):
    """Запускает функцию в отдельном потоке с авто-рестартом"""
    def wrapper():
        while True:
            try:
                print(f"[{name}] ▶ Запускаю...")
                bot_status[name] = True
                func()
            except Exception as e:
                bot_status[name] = False
                print(f"[{name}] ❌ Упал: {e}")
                print(f"[{name}] ⏳ Рестарт через 30 сек...")
                time.sleep(30)
    t = threading.Thread(target=wrapper, daemon=True, name=name)
    t.start()
    return t

def run_ptb_thread(name, build_func):
    """Запускает PTB бота в отдельном потоке с собственным event loop"""
    def wrapper():
        while True:
            try:
                print(f"[{name}] ▶ Запускаю PTB бота...")
                bot_status[name] = True
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                ptb_app = build_func()
                ptb_app.run_polling(drop_pending_updates=True)
            except Exception as e:
                bot_status[name] = False
                print(f"[{name}] ❌ Упал: {e}")
                print(f"[{name}] ⏳ Рестарт через 30 сек...")
                time.sleep(30)
    t = threading.Thread(target=wrapper, daemon=True, name=name)
    t.start()
    return t

# ══════════════════════════════════════════════
# БОТ 1: FOOTBALL ANALYZER
# ══════════════════════════════════════════════

def build_football_bot():
    from telegram.ext import Application, CommandHandler, CallbackQueryHandler
    import football_main as fb

    token = os.environ.get("FOOTBALL_TOKEN", "")
    if not token:
        raise ValueError("FOOTBALL_TOKEN не задан!")

    app = Application.builder().token(token).build()
    bot = fb.FootballBot()
    app.bot_data['bot'] = bot
    app.add_handler(CommandHandler("start", bot.start))
    app.add_handler(CommandHandler("users", fb.admin_users))
    app.add_handler(CommandHandler("revoke", fb.admin_revoke))
    app.add_handler(CallbackQueryHandler(fb.handler))
    print("[football-bot] ✅ Построен")
    return app

# ══════════════════════════════════════════════
# БОТ 2: CRYPTO SCALPER
# ══════════════════════════════════════════════

def start_scalper_bot():
    import scalper_main as sc
    print("[scalper-bot] ✅ Запускаю polling loop...")
    sc.polling_loop()

# ══════════════════════════════════════════════
# БОТ 3: CRYPTO SCANNER (Flask webhook)
# ══════════════════════════════════════════════

def start_scanner_bot():
    import scanner_main as sm
    print("[scanner-bot] ✅ Scanner бот загружен (webhook через главный порт)")
    # Держим поток живым
    while True:
        time.sleep(3600)

# ══════════════════════════════════════════════
# БОТ 4: NEURO ACADEMY
# ══════════════════════════════════════════════

def build_neuro_bot():
    import neuro_main as nm
    token = os.environ.get("NEURO_TOKEN", "")
    if not token:
        raise ValueError("NEURO_TOKEN не задан!")
    app = nm.build_app(token)
    print("[neuro-bot] ✅ Построен")
    return app

# ══════════════════════════════════════════════
# БОТ 5: META BOT (Flask webhook)
# ══════════════════════════════════════════════

def start_meta_bot():
    import meta_main as mm
    print("[meta-bot] ✅ Meta бот загружен (webhook через главный порт)")
    while True:
        time.sleep(3600)

# ══════════════════════════════════════════════
# БОТ 6: TIKTOK GENERATOR (Flask webhook)
# ══════════════════════════════════════════════

def start_tiktok_bot():
    import tiktok_main as tm
    print("[tiktok-bot] ✅ TikTok бот загружен (webhook через главный порт)")
    # Регистрируем webhook
    tm.set_webhook()
    while True:
        time.sleep(3600)

# ══════════════════════════════════════════════
# ЗАПУСК ВСЕХ БОТОВ
# ══════════════════════════════════════════════

def start_all_bots():
    """Запускает все 6 ботов в отдельных потоках"""
    print("=" * 60)
    print("🚀 MASTER LAUNCHER — Запускаю все боты...")
    print("=" * 60)

    bots_started = 0

    # Бот 1: Football (PTB polling)
    try:
        run_ptb_thread("football-bot", build_football_bot)
        bots_started += 1
        print("[1/6] ✅ Football Bot — запущен")
    except Exception as e:
        print(f"[1/6] ❌ Football Bot — ошибка: {e}")

    time.sleep(2)

    # Бот 2: Scalper (polling loop)
    try:
        run_thread("scalper-bot", start_scalper_bot)
        bots_started += 1
        print("[2/6] ✅ Crypto Scalper — запущен")
    except Exception as e:
        print(f"[2/6] ❌ Crypto Scalper — ошибка: {e}")

    time.sleep(2)

    # Бот 3: Scanner (Flask)
    try:
        run_thread("scanner-bot", start_scanner_bot)
        bots_started += 1
        print("[3/6] ✅ Crypto Scanner — запущен")
    except Exception as e:
        print(f"[3/6] ❌ Crypto Scanner — ошибка: {e}")

    time.sleep(2)

    # Бот 4: Neuro Academy (PTB polling)
    try:
        run_ptb_thread("neuro-bot", build_neuro_bot)
        bots_started += 1
        print("[4/6] ✅ Neuro Academy — запущен")
    except Exception as e:
        print(f"[4/6] ❌ Neuro Academy — ошибка: {e}")

    time.sleep(2)

    # Бот 5: Meta Bot (Flask)
    try:
        run_thread("meta-bot", start_meta_bot)
        bots_started += 1
        print("[5/6] ✅ Meta Bot — запущен")
    except Exception as e:
        print(f"[5/6] ❌ Meta Bot — ошибка: {e}")

    time.sleep(2)

    # Бот 6: TikTok Generator (Flask)
    try:
        run_thread("tiktok-bot", start_tiktok_bot)
        bots_started += 1
        print("[6/6] ✅ TikTok Bot — запущен")
    except Exception as e:
        print(f"[6/6] ❌ TikTok Bot — ошибка: {e}")

    print("=" * 60)
    print(f"✅ Запущено ботов: {bots_started}/6")
    print("=" * 60)

# ══════════════════════════════════════════════
# ГЛАВНЫЙ ЗАПУСК
# ══════════════════════════════════════════════

if __name__ == "__main__":
    PORT = int(os.environ.get("PORT", 10000))

    # Запускаем всех ботов в фоне
    threading.Thread(target=start_all_bots, daemon=True).start()

    # Health server на главном порту (Render требует!)
    print(f"[health] 🌐 Запускаю health server на порту {PORT}...")
    health_app.run(host="0.0.0.0", port=PORT)
