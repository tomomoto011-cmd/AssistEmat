import asyncio
import logging
import os
import aiohttp

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiohttp import web

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
QWEN_API_KEY = os.getenv("QWEN_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GROK_API_KEY = os.getenv("GROK_API_KEY")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ================== SYSTEM ==================

SYSTEM_QWEN = "Ты дружелюбный собеседник."
SYSTEM_OPENAI = "Ты резервный помощник."
SYSTEM_GROK = "Ты деловой секретарь."

# ================== QWEN (FIXED) ==================

async def ask_qwen(text):
    url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"

    headers = {
        "Authorization": f"Bearer {QWEN_API_KEY}",
        "Content-Type": "application/json"
    }

    data = {
        "model": "qwen-plus",
        "input": {
            "messages": [
                {"role": "system", "content": SYSTEM_QWEN},
                {"role": "user", "content": text}
            ]
        }
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=data, headers=headers) as resp:
            if resp.status != 200:
                text_resp = await resp.text()
                raise Exception(f"Qwen HTTP {resp.status}: {text_resp}")

            res = await resp.json()

            return res["output"]["text"]


# ================== OPENAI (FIXED) ==================

async def ask_openai(text):
    url = "https://api.openai.com/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }

    data = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": SYSTEM_OPENAI},
            {"role": "user", "content": text}
        ]
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=data, headers=headers) as resp:
            res = await resp.json()

            if "choices" not in res:
                raise Exception(f"OpenAI error: {res}")

            return res["choices"][0]["message"]["content"]


# ================== GROK ==================

async def ask_grok(text):
    url = "https://api.x.ai/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {GROK_API_KEY}",
        "Content-Type": "application/json"
    }

    data = {
        "model": "grok-beta",
        "messages": [
            {"role": "system", "content": SYSTEM_GROK},
            {"role": "user", "content": text}
        ]
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=data, headers=headers) as resp:
            res = await resp.json()

            if "choices" not in res:
                raise Exception(f"Grok error: {res}")

            return res["choices"][0]["message"]["content"]


# ================== ROUTER ==================

async def ask_ai(text):
    text_lower = text.lower()

    # секретарь
    if any(w in text_lower for w in ["сделай", "напиши", "сформулируй", "план"]):
        try:
            print("🧠 GROK")
            return await ask_grok(text)
        except Exception as e:
            print("❌ Grok:", e)

    # основной
    try:
        print("🧠 QWEN")
        return await ask_qwen(text)
    except Exception as e:
        print("❌ Qwen:", e)

    # fallback
    try:
        print("🧠 OPENAI")
        return await ask_openai(text)
    except Exception as e:
        print("❌ OpenAI:", e)

    return "⚠️ Все AI сейчас недоступны"


# ================== HANDLERS ==================

@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("🚀 Бот работает!")

@dp.message()
async def chat(message: types.Message):
    response = await ask_ai(message.text)
    await message.answer(response)


# ================== HEALTH ==================

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

    print("🌐 Health сервер запущен")


# ================== MAIN ==================

async def main():
    print("🚀 START MAIN")

    await start_health_server()

    await bot.delete_webhook(drop_pending_updates=True)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())