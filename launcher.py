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
from flask import Flask, request

# ──────────────────────────────────────────────
# HEALTH SERVER + WEBHOOK РОУТЕР
# ──────────────────────────────────────────────
health_app = Flask(__name__)

bot_status = {
    "football-bot": False,
    "scalper-bot":  False,
    "scanner-bot":  False,
    "neuro-bot":    False,
    "meta-bot":     False,
    "tiktok-bot":   False,
}

@health_app.route("/")
def health():
    status = []
    for name, running in bot_status.items():
        icon = "✅" if running else "❌"
        status.append(f"{icon} {name}")
    return "<br>".join(["<h2>🤖 Master Bot Launcher</h2>"] + status)

@health_app.route("/scanner", methods=["GET", "POST"])
def scanner_webhook():
    try:
        import scanner_main as sm
        return sm.webhook()
    except Exception as e:
        print(f"[scanner webhook] ошибка: {e}")
        return "ok"

@health_app.route("/meta", methods=["GET", "POST"])
def meta_webhook():
    try:
        import meta_main as mm
        return mm.webhook()
    except Exception as e:
        print(f"[meta webhook] ошибка: {e}")
        return "ok"

@health_app.route("/tiktok", methods=["GET", "POST"])
def tiktok_webhook():
    try:
        import tiktok_main as tm
        return tm.webhook()
    except Exception as e:
        print(f"[tiktok webhook] ошибка: {e}")
        return "ok"

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

def run_ptb_bot(name, token_env, build_handlers_func):
    """
    Правильный запуск PTB v20 бота в отдельном потоке.
    Каждый бот получает свой event loop.
    """
    def wrapper():
        while True:
            try:
                print(f"[{name}] ▶ Запускаю PTB бота...")
                bot_status[name] = True

                token = os.environ.get(token_env, "")
                if not token:
                    raise ValueError(f"{token_env} не задан!")

                # Создаём новый event loop для этого потока
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                from telegram.ext import Application
                ptb_app = Application.builder().token(token).build()

                # Добавляем хендлеры через переданную функцию
                build_handlers_func(ptb_app)

                print(f"[{name}] ✅ Построен, запускаю polling...")
                ptb_app.run_polling(
                    drop_pending_updates=True,
                    close_loop=False
                )

            except Exception as e:
                bot_status[name] = False
                print(f"[{name}] ❌ Упал: {e}")
                print(f"[{name}] ⏳ Рестарт через 30 сек...")
                time.sleep(30)

    t = threading.Thread(target=wrapper, daemon=True, name=name)
    t.start()
    return t

# ══════════════════════════════════════════════
# БОТ 1: FOOTBALL ANALYZER (PTB polling)
# ══════════════════════════════════════════════

def setup_football_handlers(ptb_app):
    from telegram.ext import CommandHandler, CallbackQueryHandler
    import football_main as fb

    bot = fb.FootballBot()
    ptb_app.bot_data['bot'] = bot
    ptb_app.add_handler(CommandHandler("start", bot.start))
    ptb_app.add_handler(CommandHandler("users", fb.admin_users))
    ptb_app.add_handler(CommandHandler("revoke", fb.admin_revoke))
    ptb_app.add_handler(CallbackQueryHandler(fb.handler))
    print("[football-bot] ✅ Хендлеры добавлены")

def start_football_bot():
    run_ptb_bot("football-bot", "FOOTBALL_TOKEN", setup_football_handlers)

# ══════════════════════════════════════════════
# БОТ 2: CRYPTO SCALPER (polling loop)
# ══════════════════════════════════════════════

def start_scalper_bot():
    try:
        import scalper_main as sc
        bot_status["scalper-bot"] = True
        print("[scalper-bot] ✅ Запускаю polling loop...")
        sc.polling_loop()
    except Exception as e:
        bot_status["scalper-bot"] = False
        print(f"[scalper-bot] ❌ {e}")
        raise

# ══════════════════════════════════════════════
# БОТ 3: CRYPTO SCANNER (Flask webhook)
# ══════════════════════════════════════════════

def start_scanner_bot():
    try:
        import scanner_main as sm
        bot_status["scanner-bot"] = True
        print("[scanner-bot] ✅ Scanner загружен (webhook: /scanner)")
        # Регистрируем webhook
        sm.set_webhook()
        # Держим поток живым
        while True:
            time.sleep(3600)
    except Exception as e:
        bot_status["scanner-bot"] = False
        print(f"[scanner-bot] ❌ {e}")
        raise

# ══════════════════════════════════════════════
# БОТ 4: NEURO ACADEMY (PTB polling)
# ══════════════════════════════════════════════

def setup_neuro_handlers(ptb_app):
    import neuro_main as nm
    nm.setup_handlers(ptb_app)
    print("[neuro-bot] ✅ Хендлеры добавлены")

def start_neuro_bot():
    run_ptb_bot("neuro-bot", "NEURO_TOKEN", setup_neuro_handlers)

# ══════════════════════════════════════════════
# БОТ 5: META BOT (Flask webhook)
# ══════════════════════════════════════════════

def start_meta_bot():
    try:
        import meta_main as mm
        bot_status["meta-bot"] = True
        print("[meta-bot] ✅ Meta загружен (webhook: /meta)")
        # Держим поток живым
        while True:
            time.sleep(3600)
    except Exception as e:
        bot_status["meta-bot"] = False
        print(f"[meta-bot] ❌ {e}")
        raise

# ══════════════════════════════════════════════
# БОТ 6: TIKTOK GENERATOR (Flask webhook)
# ══════════════════════════════════════════════

def start_tiktok_bot():
    try:
        import tiktok_main as tm
        bot_status["tiktok-bot"] = True
        print("[tiktok-bot] ✅ TikTok загружен (webhook: /tiktok)")
        # Регистрируем webhook
        tm.set_webhook()
        # Держим поток живым
        while True:
            time.sleep(3600)
    except Exception as e:
        bot_status["tiktok-bot"] = False
        print(f"[tiktok-bot] ❌ {e}")
        raise

# ══════════════════════════════════════════════
# ЗАПУСК ВСЕХ БОТОВ
# ══════════════════════════════════════════════

def start_all_bots():
    """Запускает все 6 ботов в отдельных потоках"""
    print("=" * 60)
    print("🚀 MASTER LAUNCHER — Запускаю все боты...")
    print("=" * 60)

    bots = [
        ("football-bot", start_football_bot),
        ("scalper-bot",  start_scalper_bot),
        ("scanner-bot",  start_scanner_bot),
        ("neuro-bot",    start_neuro_bot),
        ("meta-bot",     start_meta_bot),
        ("tiktok-bot",   start_tiktok_bot),
    ]

    for i, (name, func) in enumerate(bots, 1):
        try:
            run_thread(name, func)
            print(f"[{i}/6] ✅ {name} — запущен")
        except Exception as e:
            print(f"[{i}/6] ❌ {name} — ошибка: {e}")
        time.sleep(2)  # пауза между запусками

    print("=" * 60)
    print("✅ Все боты запущены!")
    print("=" * 60)

# ══════════════════════════════════════════════
# ГЛАВНЫЙ ЗАПУСК
# ══════════════════════════════════════════════

if __name__ == "__main__":
    PORT = int(os.environ.get("PORT", 10000))

    # Запускаем всех ботов в фоне
    threading.Thread(target=start_all_bots, daemon=True).start()

    # Health server + webhook роутер на главном порту
    print(f"[health] 🌐 Запускаю сервер на порту {PORT}...")
    health_app.run(host="0.0.0.0", port=PORT)
