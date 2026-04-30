import os
import asyncio
import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiohttp import web

BOT_TOKEN = os.getenv("BOT_TOKEN")
QWEN_API_KEY = os.getenv("QWEN_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GROK_API_KEY = os.getenv("GROK_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

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


# ================== GROK ==================

async def ask_grok(prompt):
    if not GROK_API_KEY:
        return prompt

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.x.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {GROK_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "grok-1",
                    "messages": [
                        {"role": "system", "content": "Ты секретарь. Улучши и структурируй запрос."},
                        {"role": "user", "content": prompt}
                    ]
                }
            ) as resp:
                data = await resp.json()
                return data["choices"][0]["message"]["content"]
    except Exception as e:
        print("❌ GROK:", e)
        return prompt


# ================== QWEN ==================

async def ask_qwen(prompt):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
                headers={
                    "Authorization": f"Bearer {QWEN_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "qwen-turbo",
                    "input": {
                        "messages": [
                            {"role": "user", "content": prompt}
                        ]
                    }
                }
            ) as resp:

                data = await resp.json()
                return data["output"]["text"]

    except Exception as e:
        print("❌ QWEN:", e)
        return None


# ================== OPENAI ==================

async def ask_openai(prompt):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "gpt-4o-mini",
                    "messages": [
                        {"role": "user", "content": prompt}
                    ]
                }
            ) as resp:
                data = await resp.json()
                return data["choices"][0]["message"]["content"]

    except Exception as e:
        print("❌ OPENAI:", e)
        return "❌ Все AI сейчас недоступны"


# ================== HANDLER ==================

@dp.message()
async def handle_message(message: Message):
    text = message.text

    print("🧠 GROK")
    improved = await ask_grok(text)

    print("🧠 QWEN")
    answer = await ask_qwen(improved)

    if not answer:
        print("🧠 OPENAI fallback")
        answer = await ask_openai(text)

    await message.answer(answer)


# ================== MAIN ==================

async def main():
    print("🚀 START MAIN")

    await start_health_server()

    # 🔥 фикс конфликта polling
    await bot.delete_webhook(drop_pending_updates=True)

    # 🔔 уведомление админу
    try:
        if ADMIN_ID:
            await bot.send_message(ADMIN_ID, "🟢 AssistEmpat перезапущен и готов к работе")
    except Exception as e:
        print("❌ ADMIN notify:", e)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())