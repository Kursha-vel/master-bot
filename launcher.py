"""
MASTER LAUNCHER v3 — запускает все 6 ботов в одном Render сервисе
"""

import threading
import asyncio
import os
import time
from flask import Flask

health_app = Flask(__name__)

bot_status = {
    "football-bot": False,
    "scalper-bot":  False,
    "scanner-bot":  False,
    "neuro-bot":    False,
    "meta-bot":     False,
    "tiktok-bot":   False,
}

# Защита от двойного запуска
_started = set()
_started_lock = threading.Lock()

def already_started(name):
    with _started_lock:
        if name in _started:
            print(f"[{name}] ⚠️ Уже запущен — пропускаю!")
            return True
        _started.add(name)
        return False

@health_app.route("/")
def health():
    rows = [f"<tr><td>{'✅' if v else '❌'}</td><td>{k}</td></tr>"
            for k, v in bot_status.items()]
    return f"<h2>🤖 Master Bot</h2><table>{''.join(rows)}</table>"

@health_app.route("/meta", methods=["GET", "POST"])
def meta_webhook():
    try:
        import meta_main as mm
        return mm.webhook()
    except Exception as e:
        print(f"[meta] webhook error: {e}")
        return "ok"

@health_app.route("/tiktok", methods=["GET", "POST"])
def tiktok_webhook():
    try:
        import tiktok_main as tm
        return tm.webhook()
    except Exception as e:
        print(f"[tiktok] webhook error: {e}")
        return "ok"

# ──────────────────────────────────────────────
# PTB БОТ — правильный запуск через asyncio.run
# ──────────────────────────────────────────────

async def run_ptb_async(token, setup_func):
    import httpx
    # Удаляем webhook перед polling чтобы не было конфликта
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{token}/deleteWebhook",
                json={"drop_pending_updates": True},
                timeout=10
            )
            print(f"[ptb] deleteWebhook OK")
    except Exception as e:
        print(f"[ptb] deleteWebhook error: {e}")

    await asyncio.sleep(2)

    from telegram.ext import Application
    app = Application.builder().token(token).build()
    setup_func(app)
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    # Держим бота живым
    while True:
        await asyncio.sleep(3600)

def ptb_thread(name, token_env, setup_func):
    if already_started(name):
        return
    def run():
        # Ждём чтобы не конфликтовать с другими ботами при старте
        time.sleep(1)
        while True:
            try:
                token = os.environ.get(token_env, "")
                if not token:
                    print(f"[{name}] ❌ {token_env} не задан! Жду 60 сек...")
                    time.sleep(60)
                    continue
                print(f"[{name}] ▶ Запускаю...")
                bot_status[name] = True
                asyncio.run(run_ptb_async(token, setup_func))
            except Exception as e:
                bot_status[name] = False
                print(f"[{name}] ❌ Упал: {e}")
                # Долгая пауза перед рестартом чтобы не спамить
                print(f"[{name}] ⏳ Рестарт через 60 сек...")
                time.sleep(60)
    t = threading.Thread(target=run, daemon=True, name=name)
    t.daemon = True
    t.start()

# ──────────────────────────────────────────────
# ОБЫЧНЫЙ ПОТОК с авто-рестартом
# ──────────────────────────────────────────────

def simple_thread(name, func):
    if already_started(name):
        return
    def run():
        while True:
            try:
                print(f"[{name}] ▶ Запускаю...")
                bot_status[name] = True
                func()
            except Exception as e:
                bot_status[name] = False
                print(f"[{name}] ❌ Упал: {e}")
                print(f"[{name}] ⏳ Рестарт через 60 сек...")
                time.sleep(60)
    t = threading.Thread(target=run, daemon=True, name=name)
    t.start()

# ══════════════════════════════════════════════
# БОТ 1: FOOTBALL ANALYZER
# ══════════════════════════════════════════════

