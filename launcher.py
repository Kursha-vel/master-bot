"""
MASTER LAUNCHER v4 — 6 ботов в одном Render сервисе
Каждый бот запускается СТРОГО ОДИН РАЗ
"""

import threading
import asyncio
import os
import time
from flask import Flask

# ──────────────────────────────────────────────
# FLASK — health check
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
    rows = [f"<tr><td>{'✅' if v else '❌'}</td><td>{k}</td></tr>"
            for k, v in bot_status.items()]
    return f"<h2>🤖 Master Bot v4</h2><table>{''.join(rows)}</table>"

@health_app.route("/meta", methods=["GET", "POST"])
def meta_webhook():
    try:
        import meta_main as mm
        return mm.webhook()
    except Exception as e:
        return "ok"

@health_app.route("/tiktok", methods=["GET", "POST"])
def tiktok_webhook():
    try:
        import tiktok_main as tm
        return tm.webhook()
    except Exception as e:
        return "ok"

# ──────────────────────────────────────────────
# ЗАПУСК БОТОВ — каждый строго один раз
# ──────────────────────────────────────────────

def run_once(name, func):
    """Запускает бота один раз. При падении ждёт и перезапускает."""
    def wrapper():
        while True:
            try:
                print(f"[{name}] ▶ Запускаю...")
                bot_status[name] = True
                func()
                print(f"[{name}] Завершился штатно")
            except Exception as e:
                bot_status[name] = False
                print(f"[{name}] ❌ Ошибка: {e}")
            print(f"[{name}] ⏳ Рестарт через 90 сек (ждём закрытия Telegram соединений)...")
            time.sleep(90)
    t = threading.Thread(target=wrapper, daemon=True, name=name)
    t.start()
    return t

# ══════════════════════════════════════════════
# БОТ 1: FOOTBALL (PTB)
# ══════════════════════════════════════════════

def run_football():
    token = os.environ.get("FOOTBALL_TOKEN", "")
    if not token:
        print("[football-bot] ❌ FOOTBALL_TOKEN не задан!")
        return

    # Удаляем webhook
    import requests as req
    try:
        req.post(f"https://api.telegram.org/bot{token}/deleteWebhook",
                 json={"drop_pending_updates": True}, timeout=10)
        print("[football-bot] webhook удалён")
    except: pass
    time.sleep(2)

    async def main():
        from telegram.ext import Application, CommandHandler, CallbackQueryHandler
        import football_main as fb

        app = Application.builder().token(token).build()
        bot = fb.FootballBot()
        app.bot_data['bot'] = bot
        app.add_handler(CommandHandler("start", bot.start))
        app.add_handler(CommandHandler("users", fb.admin_users))
        app.add_handler(CommandHandler("revoke", fb.admin_revoke))
        app.add_handler(CallbackQueryHandler(fb.handler))

        print("[football-bot] ✅ Запускаю polling...")
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        while True:
            await asyncio.sleep(3600)

    asyncio.run(main())

# ══════════════════════════════════════════════
# БОТ 2: SCALPER (polling)
# ══════════════════════════════════════════════

def run_scalper():
    import requests as req
    import scalper_main as sc

    token = os.environ.get("SCALPER_TOKEN", "")
    if token:
        try:
            req.post(f"https://api.telegram.org/bot{token}/deleteWebhook",
                     json={"drop_pending_updates": True}, timeout=10)
            print("[scalper-bot] webhook удалён — жду 40 сек...")
        except Exception as e:
            print(f"[scalper-bot] deleteWebhook: {e}")
        time.sleep(40)

    print("[scalper-bot] ✅ Запускаю polling...")
    sc.polling_loop()

# ══════════════════════════════════════════════
# БОТ 3: SCANNER (polling)
# ══════════════════════════════════════════════

