"""
╔══════════════════════════════════════════════════════════════════╗
║         TELEGRAM МЕТА-БОТ  —  фабрика Telegram-ботов            ║
╠══════════════════════════════════════════════════════════════════╣
║  Библиотека : python-telegram-bot==20.3                          ║
║  Запуск     : ApplicationBuilder + app.run_polling()             ║
║  LLM        : Groq API (llama-3.3-70b-versatile) via requests   ║
║  GitHub     : PyGithub                                           ║
╠══════════════════════════════════════════════════════════════════╣
║  Pipeline:                                                       ║
║    1. Пользователь описывает бота                                ║
║    2. ask_groq()           → Groq REST API via requests          ║
║    3. create_github_repo() → PyGithub                            ║
║    4. Бот отвечает ссылкой на GitHub + инструкцией по деплою    ║
╚══════════════════════════════════════════════════════════════════╝
"""

import os
import re
import time
import logging
import asyncio
import functools
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

import requests
from github import Github, GithubException

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ──────────────────────────────────────────────────────────────────
#  ЛОГИРОВАНИЕ
# ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────
#  HTTP HEALTH SERVER  —  стартует НЕМЕДЛЕННО на уровне модуля
#
#  Render делает health-check сразу после старта процесса.
#  Если порт не отвечает в течение нескольких секунд —
#  Render считает деплой упавшим и убивает процесс.
#  Запуск на уровне модуля гарантирует, что порт открыт
#  ещё до того, как ApplicationBuilder начнёт инициализацию.
# ──────────────────────────────────────────────────────────────────

class HealthHandler(BaseHTTPRequestHandler):
    """Минимальный HTTP-обработчик: любой GET → 200 OK."""

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass  # Подавляем стандартный лог каждого запроса


# Порт берётся из переменной окружения PORT, которую Render задаёт сам.
# Дефолт 10000 совпадает с дефолтом Render для Web Service.
PORT          = int(os.environ.get("PORT", 10000))
health_server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
health_thread = threading.Thread(target=health_server.serve_forever, daemon=True)
health_thread.start()
print(f"Health server started on port {PORT}", flush=True)


# ──────────────────────────────────────────────────────────────────
#  ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ
# ──────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN  = os.environ.get("TELEGRAM_TOKEN",  "8423691923:AAF0pIR_FiylsYaHRC_CfkW_tTB0PRKh3r4")
GROQ_API_KEY    = os.environ.get("GROQ_API_KEY",    "")
GITHUB_TOKEN    = os.environ.get("GITHUB_TOKEN",    "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")
GITHUB_USERNAME = os.environ.get("GITHUB_USERNAME", "Kursha-vel")


# ══════════════════════════════════════════════════════════════════
#  ШАГ 1 — Groq API через requests
# ══════════════════════════════════════════════════════════════════

def ask_groq(prompt: str) -> str:
    """
    Отправляет prompt в Groq API (OpenAI-совместимый формат),
    возвращает текст ответа. Только requests — никакого SDK.
    """
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type":  "application/json",
    }
    data = {
        "model":    "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": prompt}],
    }

    resp = requests.post(url, headers=headers, json=data, timeout=120)

    if resp.status_code != 200:
        raise RuntimeError(f"Groq API [{resp.status_code}]: {resp.text}")

    return resp.json()["choices"][0]["message"]["content"]


