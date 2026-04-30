import os
import asyncio
import logging
import aiohttp
from collections import defaultdict, deque

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

# ================= MEMORY =================

user_memory = defaultdict(lambda: deque(maxlen=10))

def add_to_memory(user_id, role, content):
    user_memory[user_id].append({
        "role": role,
        "content": content
    })

def get_context(user_id):
    return list(user_memory[user_id])

# ================= MODE DETECTION =================

def detect_mode(text: str):
    t = text.lower()

    if any(x in t for x in ["план", "структурируй", "перефразируй", "сформулируй", "деловое"]):
        return "secretary"

    if any(x in t for x in ["боль", "температура", "лекарство", "болит", "симптом"]):
        return "medical"

    return "chat"

# ================= AI =================

async def request_ai(url, api_key, model, messages):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": model,
                    "messages": messages
                },
                timeout=20
            ) as resp:

                if resp.status != 200:
                    print(f"❌ HTTP {resp.status}:", await resp.text())
                    return None

                data = await resp.json()

                # универсальный парсинг
                if "choices" in data:
                    return data["choices"][0]["message"]["content"]

                return None

    except Exception as e:
        print("❌ AI ERROR:", e)
        return None


async def ask_openrouter(messages):
    return await request_ai(
        "https://openrouter.ai/api/v1/chat/completions",
        OPENROUTER_API_KEY,
        "mistralai/mixtral-8x7b-instruct",
        messages
    )


async def ask_groq(messages):
    return await request_ai(
        "https://api.groq.com/openai/v1/chat/completions",
        GROQ_API_KEY,
        "llama3-70b-8192",
        messages
    )


async def ask_kie(messages):
    return await request_ai(
        "https://api.kie.ai/v1/chat/completions",
        KIE_API_KEY,
        "gpt-3.5-turbo",
        messages
    )

# ================= RESPONSE =================

def is_bad_answer(text: str):
    if not text:
        return True

    bad = [
        "не могу ответить",
        "не понимаю",
        "ошибка",
        "undefined",
        "null"
    ]

    return any(b in text.lower() for b in bad)


async def get_ai_response(user_id, text):
    mode = detect_mode(text)

    context = get_context(user_id)

    # системные роли
    if mode == "chat":
        system = "Ты живой, дружелюбный собеседник. Отвечай просто и понятно."
    elif mode == "secretary":
        system = "Ты деловой ассистент. Формулируй четко, структурировано, по делу."
    else:
        system = "Ты медицинский помощник. Отвечай аккуратно и предупреждай обратиться к врачу."

    messages = [{"role": "system", "content": system}] + context + [
        {"role": "user", "content": text}
    ]

    # ===== основной =====
    print(f"🧠 MODE: {mode} → OpenRouter")
    answer = await ask_openrouter(messages)

    # ===== fallback =====
    if is_bad_answer(answer):
        print("⚡ fallback → Groq")
        answer = await ask_groq(messages)

    if is_bad_answer(answer):
        print("🧩 fallback → Kie")
        answer = await ask_kie(messages)

    # ===== финал =====
    if not answer:
        return "❌ Все AI сейчас недоступны"

    # если ответ слабый → просим уточнение
    if len(answer.strip()) < 10:
        return "🤔 Не совсем тебя понял, уточни подробнее"

    return answer

# ================= HANDLERS =================

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    await message.answer("🚀 Бот работает! Пиши что угодно.")

@dp.message()
async def handle_message(message: types.Message):
    user_id = message.from_user.id
    text = message.text

    add_to_memory(user_id, "user", text)

    reply = await get_ai_response(user_id, text)

    add_to_memory(user_id, "assistant", reply)

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

    print("🌐 Health сервер запущен")

# ================= MAIN =================

async def main():
    print("🚀 БОТ ЗАПУЩЕН")
    print("🧠 Chat | 📊 Secretary | 🏥 Medical")

    await start_health_server()

    await bot.delete_webhook(drop_pending_updates=True)

    try:
        await bot.send_message(ADMIN_ID, "✅ Бот перезапущен")
    except:
        pass

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())