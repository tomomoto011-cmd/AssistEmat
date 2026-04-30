import os
import asyncio
import logging
from aiohttp import web
import requests

from aiogram import Bot, Dispatcher, types

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")

OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")
GROK_KEY = os.getenv("GROK_KEY")
KIE_KEY = os.getenv("KIE_KEY")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# =========================
# ПАМЯТЬ (контекст)
# =========================
user_memory = {}

# =========================
# SYSTEM PROMPT (ВАЖНО!)
# =========================
SYSTEM_PROMPT = """
Ты — умный, живой и дружелюбный AI-ассистент.

Правила:
- Всегда отвечай на русском языке (если пользователь явно не попросил другой язык)
- Общайся естественно, как человек, а не как робот
- Добавляй немного эмоций и живости в речь
- Не будь сухим

Роли:
- Основной: разговорный ассистент
- Иногда: помощник, советник, объясняющий

Если не понял пользователя:
→ скажи: "Не совсем тебя понял, уточни пожалуйста 🙏"

Если сообщение странное/бессмысленное:
→ мягко уточни, что он имел в виду

Контекст:
- Запоминай тему разговора
- Поддерживай диалог

Никогда:
- не переходи на английский без просьбы
- не пиши сухо как документация
"""

# =========================
# ПРОВЕРКА ЯЗЫКА
# =========================
def is_russian(text):
    return any("а" <= c <= "я" or "А" <= c <= "Я" for c in text)

# =========================
# OPENROUTER (основной)
# =========================
def ask_openrouter(user_id, message):
    print("🧠 OPENROUTER")

    history = user_memory.get(user_id, [])

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += history[-5:]
    messages.append({"role": "user", "content": message})

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "mistralai/mixtral-8x7b-instruct",
                "messages": messages,
                "temperature": 0.85
            },
            timeout=15
        )

        data = response.json()

        reply = data["choices"][0]["message"]["content"]

        # сохраняем контекст
        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": reply})
        user_memory[user_id] = history[-10:]

        return reply

    except Exception as e:
        print("❌ OpenRouter:", e)
        return None

# =========================
# GROK (резерв)
# =========================
def ask_grok(message):
    print("🧠 GROK")

    try:
        response = requests.post(
            "https://api.x.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROK_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "grok-beta",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": message}
                ],
                "temperature": 0.85
            },
            timeout=15
        )

        data = response.json()
        return data["choices"][0]["message"]["content"]

    except Exception as e:
        print("❌ GROK:", e)
        return None

# =========================
# KIE (второй резерв)
# =========================
def ask_kie(message):
    print("🧠 KIE")

    try:
        response = requests.post(
            "https://api.kie.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {KIE_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": message}
                ],
                "temperature": 0.85
            },
            timeout=15
        )

        data = response.json()
        return data["choices"][0]["message"]["content"]

    except Exception as e:
        print("❌ KIE:", e)
        return None

# =========================
# ОБРАБОТКА СООБЩЕНИЙ
# =========================
@dp.message()
async def handle_message(message: types.Message):
    text = message.text
    user_id = message.from_user.id

    # если не русский → всё равно заставим отвечать на русском
    if not is_russian(text):
        text = f"Ответь на русском: {text}"

    reply = ask_openrouter(user_id, text)

    if not reply:
        reply = ask_grok(text)

    if not reply:
        reply = ask_kie(text)

    if not reply:
        reply = "❌ Все AI сейчас недоступны. Попробуй позже."

    await message.answer(reply)

# =========================
# HEALTH SERVER
# =========================
async def health(request):
    return web.Response(text="OK")

async def start_health_server():
    app = web.Application()
    app.router.add_get("/", health)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    print("🌐 Сервер здоровья запущен")

# =========================
# MAIN
# =========================
async def main():
    print("🚀 БОТ ЗАПУЩЕН")
    print("🧠 OpenRouter | ⚡ Grok | 🧩 KIE")

    await start_health_server()

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())