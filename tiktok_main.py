import os
import json
import requests
import threading
import time
from flask import Flask, request

# ---------------- КОНФИГ ---------------- #

TOKEN      = os.environ.get("TIKTOK_BOT_TOKEN", "")
GROQ_KEY   = os.environ.get("GROQ_API_KEY", "")
RENDER_URL = os.environ.get("RENDER_URL", "")

GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"

app = Flask(__name__)

# ---------------- ПАМЯТЬ РАЗГОВОРОВ ---------------- #

# { chat_id: { "history": [...], "scenario": "...", "sora": "...", "prediction": "..." } }
sessions = {}

MAX_HISTORY = 20

SYSTEM_PROMPT = """Ты эксперт по созданию вирусного TikTok контента о футбольных прогнозах.

Твоя задача:
1. Генерировать сценарии 15-секундных TikTok видео
2. Генерировать промпты для Sora AI
3. Редактировать контент по запросу пользователя в разговорном стиле

━━━ КРИТИЧЕСКИ ВАЖНО: ЗАПРЕЩЁННЫЕ СЛОВА TIKTOK ━━━

НИКОГДА не используй эти слова — TikTok банит аккаунт:
❌ "ставка" / "ставим" / "ставлю" / "сделать ставку"
❌ "букмекер" / "букмекерская контора"
❌ "мы ставим" / "наша ставка"
❌ "выиграть деньги" / "заработать на ставках"
❌ "коэффициент" (заменяй на "котировка" или просто число)
❌ "беттинг" / "betting"
❌ "прогноз на деньги"

ВМЕСТО ЭТОГО используй:
✅ "я жду победу" / "мой выбор"
✅ "я верю в" / "я склоняюсь к"
✅ "моё мнение" / "по моему анализу"
✅ "шансы" вместо "коэффициент"
✅ "прогноз" вместо "ставка"
✅ "победит" / "возьмёт верх"
✅ "давай посмотрим" / "интересный матч"
✅ "мой фаворит сегодня"

Примеры замены:
❌ "Сегодня мы делаем ставку на победу Реала"
✅ "Сегодня я жду победу Реала"

❌ "Мы ставим на П1, коэффициент 2.10"
✅ "Мой выбор — победа хозяев, шансы 2.10"

❌ "Не пропустишь шанс выиграть?"
✅ "Не пропусти мой следующий разбор!"

━━━ СТРУКТУРА TIKTOK СЦЕНАРИЯ (СТРОГО) ━━━

🎬 ИНТРО (3 сек) — цепляющая фраза, стоп-скролл, БЕЗ слова "ставка"
⚽ ПРОГНОЗ (8 сек) — анализ матча, мнение эксперта, личный выбор
📣 ПРИЗЫВ (4 сек) — подписка/лайк, следующий разбор

Структура Sora промпта:
- Основной промпт на английском (для лучших результатов)
- Текст на экране на русском (КРАТКИЙ — максимум 5-6 слов на строку)
- Озвучка на русском (КОРОТКАЯ — только ключевые мысли)
- Технические параметры (9:16, 15 сек)

━━━ ПРАВИЛА ТЕКСТА ━━━
- Озвучка максимально короткая — 15 секунд это МАЛО
- Текст на экране — крупный, максимум 5 слов на строку
- Говори от первого лица "Я" а не "МЫ"
- Стиль: уверенный эксперт, не рекламщик

Стиль общения:
- Разговорный, дружелюбный
- Когда редактируешь — показывай только изменённую часть
- Объясняй что изменил и почему
- Предлагай альтернативы если нужно
- Всегда на русском языке"""


def get_session(chat_id):
    if chat_id not in sessions:
        sessions[chat_id] = {
            "history":    [],
            "scenario":   None,
            "sora":       None,
            "prediction": None,
            "mode":       "idle",  # idle / generated / editing
        }
    return sessions[chat_id]


# ---------------- TELEGRAM ---------------- #

