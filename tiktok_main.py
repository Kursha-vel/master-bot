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
OWNER_ID   = int(os.environ.get("OWNER_ID", "0"))

GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"

app = Flask(__name__)

# ---------------- TELEGRAM ---------------- #

def send_message(chat_id, text, buttons=None):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    # Разбиваем длинные сообщения
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
        r = requests.post(url, json={"url": RENDER_URL.rstrip("/") + "/tiktok"}, timeout=10)
        print(f"Webhook TikTok бота: {r.json()}")
    except Exception as e:
        print(f"Ошибка webhook: {e}")

# ---------------- GROQ ИИ ---------------- #

def ask_groq(prompt, system):
    try:
        r = requests.post(
            GROQ_URL,
            headers={
                "Authorization": f"Bearer {GROQ_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": prompt}
                ],
                "max_tokens": 2048,
                "temperature": 0.85,
            },
            timeout=30
        )
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"Groq ошибка: {e}")
        return None

# ---------------- ГЕНЕРАТОРЫ ---------------- #

def generate_tiktok_scenario(prediction_text):
    """Генерирует сценарий TikTok видео 15 секунд"""

    system = """Ты эксперт по созданию вирусных TikTok видео о спортивных ставках.
Ты создаёшь захватывающие сценарии которые удерживают внимание зрителя.
Твой стиль: динамичный, уверенный, с интригой.
Всегда отвечай на русском языке."""

    prompt = f"""Создай сценарий для 15-секундного TikTok видео на основе этого прогноза:

{prediction_text}

Структура СТРОГО:
🎬 ИНТРО (3 секунды):
- Одна цепляющая фраза которая останавливает скролл
- Должна создать интригу или шок
- Максимум 8-10 слов

⚽ ОСНОВНОЙ ПРОГНОЗ (8 секунд):
- Ключевые факторы прогноза (2-3 пункта)
- Конкретная ставка с коэффициентом
- Уверенный тон эксперта

📣 ПРИЗЫВ К ДЕЙСТВИЮ (4 секунды):
- Призыв подписаться/лайкнуть
- Обещание следующего контента

Для каждой части укажи:
- Текст на экране (русский, крупный шрифт)
- Озвучка (русский, разговорный стиль)
- Эмоция/настроение сцены"""

    return ask_groq(prompt, system)


def generate_sora_prompt(prediction_text):
    """Генерирует промпт для Sora для футбольного видеоряда"""

    system = """You are an expert at creating Sora AI video prompts for sports content.
You create cinematic, dynamic football video prompts that match betting predictions.
Always write the main prompt in English for best Sora results."""

    prompt = f"""Create a Sora AI video prompt for a TikTok football prediction video.

The prediction is about:
{prediction_text}

Requirements:
- 15 seconds total, vertical format (9:16) for TikTok
- Cinematic football atmosphere
- Dynamic camera movements
- Match the energy of the prediction

Return EXACTLY in this format:

🎬 SORA PROMPT (English - for best results):
[Write detailed English prompt here - describe the football scene, camera angles, lighting, atmosphere, player movements, stadium, crowd]

🔤 ТЕКСТ НА ЭКРАНЕ (Russian):
[Write the Russian text overlays that appear on screen - match names, prediction, odds, call to action]

🎙️ ОЗВУЧКА (Russian):
[Write the Russian voiceover script that matches the 15-second timing]

⚙️ ТЕХНИЧЕСКИЕ ПАРАМЕТРЫ:
- Формат: Вертикальное видео 9:16
- Длительность: 15 секунд
- Разрешение: 1080x1920
- Стиль: Кинематографический, динамичный"""

    return ask_groq(prompt, system)


