import asyncio
import logging
import os
import re
import random
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart


import aiosqlite
import httpx
import redis.asyncio as redis

from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler

load_dotenv()
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
REDIS_URL = os.getenv("REDIS_URL")  # ОБЯЗАТЕЛЬНО добавить в Railway

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

DB_PATH = "bot.db"
scheduler = AsyncIOScheduler()

# ======================
# 🔥 REDIS LOCK (ГЛАВНЫЙ ФИКС)
# ======================
IS_MAIN = False
redis_client = None

async def acquire_lock():
    global IS_MAIN, redis_client

    if not REDIS_URL:
        logging.warning("⚠️ REDIS_URL нет → fallback в single mode")
        IS_MAIN = True
        return

    redis_client = redis.from_url(REDIS_URL)

    lock = await redis_client.set(
        "bot_lock",
        "1",
        ex=60,
        nx=True
    )

    if lock:
        IS_MAIN = True
        logging.info("✅ Я ГЛАВНЫЙ ИНСТАНС")
    else:
        logging.warning("⛔ Уже есть главный инстанс")

# keepalive lock
async def keep_lock_alive():
    while True:
        try:
            if IS_MAIN and redis_client:
                await redis_client.expire("bot_lock", 60)
        except Exception as e:
            logging.error(f"LOCK ERROR: {e}")
        await asyncio.sleep(30)

# ======================
# 🛑 АНТИ-ДУБЛЬ update_id
# ======================
LAST_UPDATE_ID = 0

@dp.update.outer_middleware()
async def anti_duplicate_middleware(handler, event, data):
    global LAST_UPDATE_ID

    update = data.get("event_update")

    if update and hasattr(update, "update_id"):
        if update.update_id <= LAST_UPDATE_ID:
            return
        LAST_UPDATE_ID = update.update_id

    return await handler(event, data)

# ======================
# БАЗА
# ======================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            name TEXT
        );

        CREATE TABLE IF NOT EXISTS memory(
            user_id INTEGER,
            role TEXT,
            content TEXT
        );

        CREATE TABLE IF NOT EXISTS habits(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT,
            streak INTEGER DEFAULT 0,
            last_done TEXT
        );

        CREATE TABLE IF NOT EXISTS emotions(
            user_id INTEGER,
            mood TEXT
        );
        """)
        await db.commit()


# 🧠 TIME PARSER
# ======================
def parse_time(text: str):
    text = text.lower()
    now = datetime.now()

    if "вечером" in text:
        return now.replace(hour=19, minute=0)

    if "после работы" in text:
        return now.replace(hour=18, minute=30)

    if "на выходных" in text:
        days_ahead = (5 - now.weekday()) % 7
        return (now + timedelta(days=days_ahead)).replace(hour=12, minute=0)

    minutes = re.search(r'через (\d+) минут', text)
    hours = re.search(r'через (\d+) час', text)

    if minutes:
        return now + timedelta(minutes=int(minutes.group(1)))
    if hours:
        return now + timedelta(hours=int(hours.group(1)))

    if "завтра" in text:
        return (now + timedelta(days=1)).replace(hour=9, minute=0)

    return None

# ======================
# ПАМЯТЬ
# ======================
async def save_memory(user_id, role, content):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO memory VALUES (?, ?, ?)", (user_id, role, content))
        await db.commit()

async def get_memory(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT role, content FROM memory WHERE user_id=? ORDER BY rowid DESC LIMIT 20",
            (user_id,)
        )
        rows = await cursor.fetchall()
        return [{"role": r[0], "content": r[1]} for r in reversed(rows)]

# ======================
# ЭМОЦИИ
# ======================
async def update_emotion(user_id, text):
    mood = "нейтральное"
    if "груст" in text:
        mood = "грусть"
    elif "рад" in text:
        mood = "радость"

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO emotions VALUES (?, ?)", (user_id, mood))
        await db.commit()

async def get_mood(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT mood FROM emotions WHERE user_id=? ORDER BY rowid DESC LIMIT 1",
            (user_id,)
        )
        row = await cur.fetchone()
        return row[0] if row else "нейтральное"

# ======================
# 💪 ДАВЛЕНИЕ
# ======================
def pressure_text(streak, missed=False):
    if missed:
        return "Ты вчера пропустил. Это откат. Делаешь сегодня или сливаешь?"

    if streak >= 7:
        return "Ты уже в системе. Не ломай её."
    if streak >= 3:
        return "Неплохо. Но расслабишься — откатишься."

    return "Начал — доведи."

# ======================
# 🧠 ПОВЕДЕНКА
# ======================
async def behavior_analyze(user_id, text):
    mood = await get_mood(user_id)

    if "устал" in text:
        return "Ты часто устаёшь. Добавим привычку: сон до 23:00?"

    if mood == "грусть":
        return "Окей. Сегодня без давления. Но не пропадай."

    return None

# ======================
# AI
# ======================
async def ask_ai(user_id, text):
    context = await get_memory(user_id)
    mood = await get_mood(user_id)

    messages = [
        {"role": "system", "content": f"Настроение: {mood}. Будь немного давящим."}
    ] + context + [{"role": "user", "content": text}]

    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
                json={"model": "openai/gpt-4o-mini", "messages": messages},
                timeout=15
            )
            return r.json()["choices"][0]["message"]["content"]
    except:
        return "❌ AI недоступен"

# ======================
# RETENTION
# ======================
FACTS = [
    "Факт: мозг потребляет 20% энергии тела",
    "Факт: привычки формируются за 21-30 дней"
]

QUOTES = [
    "Дисциплина — это выбор",
    "Ты либо действуешь, либо ищешь оправдания"
]

async def retention_ping():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id FROM users")
        users = await cur.fetchall()

    for u in users:
        try:
            await bot.send_message(u[0], "Ты пропал. Возвращайся.")
            await bot.send_message(u[0], random.choice(FACTS))
            await bot.send_message(u[0], random.choice(QUOTES))
        except:
            pass

# ======================
# ХЕНДЛЕРЫ
# ======================
@dp.message(CommandStart())
async def start(message: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users(user_id, name) VALUES (?, ?)",
            (message.from_user.id, message.from_user.first_name)
        )
        await db.commit()

    await message.answer("Привет 👋")

@dp.message()
async def chat(message: Message):
    text = message.text

    await save_memory(message.from_user.id, "user", text)
    await update_emotion(message.from_user.id, text)

    behavior = await behavior_analyze(message.from_user.id, text)
    answer = await ask_ai(message.from_user.id, text)

    if behavior:
        await message.answer(behavior)

    await message.answer(answer)

# ======================
# MAIN
# ======================
async def main():
    await init_db()
    await acquire_lock()

    if IS_MAIN:
        scheduler.start()
        scheduler.add_job(retention_ping, "interval", hours=12)
        asyncio.create_task(keep_lock_alive())

    logging.info(f"🚀 БОТ ЗАПУЩЕН | IS_MAIN={IS_MAIN}")

    if IS_MAIN:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    else:
        while True:
            await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())