def send_message(chat_id, text, buttons=None):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    if len(text) > 4000:
        parts = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for part in parts:
            payload = {"chat_id": chat_id, "text": part, "parse_mode": "HTML"}
            try:
                requests.post(url, data=payload, timeout=10)
                time.sleep(0.5)
            except:
                pass
        return
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if buttons:
        payload["reply_markup"] = json.dumps({"inline_keyboard": buttons})
    try:
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        print(f"Ошибка отправки: {e}")

def send_typing(chat_id):
    url = f"https://api.telegram.org/bot{TOKEN}/sendChatAction"
    try:
        requests.post(url, data={"chat_id": chat_id, "action": "typing"}, timeout=5)
    except:
        pass

def set_webhook():
    if not RENDER_URL:
        print("RENDER_URL не задан!")
        return
    url = f"https://api.telegram.org/bot{TOKEN}/setWebhook"
    try:
        r = requests.post(
            url,
            json={"url": RENDER_URL.rstrip("/") + "/tiktok"},
            timeout=10
        )
        print(f"Webhook TikTok бота: {r.json()}")
    except Exception as e:
        print(f"Ошибка webhook: {e}")

# ---------------- GROQ ИИ ---------------- #

def ask_groq(chat_id, user_message):
    """Отправляет запрос в Groq с историей разговора"""
    session = get_session(chat_id)

    # Добавляем сообщение пользователя в историю
    session["history"].append({
        "role": "user",
        "content": user_message
    })

    # Ограничиваем историю
    if len(session["history"]) > MAX_HISTORY:
        session["history"] = session["history"][-MAX_HISTORY:]

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + session["history"]

    try:
        r = requests.post(
            GROQ_URL,
            headers={
                "Authorization": f"Bearer {GROQ_KEY}",
                "Content-Type":  "application/json"
            },
            json={
                "model":       "llama-3.3-70b-versatile",
                "messages":    messages,
                "max_tokens":  2048,
                "temperature": 0.85,
            },
            timeout=30
        )
        reply = r.json()["choices"][0]["message"]["content"]

        # Сохраняем ответ в историю
        session["history"].append({
            "role":    "assistant",
            "content": reply
        })

        return reply
    except Exception as e:
        print(f"Groq ошибка: {e}")
        return None

# ---------------- ГЕНЕРАЦИЯ КОНТЕНТА ---------------- #

def generate_initial_content(chat_id, prediction_text):
    """Генерирует сценарий и промпт для Sora с нуля"""
    session = get_session(chat_id)
    session["prediction"] = prediction_text
    session["history"]    = []  # чистая история для нового прогноза
    session["mode"]       = "generating"

    prompt = f"""Создай полный контент для TikTok видео на основе прогноза:

{prediction_text}

Нужно два блока:

━━━ БЛОК 1: СЦЕНАРИЙ TIKTOK (15 сек) ━━━

🎬 ИНТРО (3 секунды):
Текст на экране: [крупный текст, максимум 8 слов]
Озвучка: [фраза которая останавливает скролл]
Настроение: [интрига/шок/уверенность]

⚽ ОСНОВНОЙ ПРОГНОЗ (8 секунд):
Текст на экране: [ключевые факты крупно]
Озвучка: [3 причины прогноза + ставка с коэффициентом]
Настроение: [уверенность эксперта]

📣 ПРИЗЫВ К ДЕЙСТВИЮ (4 секунды):
Текст на экране: [подписка/лайк]
Озвучка: [мотивирующий призыв]
Настроение: [энергия/срочность]

━━━ БЛОК 2: ПРОМПТ ДЛЯ SORA ━━━

🎥 SORA PROMPT (English):
[Детальный промпт на английском — футбольная сцена, камера, освещение, атмосфера, движения игроков, стадион, толпа]

🔤 ТЕКСТ НА ЭКРАНЕ (русский):
[Все надписи которые появляются на видео]

🎙️ ОЗВУЧКА (русский):
[Полный текст озвучки под тайминг 15 секунд]

⚙️ ПАРАМЕТРЫ:
Формат: 9:16 вертикальный
Длительность: 15 секунд
Стиль: Кинематографический, динамичный"""

    send_typing(chat_id)
    reply = ask_groq(chat_id, prompt)

    if not reply:
        send_message(chat_id, "❌ Ошибка генерации. Попробуй ещё раз!")
        session["mode"] = "idle"
        return

    # Сохраняем сгенерированный контент
    session["scenario"] = reply
    session["mode"]     = "generated"

    send_message(
        chat_id,
        f"🎬 <b>ГОТОВО! Вот твой контент:</b>\n\n{reply}",
        buttons=[
            [
                {"text": "✏️ Изменить сценарий", "callback_data": "edit_scenario"},
                {"text": "🎥 Изменить Sora", "callback_data": "edit_sora"},
            ],
            [
                {"text": "🔄 Всё заново", "callback_data": "regenerate"},
                {"text": "✅ Отлично!", "callback_data": "done"},
            ]
        ]
    )

    send_message(
        chat_id,
        "💬 <b>Или просто напиши что хочешь изменить!</b>\n\n"
        "Например:\n"
        "• <i>«сделай интро более агрессивным»</i>\n"
        "• <i>«измени призыв к действию»</i>\n"
        "• <i>«в Sora промпте сделай ночной стадион»</i>\n"
        "• <i>«коэффициент 1.95 а не 2.10»</i>"
    )