def run_scanner():
    import requests as req
    import scanner_main as sm

    token = os.environ.get("TELEGRAM_TOKEN", "")
    if not token:
        print("[scanner-bot] ❌ TELEGRAM_TOKEN не задан!")
        return

    # Принудительно удаляем webhook и ждём закрытия старых соединений
    try:
        req.post(f"https://api.telegram.org/bot{token}/deleteWebhook",
                 json={"drop_pending_updates": True}, timeout=10)
        print("[scanner-bot] webhook удалён — жду 40 сек закрытия соединений...")
    except Exception as e:
        print(f"[scanner-bot] deleteWebhook: {e}")

    time.sleep(40)  # Telegram держит соединение 30 сек — ждём дольше!

    sm._polling_running = False
    print("[scanner-bot] ✅ Запускаю polling...")
    sm.polling_loop()

# ══════════════════════════════════════════════
# БОТ 4: NEURO ACADEMY (PTB)
# ══════════════════════════════════════════════

def run_neuro():
    token = os.environ.get("NEURO_TOKEN", "")
    if not token:
        print("[neuro-bot] ❌ NEURO_TOKEN не задан!")
        return

    import requests as req
    try:
        req.post(f"https://api.telegram.org/bot{token}/deleteWebhook",
                 json={"drop_pending_updates": True}, timeout=10)
        print("[neuro-bot] webhook удалён")
    except: pass
    time.sleep(2)

    async def main():
        from telegram.ext import Application
        import neuro_main as nm

        app = Application.builder().token(token).build()

        # Пробуем разные способы подключить хендлеры
        if hasattr(nm, 'setup_handlers'):
            nm.setup_handlers(app)
            print("[neuro-bot] ✅ setup_handlers OK")
        elif hasattr(nm, 'register_handlers'):
            nm.register_handlers(app)
            print("[neuro-bot] ✅ register_handlers OK")
        elif hasattr(nm, 'build_app'):
            # build_app создаёт своё приложение — копируем хендлеры
            try:
                tmp = nm.build_app(token)
                for group, handlers in tmp.handlers.items():
                    for h in handlers:
                        app.add_handler(h, group)
                print("[neuro-bot] ✅ build_app handlers скопированы")
            except Exception as e:
                print(f"[neuro-bot] ⚠️ build_app error: {e}")
        else:
            print("[neuro-bot] ⚠️ Не нашёл функцию хендлеров!")
            # Показываем что есть в модуле
            attrs = [a for a in dir(nm) if not a.startswith('_')]
            print(f"[neuro-bot] Доступные функции: {attrs[:20]}")

        print("[neuro-bot] ✅ Запускаю polling...")
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        while True:
            await asyncio.sleep(3600)

    asyncio.run(main())

# ══════════════════════════════════════════════
# БОТ 5: META (Flask webhook)
# ══════════════════════════════════════════════

def run_meta():
    import meta_main as mm
    print("[meta-bot] ✅ Загружен (webhook: /meta)")
    while True:
        time.sleep(3600)

# ══════════════════════════════════════════════
# БОТ 6: TIKTOK (Flask webhook)
# ══════════════════════════════════════════════

def run_tiktok():
    import tiktok_main as tm
    print("[tiktok-bot] ✅ Загружен (webhook: /tiktok)")
    tm.set_webhook()
    while True:
        time.sleep(3600)

# ══════════════════════════════════════════════
# ЗАПУСК ВСЕХ БОТОВ
# ══════════════════════════════════════════════

def start_all():
    print("=" * 55)
    print("🚀 MASTER LAUNCHER v4")
    print("=" * 55)

    bots = [
        ("football-bot", run_football),
        ("scalper-bot",  run_scalper),
        ("scanner-bot",  run_scanner),
        ("neuro-bot",    run_neuro),
        ("meta-bot",     run_meta),
        ("tiktok-bot",   run_tiktok),
    ]

    for name, func in bots:
        run_once(name, func)
        time.sleep(5)  # пауза между запусками

    print("=" * 55)
    print("✅ Все боты запущены!")
    print("=" * 55)

# ══════════════════════════════════════════════
# ГЛАВНЫЙ ЗАПУСК
# ══════════════════════════════════════════════

if __name__ == "__main__":
    PORT = int(os.environ.get("PORT", 10000))
    threading.Thread(target=start_all, daemon=True).start()
    print(f"[health] 🌐 Сервер на порту {PORT}...")
    health_app.run(host="0.0.0.0", port=PORT)
