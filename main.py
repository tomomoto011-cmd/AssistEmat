import os
import asyncio
import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message
from aiogram.filters import Command
from aiohttp import web

# ================== ENV ==================
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
QWEN_API_KEY = os.getenv("QWEN_API_KEY")
GROK_API_KEY = os.getenv("GROK_API_KEY")

print(f"DEBUG TOKEN: {BOT_TOKEN}")

# ================== BOT ==================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ================== AI CLIENTS ==================

async def ask_openai(prompt: str):
    url = "https://api.openai.com/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }

    json_data = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": "Ты живой, понимающий собеседник. Отвечай естественно и по-человечески."},
            {"role": "user", "content": prompt}
        ]
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=json_data) as resp:
            data = await resp.json()

            if "error" in data:
                raise Exception(data["error"]["message"])

            return data["choices"][0]["message"]["content"]


async def ask_qwen(prompt: str):
    url = "https://api.qwen.ai/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {QWEN_API_KEY}",
        "Content-Type": "application/json"
    }

    json_data = {
        "model": "qwen-plus",
        "messages": [
            {"role": "system", "content": "Ты эмпатичный медицинский ассистент. Дай мягкий, поддерживающий и осторожный ответ без постановки диагноза."},
            {"role": "user", "content": prompt}
        ]
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=json_data) as resp:
            data = await resp.json()

            if "error" in data:
                raise Exception(data["error"]["message"])

            return data["choices"][0]["message"]["content"]


async def ask_grok(prompt: str):
    url = "https://api.x.ai/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {GROK_API_KEY}",
        "Content-Type": "application/json"
    }

    json_data = {
        "model": "grok-1",
        "messages": [
            {"role": "system", "content": "Ты деловой ассистент. Переформулируй текст чётко, структурированно и профессионально."},
            {"role": "user", "content": prompt}
        ]
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=json_data) as resp:
            data = await resp.json()

            if "error" in data:
                raise Exception(data["error"]["message"])

            return data["choices"][0]["message"]["content"]

# ================== ROUTER ==================

def detect_mode(text: str):
    text = text.lower()

    medical_words = ["болит", "температура", "симптом", "врач", "лекарство"]
    business_words = ["сделай текст", "переформулируй", "деловое", "письмо", "запрос"]

    if any(w in text for w in medical_words):
        return "qwen"

    if any(w in text for w in business_words):
        return "grok"

    return "openai"


async def ask_ai(prompt: str):
    mode = detect_mode(prompt)

    try:
        if mode == "qwen":
            print("🧠 QWEN")
            return await ask_qwen(prompt)

        if mode == "grok":
            print("🧠 GROK")
            return await ask_grok(prompt)

        print("🧠 OPENAI")
        return await ask_openai(prompt)

    except Exception as e:
        print(f"❌ Ошибка основного AI: {e}")

        # fallback
        for fallback in [ask_openai, ask_qwen, ask_grok]:
            try:
                return await fallback(prompt)
            except:
                continue

        return "⚠️ Все AI сейчас недоступны"

# ================== HANDLERS ==================

@dp.message(Command("start"))
async def start_cmd(message: Message):
    await message.answer("🤖 Бот работает 🚀")

@dp.message()
async def handle_msg(message: Message):
    user_text = message.text

    reply = await ask_ai(user_text)

    await message.answer(reply)

# ================== HEALTH SERVER ==================

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

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
#gecnj    