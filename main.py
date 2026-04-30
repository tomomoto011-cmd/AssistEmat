import os
import asyncio
import logging
import aiohttp

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiohttp import web

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
KIE_API_KEY = os.getenv("KIE_API_KEY")

ADMIN_ID = 8590402564

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ================= AI =================

async def ask_openrouter(prompt):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "mistralai/mixtral-8x7b-instruct",
                    "messages": [{"role": "user", "content": prompt}]
                },
                timeout=20
            ) as resp:

                if resp.status != 200:
                    text = await resp.text()
                    print("❌ OpenRouter HTTP:", text)
                    return None

                data = await resp.json()
                return data["choices"][0]["message"]["content"]

    except Exception as e:
        print("❌ OpenRouter:", e)
        return None


async def ask_groq(prompt):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "llama3-70b-8192",
                    "messages": [{"role": "user", "content": prompt}]
                },
                timeout=20
            ) as resp:

                if resp.status != 200:
                    text = await resp.text()
                    print("❌ Groq HTTP:", text)
                    return None

                data = await resp.json()
                return data["choices"][0]["message"]["content"]

    except Exception as e:
        print("❌ Groq:", e)
        return None


async def ask_kie(prompt):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.kie.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {KIE_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "gpt-3.5-turbo",
                    "messages": [{"role": "user", "content": prompt}]
                },
                timeout=20
            ) as resp:

                if resp.status != 200:
                    text = await resp.text()
                    print("❌ KIE HTTP:", text)
                    return None

                data = await resp.json()
                return data["choices"][0]["message"]["content"]

    except Exception as e:
        print("❌ KIE:", e)
        return None


async def get_ai_response(text):
    print("🧠 OPENROUTER")
    answer = await ask_openrouter(text)
    if answer:
        return answer

    print("⚡ GROQ fallback")
    answer = await ask_groq(text)
    if answer:
        return answer

    print("🧩 KIE fallback")
    answer = await ask_kie(text)
    if answer:
        return answer

    return "❌ Все AI сейчас недоступны"


# ================= HANDLERS =================

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    await message.answer("🚀 Бот работает!")


@dp.message()
async def handle_message(message: types.Message):
    text = message.text

    reply = await get_ai_response(text)

    await message.answer(reply)


# ================= HEALTH SERVER =================

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


# ================= MAIN =================

async def main():
    print("🚀 БОТ ЗАПУЩЕН")
    print("🧠 OpenRouter | ⚡ Groq | 🧩 Kie")

    await start_health_server()

    # фикс конфликта Telegram
    await bot.delete_webhook(drop_pending_updates=True)

    # уведомление админу
    try:
        await bot.send_message(ADMIN_ID, "✅ Бот перезапущен")
    except:
        print("❌ Не удалось отправить сообщение админу")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())