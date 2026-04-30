import os
import asyncio
import logging
import re
from datetime import datetime, timedelta

from aiohttp import web
import requests
import asyncpg

from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# ================= CONFIG =================

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

db = None
user_states = {}

# ================= DB =================

async def init_db():
    global db
    db = await asyncpg.create_pool(DATABASE_URL)

    async with db.acquire() as conn:

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            name TEXT,
            age INT,
            gender TEXT,
            style TEXT
        );
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            role TEXT,
            content TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_facts (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            fact TEXT
        );
        """)

# ================= MEMORY =================

async def save_message(user_id, role, content):
    async with db.acquire() as conn:
        await conn.execute(
            "INSERT INTO messages(user_id, role, content) VALUES($1,$2,$3)",
            user_id, role, content
        )

async def get_history(user_id):
    async with db.acquire() as conn:
        rows = await conn.fetch(
            "SELECT role, content FROM messages WHERE user_id=$1 ORDER BY id DESC LIMIT 10",
            user_id
        )
    return list(reversed(rows))

# ================= FACTS =================

async def save_fact(user_id, text):
    async with db.acquire() as conn:
        await conn.execute(
            "INSERT INTO user_facts(user_id, fact) VALUES($1,$2)",
            user_id, text
        )

async def get_facts(user_id):
    async with db.acquire() as conn:
        rows = await conn.fetch(
            "SELECT fact FROM user_facts WHERE user_id=$1 LIMIT 5",
            user_id
        )
    return [r["fact"] for r in rows]

def extract_fact(text):
    triggers = ["я люблю", "я работаю", "я хочу", "мне нравится"]
    for t in triggers:
        if t in text.lower():
            return text
    return None

# ================= AI =================

def detect_mode(text):
    t = text.lower()

    if any(x in t for x in ["груст", "плохо", "обид", "тревог"]):
        return "psycho"
    if any(x in t for x in ["болит", "температур", "кашель"]):
        return "doctor"
    return "normal"

def build_prompt(user, history, facts, mode, text):

    prompt = f"Ты общаешься с {user['name']} на ты.\n"

    if facts:
        prompt += "Факты о пользователе:\n" + "\n".join(facts) + "\n\n"

    for msg in history:
        prompt += f"{msg['role']}: {msg['content']}\n"

    if mode == "psycho":
        prompt += "Будь максимально эмпатичным.\n"
    elif mode == "doctor":
        prompt += "Отвечай как врач, без назначения лекарств.\n"

    prompt += f"user: {text}"

    return prompt

def ask_ai(prompt):
    try:
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_KEY}"},
            json={
                "model": "mistralai/mixtral-8x7b-instruct",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.85
            },
            timeout=15
        )
        return r.json()["choices"][0]["message"]["content"]
    except:
        return None

# ================= HANDLER =================

@dp.message()
async def handle(message: types.Message):
    user_id = message.from_user.id
    text = message.text or ""

    async with db.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE user_id=$1", user_id)

    if not user:
        await message.answer("Напиши /start")
        return

    # сохраняем сообщение
    await save_message(user_id, "user", text)

    # извлекаем факт
    fact = extract_fact(text)
    if fact:
        await save_fact(user_id, fact)

    history = await get_history(user_id)
    facts = await get_facts(user_id)

    mode = detect_mode(text)
    prompt = build_prompt(user, history, facts, mode, text)

    reply = ask_ai(prompt) or "Не совсем понял 🙏"

    await save_message(user_id, "assistant", reply)

    await message.answer(reply)

# ================= HEALTH =================

async def health(request):
    return web.Response(text="OK")

async def start_health():
    app = web.Application()
    app.router.add_get("/", health)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

# ================= MAIN =================

async def main():
    print("🚀 БОТ ЗАПУЩЕН")

    run_uid = os.getenv("RAILWAY_RUN_UID")
    deploy_id = os.getenv("RAILWAY_DEPLOYMENT_ID")

    if run_uid and deploy_id and run_uid != deploy_id:
        return

    await init_db()
    await start_health()

    await bot.delete_webhook(drop_pending_updates=True)
    await asyncio.sleep(2)

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())