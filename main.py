import os
import asyncio
import logging
from aiohttp import web
import requests

from aiogram import Bot, Dispatcher, types

# ================= CONFIG =================

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")
GEMINI_KEY = os.getenv("GEMINI_KEY")

ADMIN_ID = 8590402564

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ================= MEMORY =================

user_memory = {}

# ================= SYSTEM PROMPT =================

SYSTEM_PROMPT = """
Ты — живой, дружелюбный AI-ассистент.

Правила:
- Всегда отвечай на русском языке (если пользователь не попросил иначе)
- Пиши естественно, как человек
- Добавляй лёгкую живость в ответ
- Поддерживай диалог

Если не понял:
→ "Не совсем тебя понял, уточни пожалуйста 🙏"
"""

# ================= UTILS =================

def is_russian(text):
    if not text:
        return False
    return any("а" <= c <= "я" or "А" <= c <= "Я" for c in text)


def safe_get_content(data):
    try:
        return data["choices"][0]["message"]["content"]
    except Exception:
        print("❌ Неправильный формат ответа:", data)
        return None

# ================= OPENROUTER =================

def ask_openrouter(user_id, message):
    print("🧠 OPENROUTER")

    if not OPENROUTER_KEY:
        print("❌ OPENROUTER_KEY отсутствует")
        return None

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
            timeout=20
        )

        if response.status_code != 200:
            print("❌ OpenRouter HTTP:", response.status_code, response.text)
            return None

        data = response.json()
        reply = safe_get_content(data)

        if not reply:
            return None

        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": reply})
        user_memory[user_id] = history[-10:]

        return reply

    except Exception as e:
        print("❌ OpenRouter:", e)
        return None

# ================= GEMINI =================

def ask_gemini(message):
    print("🧠 GEMINI")

    if not GEMINI_KEY:
        print("❌ GEMINI_KEY отсутствует")
        return None

    try:
        url = f"https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}"

        response = requests.post(
            url,
            headers={"Content-Type": "application/json"},
            json={
                "contents": [
                    {
                        "parts": [
                            {"text": SYSTEM_PROMPT},
                            {"text": message}
                        ]
                    }
                ]
            },
            timeout=20
        )

        if response.status_code != 200:
            print("❌ GEMINI HTTP:", response.status_code, response.text)
            return None

        data = response.json()

        return data["candidates"][0]["content"]["parts"][0]["text"]

    except Exception as e:
        print("❌ GEMINI:", e)
        return None

# ================= HANDLER =================

@dp.message()
async def handle_message(message: types.Message):

    if not message.text:
        await message.answer("Я пока понимаю только текст 🙂")
        return

    text = message.text
    user_id = message.from_user.id

    if not is_russian(text):
        text = f"Ответь на русском: {text}"

    # 1. основной AI
    reply = ask_openrouter(user_id, text)

    # 2. fallback
    if not reply:
        reply = ask_gemini(text)

    if not reply:
        reply = "⚠️ AI временно недоступен, попробуй позже"

    await message.answer(reply)

# ================= HEALTH =================

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

# ================= MAIN =================

async def main():
    print("🚀 БОТ ЗАПУЩЕН")

    # 🛑 анти-дубль Railway
    run_uid = os.getenv("RAILWAY_RUN_UID")
    deploy_id = os.getenv("RAILWAY_DEPLOYMENT_ID")

    if run_uid and deploy_id and run_uid != deploy_id:
        print("⛔ Второй инстанс — выходим")
        return

    await start_health_server()

    await bot.delete_webhook(drop_pending_updates=True)
    await asyncio.sleep(2)

    # 🔔 баннер при старте
    try:
        await bot.send_message(ADMIN_ID, "✅ Бот перезапущен и работает")
    except Exception as e:
        print("❌ Не удалось отправить баннер:", e)

    await dp.start_polling(bot)

# ================= START =================

if __name__ == "__main__":
    asyncio.run(main())