def generate_bot_code(description: str) -> dict:
    """
    Формирует prompt, вызывает ask_groq(), парсит структурированный ответ.

    Возвращает dict:
      bot_name     — slug репозитория, напр. "echo-bot-42731"
      bot_code     — содержимое main.py нового бота
      requirements — содержимое requirements.txt нового бота
      render_yaml  — содержимое render.yaml нового бота
    """
    prompt = f"""
Ты — эксперт по разработке Telegram-ботов на Python.

Пользователь хочет создать бота:
---
{description}
---

Напиши ГОТОВЫЙ рабочий код. Строго соблюдай формат ответа:

===BOT_NAME===
<slug на английском через дефис, например: echo-bot>
===BOT_NAME_END===

===MAIN_PY===
<полный код main.py>
===MAIN_PY_END===

===REQUIREMENTS===
<содержимое requirements.txt>
===REQUIREMENTS_END===

===RENDER_YAML===
<содержимое render.yaml>
===RENDER_YAML_END===

Обязательные правила:
- Используй python-telegram-bot==20.3
- Токен: os.environ.get("TELEGRAM_TOKEN")
- Запуск строго через:
    def main():
        app = ApplicationBuilder().token(TOKEN).build()
        app.add_handler(...)
        app.run_polling(drop_pending_updates=True)
    if __name__ == "__main__":
        main()
- Хендлеры должны быть async def
- render.yaml: тип worker, plan free, pythonVersion "3.11.0", startCommand: python main.py
- Добавь /start с описанием функционала бота
- Только текст внутри блоков ===...===, никаких пояснений снаружи
"""

    logger.info("Запрос к Groq...")
    raw = ask_groq(prompt)
    logger.info("Groq ответил, символов: %d", len(raw))

    # ── Извлекаем именованные блоки ──────────────────────────────
    def extract(tag: str) -> str:
        m = re.search(
            rf"==={re.escape(tag)}===\s*(.*?)\s*==={re.escape(tag)}_END===",
            raw,
            re.DOTALL,
        )
        return m.group(1).strip() if m else ""

    bot_name     = extract("BOT_NAME")
    bot_code     = extract("MAIN_PY")
    requirements = extract("REQUIREMENTS")
    render_yaml  = extract("RENDER_YAML")

    # ── Снимаем markdown-обёртки ```python ... ``` ───────────────
    def strip_fences(text: str) -> str:
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text.strip())
        text = re.sub(r"\n?```$",           "", text.strip())
        return text.strip()

    bot_code     = strip_fences(bot_code)
    requirements = strip_fences(requirements)
    render_yaml  = strip_fences(render_yaml)

    # ── Безопасный slug + уникальный суффикс ─────────────────────
    if not bot_name:
        bot_name = "generated-bot"
    bot_name = re.sub(r"[^a-z0-9-]", "-", bot_name.lower()).strip("-")[:45]
    bot_name = f"{bot_name}-{int(time.time()) % 100000}"

    logger.info("Имя бота: %s", bot_name)
    return {
        "bot_name":     bot_name,
        "bot_code":     bot_code,
        "requirements": requirements,
        "render_yaml":  render_yaml,
    }


# ══════════════════════════════════════════════════════════════════
#  ШАГ 2 — GitHub: создаём репозиторий и загружаем файлы
# ══════════════════════════════════════════════════════════════════

def create_github_repo(generated: dict) -> str:
    """
    Создаёт публичный репозиторий на GitHub через PyGithub
    и загружает три файла: main.py, requirements.txt, render.yaml.
    Возвращает HTML URL репозитория.
    """
    bot_name = generated["bot_name"]
    logger.info("Создаю GitHub репозиторий: %s", bot_name)

    gh   = Github(GITHUB_TOKEN)
    user = gh.get_user()

    try:
        repo = user.create_repo(
            name=bot_name,
            description=f"Auto-generated Telegram bot: {bot_name}",
            private=False,
            auto_init=False,    # файлы загружаем сами
        )
    except GithubException as e:
        raise RuntimeError(f"GitHub create repo: {e.data}") from e

    logger.info("Репозиторий создан: %s", repo.html_url)

    # Дефолтные значения на случай пустого ответа Groq
    default_reqs = "python-telegram-bot==20.3\nrequests==2.31.0\n"
    default_yaml = (
        "services:\n"
        f"  - type: worker\n"
        f"    name: {bot_name}\n"
        "    runtime: python\n"
        "    plan: free\n"
        "    pythonVersion: \"3.11.0\"\n"
        "    buildCommand: pip install -r requirements.txt\n"
        "    startCommand: python main.py\n"
    )

    files = {
        "main.py":          generated["bot_code"]     or "# generated bot",
        "requirements.txt": generated["requirements"] or default_reqs,
        "render.yaml":      generated["render_yaml"]  or default_yaml,
    }

    for filename, content in files.items():
        if not content.strip():
            logger.warning("Пустой файл, пропускаем: %s", filename)
            continue
        try:
            repo.create_file(
                path=filename,
                message=f"Add {filename}",
                content=content,
            )
            logger.info("Загружен: %s", filename)
        except GithubException as e:
            raise RuntimeError(f"GitHub upload {filename}: {e.data}") from e

    return repo.html_url