def setup_football(app):
    from telegram.ext import CommandHandler, CallbackQueryHandler
    import football_main as fb
    bot = fb.FootballBot()
    app.bot_data['bot'] = bot
    app.add_handler(CommandHandler("start", bot.start))
    app.add_handler(CommandHandler("users", fb.admin_users))
    app.add_handler(CommandHandler("revoke", fb.admin_revoke))
    app.add_handler(CallbackQueryHandler(fb.handler))
    print("[football-bot] ✅ Хендлеры добавлены")

# ══════════════════════════════════════════════
# БОТ 4: NEURO ACADEMY
# ══════════════════════════════════════════════

def setup_neuro(app):
    import neuro_main as nm
    # Пробуем разные варианты подключения хендлеров
    if hasattr(nm, 'setup_handlers'):
        nm.setup_handlers(app)
    elif hasattr(nm, 'build_app'):
        # Если build_app принимает готовый app
        try:
            nm.build_app(app)
        except Exception:
            # Если build_app создаёт новый app — копируем хендлеры
            token = os.environ.get("NEURO_TOKEN", "")
            tmp = nm.build_app(token)
            for handler in tmp.handlers.get(0, []):
                app.add_handler(handler)
    print("[neuro-bot] ✅ Хендлеры добавлены")

# ══════════════════════════════════════════════
# БОТ 2: CRYPTO SCALPER
# ══════════════════════════════════════════════

def start_scalper():
    import scalper_main as sc
    sc.polling_loop()

# ══════════════════════════════════════════════
# БОТ 3: CRYPTO SCANNER
# ══════════════════════════════════════════════

def start_scanner():
    import scanner_main as sm
    print("[scanner-bot] ✅ Запускаю polling loop...")
    while True:
        try:
            sm._polling_running = False  # сбрасываем флаг перед каждым запуском
            sm.polling_loop()
        except Exception as e:
            sm._polling_running = False
            print(f"[scanner-bot] ❌ Упал: {e}")
            print("[scanner-bot] ⏳ Рестарт через 60 сек...")
            time.sleep(60)

# ══════════════════════════════════════════════
# БОТ 5: META BOT
# ══════════════════════════════════════════════

def start_meta():
    import meta_main as mm
    print("[meta-bot] ✅ Загружен (webhook: /meta)")
    while True:
        time.sleep(3600)

# ══════════════════════════════════════════════
# БОТ 6: TIKTOK GENERATOR
# ══════════════════════════════════════════════

def start_tiktok():
    import tiktok_main as tm
    print("[tiktok-bot] ✅ Загружен (webhook: /tiktok)")
    tm.set_webhook()
    while True:
        time.sleep(3600)

# ══════════════════════════════════════════════
# ЗАПУСК ВСЕХ БОТОВ
# ══════════════════════════════════════════════

def start_all_bots():
    print("=" * 55)
    print("🚀 MASTER LAUNCHER v3 — Запускаю все боты...")
    print("=" * 55)

    # PTB боты — запускаем напрямую через ptb_thread (у них свой рестарт)
    ptb_thread("football-bot", "FOOTBALL_TOKEN", setup_football)
    time.sleep(5)  # больше паузы чтобы не конфликтовали

    ptb_thread("neuro-bot", "NEURO_TOKEN", setup_neuro)
    time.sleep(5)

    # Polling боты
    simple_thread("scalper-bot", start_scalper)
    time.sleep(3)

    simple_thread("scanner-bot", start_scanner)
    time.sleep(3)

    # Фоновые боты (держат потоки живыми)
    simple_thread("meta-bot", start_meta)
    time.sleep(2)

    simple_thread("tiktok-bot", start_tiktok)
    time.sleep(2)

    print("=" * 55)
    print("✅ Все боты запущены!")
    print("=" * 55)

# ══════════════════════════════════════════════
# ГЛАВНЫЙ ЗАПУСК
# ══════════════════════════════════════════════

if __name__ == "__main__":
    PORT = int(os.environ.get("PORT", 10000))
    threading.Thread(target=start_all_bots, daemon=True).start()
    print(f"[health] 🌐 Сервер на порту {PORT}...")
    health_app.run(host="0.0.0.0", port=PORT)