def edit_content(chat_id, edit_request):
    """Редактирует контент на основе запроса пользователя"""
    session = get_session(chat_id)

    send_typing(chat_id)

    # Контекст для редактирования
    context = f"""Вот текущий сгенерированный контент:

{session.get('scenario', 'Контент не найден')}

Запрос на изменение: {edit_request}

Внеси нужные изменения. 
- Если меняешь только часть — покажи только изменённую часть и объясни что изменил
- Если меняешь всё — покажи полный обновлённый контент
- Будь разговорным, объясни своё решение
- Предложи альтернативу если есть идеи"""

    reply = ask_groq(chat_id, context)

    if not reply:
        send_message(chat_id, "❌ Ошибка. Попробуй ещё раз!")
        return

    # Обновляем сохранённый контент
    session["scenario"] = reply
    session["mode"]     = "editing"

    send_message(
        chat_id,
        f"✏️ <b>Обновлено!</b>\n\n{reply}",
        buttons=[
            [
                {"text": "✏️ Ещё изменить", "callback_data": "edit_more"},
                {"text": "🔄 Всё заново", "callback_data": "regenerate"},
            ],
            [
                {"text": "✅ Готово!", "callback_data": "done"},
            ]
        ]
    )


# ---------------- WEBHOOK ---------------- #