# ══════════════════════════════════════════════════════════════════
#  ВСПОМОГАТЕЛЬНАЯ: синхронный вызов в пуле потоков
# ══════════════════════════════════════════════════════════════════

async def run_sync(fn, *args):
    """
    Запускает синхронную функцию (requests, PyGithub) через
    loop.run_in_executor — не блокирует event loop бота.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, functools.partial(fn, *args))


# ══════════════════════════════════════════════════════════════════
#  TELEGRAM HANDLERS  (async — обязательно для v20)
# ══════════════════════════════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команд /start и /help."""
    await update.message.reply_text(
        "👋 Привет! Я *Мета-бот* — фабрика Telegram-ботов.\n\n"
        "✍️ Опиши бота, которого хочешь создать, и я:\n"
        "  1️⃣ Сгенерирую код через *Groq AI*\n"
        "  2️⃣ Создам репозиторий на *GitHub*\n"
        "  3️⃣ Дам инструкцию для деплоя на *Render*\n\n"
        "📝 *Пример:* «Бот-переводчик с русского на английский»\n\n"
        "⏳ Генерация занимает ~20–40 секунд. Напиши описание — и поехали!",
        parse_mode="Markdown",
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Основной обработчик текста.
    Pipeline: Groq генерирует код → PyGithub создаёт репозиторий →
    бот отвечает ссылкой на GitHub + инструкцией по деплою на Render.
    """
    user_text = (update.message.text or "").strip()
    if not user_text:
        await update.message.reply_text("⚠️ Напишите описание бота.")
        return

    logger.info(
        "[%d] %s: %s",
        update.effective_user.id,
        update.effective_user.first_name,
        user_text[:80],
    )

    # Статусное сообщение — редактируем на каждом шаге
    status = await update.message.reply_text(
        "⚙️ *Запускаю конвейер...*\n\n🤖 Шаг 1/2 — Groq генерирует код...",
        parse_mode="Markdown",
    )

    # ── ШАГ 1: Groq генерирует код ──────────────────────────────
    try:
        generated = await run_sync(generate_bot_code, user_text)
    except Exception as exc:
        logger.exception("Ошибка Groq")
        await status.edit_text(
            f"❌ *Ошибка Groq:*\n`{exc}`",
            parse_mode="Markdown",
        )
        return

    bot_name = generated["bot_name"]

    # ── ШАГ 2: GitHub создаёт репозиторий ───────────────────────
    try:
        await status.edit_text(
            f"✅ Код сгенерирован!\n\n"
            f"📦 Шаг 2/2 — Создаю репозиторий `{bot_name}`...",
            parse_mode="Markdown",
        )
        repo_url = await run_sync(create_github_repo, generated)
    except Exception as exc:
        logger.exception("Ошибка GitHub")
        await status.edit_text(
            f"❌ *Ошибка GitHub:*\n`{exc}`",
            parse_mode="Markdown",
        )
        return

    # ── Финальное сообщение с инструкцией по деплою ─────────────
    await status.edit_text(
        f"✅ Код создан и залит на GitHub!\n\n"
        f"📁 *Репозиторий:* {repo_url}\n\n"
        f"🚀 *Чтобы задеплоить на Render \\(2 минуты\\):*\n"
        f"1\\. Зайди на [render\\.com](https://render.com)\n"
        f"2\\. Нажми *New\\+* → *Web Service*\n"
        f"3\\. Выбери репозиторий `{bot_name}`\n"
        f"4\\. Нажми *Deploy*\n\n"
        f"⚙️ *Не забудь добавить переменную:*\n"
        f"`TELEGRAM_TOKEN` \\= токен нового бота от @BotFather",
        parse_mode="MarkdownV2",
        disable_web_page_preview=True,
    )


# ══════════════════════════════════════════════════════════════════
#  ТОЧКА ВХОДА
# ══════════════════════════════════════════════════════════════════

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help",  start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Удаляем вебхук и сбрасываем очередь апдейтов перед стартом.
    # Устраняет ошибку Conflict: terminated by other getUpdates request.
    async def post_init(application):
        await application.bot.delete_webhook(drop_pending_updates=True)

    app.post_init = post_init

    logger.info("Мета-бот запущен.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
