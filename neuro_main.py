import logging
import asyncio
import threading
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler,
    PreCheckoutQueryHandler, MessageHandler, filters
)

import config
from handlers.start import get_registration_handler
from handlers.admin import get_broadcast_handler, admin_command, admin_stats, admin_users
from handlers.menu import (
    show_main_menu, show_modules, show_help,
    show_language_menu, change_language, show_progress,
    show_referral, show_certificate
)
from handlers.lessons import show_module, show_lesson
from handlers.tests import show_question, handle_answer
from handlers.payment import buy_module, buy_full_course, pre_checkout, successful_payment

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# ─── Keep-Alive веб-сервер ──────────────────────────────────────────────────
class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"NeuroAcademy Bot is running!")

    def log_message(self, format, *args):
        pass


def run_keep_alive():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), KeepAliveHandler)
    logger.info(f"Keep-alive сервер запущен на порту {port}")
    server.serve_forever()


def start_keep_alive():
    thread = threading.Thread(target=run_keep_alive, daemon=True)
    thread.start()


# ─── Основной бот ───────────────────────────────────────────────────────────
async def main():
    # Запускаем keep-alive сервер
    start_keep_alive()

    app = Application.builder().token(config.BOT_TOKEN).build()

    # ── Регистрация ────────────────────────────────────────────────────
    app.add_handler(get_registration_handler())

    # ── Рассылка ───────────────────────────────────────────────────────
    app.add_handler(get_broadcast_handler())

    # ── Команды ────────────────────────────────────────────────────────
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("menu", show_main_menu))

    # ── Главное меню ───────────────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(show_main_menu,     pattern="^back_menu$"))
    app.add_handler(CallbackQueryHandler(show_modules,       pattern="^menu_lessons$"))
    app.add_handler(CallbackQueryHandler(show_progress,      pattern="^menu_progress$"))
    app.add_handler(CallbackQueryHandler(show_referral,      pattern="^menu_referral$"))
    app.add_handler(CallbackQueryHandler(show_certificate,   pattern="^menu_certificate$"))
    app.add_handler(CallbackQueryHandler(show_language_menu, pattern="^menu_language$"))
    app.add_handler(CallbackQueryHandler(show_help,          pattern="^menu_help$"))
    app.add_handler(CallbackQueryHandler(change_language,    pattern="^lang_(ru|uk)$"))

    # ── Модули и уроки ─────────────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(show_module,  pattern=r"^module_\d+$"))
    app.add_handler(CallbackQueryHandler(show_lesson,  pattern=r"^lesson_\d+$"))

    # ── Тесты ──────────────────────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(show_question,  pattern=r"^test_\d+_\d+$"))
    app.add_handler(CallbackQueryHandler(handle_answer,  pattern=r"^answer_\d+_\d+_\d+$"))

    # ── Оплата ─────────────────────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(buy_module,      pattern=r"^buy_module_\d+$"))
    app.add_handler(CallbackQueryHandler(buy_full_course, pattern="^buy_full_course$"))
    app.add_handler(PreCheckoutQueryHandler(pre_checkout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))

    # ── Админ ──────────────────────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(admin_stats, pattern="^admin_stats$"))
    app.add_handler(CallbackQueryHandler(admin_users, pattern="^admin_users$"))
    app.add_handler(CallbackQueryHandler(confirm_broadcast_handler, pattern="^broadcast_confirm$"))

    # ── Запуск ─────────────────────────────────────────────────────────
    logger.info("Запуск бота...")
    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        logger.info("Бот запущен! Ожидаю сообщений...")
        # Держим бота запущенным
        await asyncio.Event().wait()


async def confirm_broadcast_handler(update: Update, ctx):
    from handlers.admin import confirm_broadcast
    await confirm_broadcast(update, ctx)


if __name__ == "__main__":
    asyncio.run(main())
