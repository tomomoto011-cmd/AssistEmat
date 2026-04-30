import os
import asyncio
import logging
import re
from datetime import datetime, timedelta

from aiohttp import web
import requests
import asyncpg

from aiogram import Bot, Dispatcher, types, F

# ================= LOGGING =================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# ================= CONFIG =================

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

db = None

# ================= DB =================

async def init_db():
    global db
    db = await asyncpg.create_pool(DATABASE_URL)

    async with db.acquire() as conn:

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            name TEXT,
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
            "SELECT role, content FROM messages WHERE user_id=$1 ORDER BY id DESC LIMIT 20"
        )
    return list(reversed(rows))

# ================= FACTS =================

async def save_fact(user_id, text):
    async with db.acquire() as conn:

        # проверка на дубликаты
        exists = await conn.fetchrow(
            "SELECT * FROM user_facts WHERE user_id=$1 AND fact=$2",
            user_id, text
        )

        if not exists:
            await conn.execute(
                "INSERT INTO user_facts(user_id, fact) VALUES($1,$2)",
                user_id, text
            )
            logger.info(f"📌 Новый факт: {text}")

async def get_facts(user_id):
    async with db.acquire() as conn:
        rows = await conn.fetch(
            "SELECT fact FROM user_facts WHERE user_id=$1 LIMIT 10",
            user_id
        )
    return [r["fact"] for r in rows]

def extract_fact(text):
    triggers = ["я люблю", "я работаю", "мне нравится", "я часто"]
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
        prompt += "Важно помнить о пользователе:\n"
        for f in facts:
            prompt += f"- {f}\n"

    prompt += "\nДиалог:\n"

    for msg in history:
        prompt += f"{msg['role']}: {msg['content']}\n"

    if mode == "psycho":
        prompt += "\nРежим: психолог. Максимальная эмпатия.\n"
    elif mode == "doctor":
        prompt += "\nРежим: врач. Кратко и без лекарств.\n"

    prompt += f"\nuser: {text}"

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

        data = r.json()
        reply = data["choices"][0]["message"]["content"]

        logger.info(f"💬 AI: {reply[:100]}")

        return reply

    except Exception as e:
        logger.error(f"❌ AI ERROR: {e}")
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

    await save_message(user_id, "user", text)

    fact = extract_fact(text)
    if fact:
        await save_fact(user_id, fact)

    history = await get_history(user_id)
    facts = await get_facts(user_id)

    mode = detect_mode(text)
    logger.info(f"🧠 MODE: {mode}")

    prompt = build_prompt(user, history, facts, mode, text)

    reply = ask_ai(prompt)

    if not reply or len(reply) < 5:
        reply = "Не совсем понял, уточни 🙏"

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
    logger.info("🚀 БОТ ЗАПУЩЕН")

    run_uid = os.getenv("RAILWAY_RUN_UID")
    deploy_id = os.getenv("RAILWAY_DEPLOYMENT_ID")

    if run_uid and deploy_id and run_uid != deploy_id:
        logger.warning("⛔ Второй инстанс — выходим")
        return

    await init_db()
    await start_health()

    await bot.delete_webhook(drop_pending_updates=True)
    await asyncio.sleep(2)

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())