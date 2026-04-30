import os
import asyncio
import logging
from aiohttp import web
import requests

from aiogram import Bot, Dispatcher, types

# ================= CONFIG =================

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")

QWEN_KEY = os.getenv("QWEN_API_KEY")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")

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
- Пиши естественно, как человек
- Не будь сухим
- Поддерживай диалог

Если не понял:
→ "Не совсем тебя понял, уточни пожалуйста 🙏"
"""

# ================= UTILS =================

def safe_get_content(data):
    try:
        return data["choices"][0]["message"]["content"]
    except:
        print("❌ Формат ответа:", data)
        return None


def is_russian(text):
    if not text:
        return False
    return any("а" <= c <= "я" or "А" <= c <= "Я" for c in text)

# ================= QWEN =================

def ask_qwen(user_id, message):
    if not QWEN_KEY:
        return None

    print("🧠 QWEN")

    history = user_memory.get(user_id, [])

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += history[-5:]
    messages.append({"role": "user", "content": message})

    try:
        response = requests.post(
            "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
            headers={
                "Authorization": f"Bearer {QWEN_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "qwen-turbo",
                "input": {
                    "messages": messages
                },
                "parameters": {
                    "temperature": 0.85
                }
            },
            timeout=15
        )

        if response.status_code != 200:
            print("❌ QWEN:", response.text)
            return None

        data = response.json()

        try:
            reply = data["output"]["choices"][0]["message"]["content"]
        except:
            print("❌ QWEN формат:", data)
            return None

        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": reply})
        user_memory[user_id] = history[-10:]

        return reply

    except Exception as e:
        print("❌ QWEN EX:", e)
        return None

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
                "temperature": 0.85
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

# ================= HANDLER =================

@dp.message()
async def handle_message(message: types.Message):
    text = message.text or ""
    user_id = message.from_user.id

    if not is_russian(text):
        text = f"Ответь на русском: {text}"

    # 1. QWEN (основной)
    reply = ask_qwen(user_id, text)
    source = "Qwen"

    # 2. fallback
    if not reply:
        reply = ask_openrouter(user_id, text)
        source = "OpenRouter"

    if not reply:
        reply = "❌ AI временно недоступны"
        source = "None"

    await message.answer(f"{reply}\n\n— 🧠 {source}")

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