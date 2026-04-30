import os
import asyncio
import logging
from aiohttp import web
import requests

from aiogram import Bot, Dispatcher, types

# ================= CONFIG =================

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")

OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")
GROK_KEY = os.getenv("GROK_API_KEY")
KIE_KEY = os.getenv("KIE_API_KEY")
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
- Всегда отвечай на русском языке
- Пиши как человек
- Добавляй лёгкую эмоцию
- Поддерживай диалог

Если не понял:
→ "Не совсем тебя понял, уточни пожалуйста 🙏"
"""

# ================= UTILS =================

def safe_get_content(data):
    try:
        return data["choices"][0]["message"]["content"]
    except:
        print("❌ Неправильный формат:", data)
        return None


def is_russian(text):
    if not text:
        return False
    return any("а" <= c <= "я" or "А" <= c <= "Я" for c in text)

# ================= OPENROUTER =================

def ask_openrouter(user_id, message):
    if not OPENROUTER_KEY:
        return None

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
                "temperature": 0.8
            },
            timeout=15
        )

        if response.status_code != 200:
            print("❌ OpenRouter:", response.text)
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
        print("❌ OpenRouter EX:", e)
        return None

# ================= GROK =================

def ask_grok(message):
    if not GROK_KEY:
        return None

    print("🧠 GROK")

    try:
        response = requests.post(
            "https://api.x.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROK_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "grok-1",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": message}
                ]
            },
            timeout=15
        )

        if response.status_code != 200:
            print("❌ GROK:", response.text)
            return None

        return safe_get_content(response.json())

    except Exception as e:
        print("❌ GROK EX:", e)
        return None

# ================= KIE =================

def ask_kie(message):
    if not KIE_KEY:
        return None

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
                ]
            },
            timeout=15
        )

        if response.status_code != 200:
            print("❌ KIE:", response.text)
            return None

        return safe_get_content(response.json())

    except Exception as e:
        print("❌ KIE EX:", e)
        return None

# ================= GEMINI =================

def ask_gemini(message):
    if not GEMINI_KEY:
        return None

    print("🧠 GEMINI")

    try:
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={GEMINI_KEY}",
            headers={"Content-Type": "application/json"},
            json={
                "contents": [
                    {
                        "parts": [
                            {"text": SYSTEM_PROMPT + "\n\n" + message}
                        ]
                    }
                ]
            },
            timeout=15
        )

        if response.status_code != 200:
            print("❌ GEMINI:", response.text)
            return None

        data = response.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]

    except Exception as e:
        print("❌ GEMINI EX:", e)
        return None

# ================= HANDLER =================

@dp.message()
async def handle_message(message: types.Message):
    text = message.text or ""
    user_id = message.from_user.id

    if not is_russian(text):
        text = f"Ответь на русском: {text}"

    reply = (
        ask_openrouter(user_id, text)
        or ask_grok(text)
        or ask_kie(text)
        or ask_gemini(text)
    )

    if not reply:
        reply = "❌ Все AI сейчас недоступны"

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

    # анти-дубль
    run_uid = os.getenv("RAILWAY_RUN_UID")
    deploy_id = os.getenv("RAILWAY_DEPLOYMENT_ID")

    if run_uid and deploy_id and run_uid != deploy_id:
        print("⛔ Второй инстанс — выходим")
        return

    await start_health_server()

    await bot.delete_webhook(drop_pending_updates=True)
    await asyncio.sleep(2)

    try:
        await bot.send_message(ADMIN_ID, "✅ Бот перезапущен")
    except:
        pass

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())