@app.route("/tiktok", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        return "✅ TikTok Bot работает!"

    try:
        data = request.json
    except:
        return "ok"

    if not data:
        return "ok"

    if "message" in data:
        msg     = data["message"]
        text    = msg.get("text", "")
        chat_id = msg["chat"]["id"]
        user    = msg.get("from", {})
        name    = user.get("first_name", "друг")
        session = get_session(chat_id)

        if not text:
            return "ok"

        # ── Команды ──────────────────────────────

        if text == "/start":
            sessions[chat_id] = {
                "history": [], "scenario": None,
                "sora": None, "prediction": None, "mode": "idle"
            }
            send_message(chat_id, f"""🎬 <b>Привет, {name}!</b>

Я создаю TikTok контент для футбольных прогнозов!

📝 <b>Отправь мне прогноз на матч</b> и я сгенерирую:

🎬 <b>Сценарий TikTok 15 сек:</b>
  • Интро 3 сек — цепляет внимание
  • Прогноз 8 сек — основной контент
  • Призыв 4 сек — подписка/лайк

🎥 <b>Промпт для Sora:</b>
  • Видеоряд на английском
  • Текст на экране на русском
  • Озвучка на русском

✏️ <b>После генерации можешь редактировать!</b>
Просто пиши что хочешь изменить — я исправлю!

<b>Пример прогноза:</b>
<i>Реал Мадрид vs Барселона. Реал дома — 4 победы подряд. Барса без Педри. Ставлю П1 @ 2.10</i>""")

        elif text == "/new":
            sessions[chat_id] = {
                "history": [], "scenario": None,
                "sora": None, "prediction": None, "mode": "idle"
            }
            send_message(chat_id, "🔄 <b>Начинаем заново!</b>\n\nОтправь новый прогноз на матч! ⚽")

        elif text == "/help":
            send_message(chat_id, """📌 <b>Как пользоваться ботом:</b>

1️⃣ Отправь прогноз на матч
2️⃣ Получи сценарий + Sora промпт
3️⃣ Редактируй в разговорном стиле!

✏️ <b>Примеры редактирования:</b>
• <i>«сделай интро более агрессивным»</i>
• <i>«измени коэффициент на 1.95»</i>
• <i>«в Sora сделай ночной стадион с дождём»</i>
• <i>«призыв сделай смешнее»</i>
• <i>«перепиши озвучку короче»</i>

🔄 /new — начать с новым прогнозом""")

        else:
            # ── Определяем что делать с сообщением ──
            mode = session.get("mode", "idle")

            if mode in ("generated", "editing"):
                # Уже есть контент — редактируем
                threading.Thread(
                    target=edit_content,
                    args=(chat_id, text),
                    daemon=True
                ).start()
            else:
                # Нет контента — генерируем новый
                threading.Thread(
                    target=generate_initial_content,
                    args=(chat_id, text),
                    daemon=True
                ).start()

    if "callback_query" in data:
        q           = data["callback_query"]["data"]
        callback_id = data["callback_query"]["id"]
        chat_id     = data["callback_query"]["message"]["chat"]["id"]
        session     = get_session(chat_id)

        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/answerCallbackQuery",
            json={"callback_query_id": callback_id},
            timeout=5
        )

        if q == "edit_scenario":
            send_message(
                chat_id,
                "✏️ <b>Что изменить в сценарии?</b>\n\n"
                "Напиши что именно хочешь изменить:\n"
                "• <i>«сделай интро с вопросом»</i>\n"
                "• <i>«добавь статистику в прогноз»</i>\n"
                "• <i>«призыв сделай агрессивнее»</i>"
            )

        elif q == "edit_sora":
            send_message(
                chat_id,
                "🎥 <b>Что изменить в Sora промпте?</b>\n\n"
                "Напиши что именно:\n"
                "• <i>«ночной стадион с дождём»</i>\n"
                "• <i>«крупный план на мяч»</i>\n"
                "• <i>«добавь болельщиков в экстазе»</i>"
            )

        elif q in ("edit_more", "edit_scenario", "edit_sora"):
            send_message(
                chat_id,
                "✏️ <b>Пиши что хочешь изменить!</b>\n\n"
                "Я исправлю любую часть контента 🎬"
            )

        elif q == "regenerate":
            if session.get("prediction"):
                send_message(chat_id, "🔄 <b>Генерирую заново...</b>")
                threading.Thread(
                    target=generate_initial_content,
                    args=(chat_id, session["prediction"]),
                    daemon=True
                ).start()
            else:
                send_message(chat_id, "❌ Отправь новый прогноз!")

        elif q == "done":
            send_message(
                chat_id,
                "✅ <b>Отлично! Контент готов!</b>\n\n"
                "Отправляй следующий прогноз — создадим ещё один TikTok! 🎬\n\n"
                "Или /new для новой сессии"
            )

    return "ok"

# ---------------- ЗАПУСК ---------------- #

def delayed_start():
    time.sleep(3)
    set_webhook()

if __name__ == "__main__":
    PORT = int(os.environ.get("PORT", 10000))
    threading.Thread(target=delayed_start, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT)