def process_prediction(chat_id, prediction_text):
    """Обрабатывает прогноз и генерирует весь контент"""

    send_typing(chat_id)
    send_message(chat_id, "⏳ <b>Генерирую контент...</b>\n\n🎬 Создаю сценарий TikTok...\n🎥 Готовлю промпт для Sora...")

    # Генерируем сценарий
    send_typing(chat_id)
    scenario = generate_tiktok_scenario(prediction_text)

    if not scenario:
        send_message(chat_id, "❌ Ошибка генерации. Попробуй ещё раз!")
        return

    # Генерируем Sora промпт
    send_typing(chat_id)
    sora_prompt = generate_sora_prompt(prediction_text)

    if not sora_prompt:
        send_message(chat_id, "❌ Ошибка генерации Sora промпта. Попробуй ещё раз!")
        return

    # Отправляем результаты
    send_message(chat_id, f"""🎬 <b>СЦЕНАРИЙ TIKTOK (15 сек)</b>
━━━━━━━━━━━━━━━━━━━━

{scenario}

━━━━━━━━━━━━━━━━━━━━
✅ Сценарий готов!""")

    time.sleep(1)

    send_message(chat_id, f"""🎥 <b>ПРОМПТ ДЛЯ SORA</b>
━━━━━━━━━━━━━━━━━━━━

{sora_prompt}

━━━━━━━━━━━━━━━━━━━━
✅ Промпт готов!""",
    buttons=[[
        {"text": "🔄 Regenerate", "callback_data": f"regen_{chat_id}"},
        {"text": "✅ Готово", "callback_data": "done"}
    ]])

# ---------------- ХРАНИЛИЩЕ ПОСЛЕДНИХ ПРОГНОЗОВ ---------------- #

last_predictions = {}  # { chat_id: prediction_text }

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

        if not text:
            return "ok"

        if text == "/start":
            send_message(chat_id, f"""🎬 <b>Привет, {name}!</b>

Я генерирую TikTok контент для футбольных прогнозов!

📝 <b>Просто отправь мне прогноз на матч</b>, например:

<i>"Реал Мадрид vs Барселона. Реал дома в хорошей форме, выиграли 4 из 5. Барса без Педри. Ставлю на П1 @ 2.10"</i>

И я создам:
🎬 Сценарий 15-сек TikTok видео
   • Интро 3 сек — цепляет внимание
   • Прогноз 8 сек — основной контент
   • Призыв 4 сек — подписка/лайк

🎥 Промпт для Sora:
   • На английском для видеоряда
   • Текст на экране на русском
   • Озвучка на русском

<b>Отправляй прогноз — создадим вирусное видео!</b> 🚀""")

        elif text == "/help":
            send_message(chat_id, """📌 <b>Как пользоваться ботом:</b>

1️⃣ Отправь прогноз на матч в свободной форме
2️⃣ Бот генерирует сценарий TikTok (15 сек)
3️⃣ Бот генерирует промпт для Sora
4️⃣ Используй контент для съёмки!

💡 <b>Советы для лучшего результата:</b>
• Укажи названия команд
• Добавь свою ставку и коэффициент
• Напиши 2-3 причины прогноза
• Укажи лигу если важно

📝 <b>Пример хорошего прогноза:</b>
<i>Манчестер Сити vs Арсенал, АПЛ. Сити дома непобедимы — 8 побед подряд. Арсенал без Сака травма. Холанд вернулся. Ставка: П1 @ 1.85, уверенность 80%</i>""")

        else:
            # Любой текст кроме команд = прогноз на матч
            last_predictions[chat_id] = text
            threading.Thread(
                target=process_prediction,
                args=(chat_id, text),
                daemon=True
            ).start()

    if "callback_query" in data:
        q           = data["callback_query"]["data"]
        callback_id = data["callback_query"]["id"]
        chat_id     = data["callback_query"]["message"]["chat"]["id"]

        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/answerCallbackQuery",
            json={"callback_query_id": callback_id},
            timeout=5
        )

        if q.startswith("regen_"):
            # Регенерируем контент для последнего прогноза
            if chat_id in last_predictions:
                send_message(chat_id, "🔄 <b>Регенерирую контент...</b>")
                threading.Thread(
                    target=process_prediction,
                    args=(chat_id, last_predictions[chat_id]),
                    daemon=True
                ).start()
            else:
                send_message(chat_id, "❌ Прогноз не найден. Отправь новый!")

        elif q == "done":
            send_message(chat_id, "✅ <b>Готово!</b>\n\nОтправляй следующий прогноз — создадим ещё один TikTok! 🎬")

    return "ok"

# ---------------- ЗАПУСК ---------------- #

def delayed_start():
    time.sleep(3)
    set_webhook()

if __name__ == "__main__":
    PORT = int(os.environ.get("PORT", 10000))
    threading.Thread(target=delayed_start, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT)
