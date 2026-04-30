import asyncio
import logging
import os
import re
import random
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

import aiosqlite
import httpx
import redis.asyncio as redis

from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler

load_dotenv()
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
REDIS_URL = os.getenv("REDIS_URL")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

DB_PATH = "bot.db"
scheduler = AsyncIOScheduler()

# ======================
# 🔥 REDIS LOCK
# ======================
IS_MAIN = False
redis_client = None

async def acquire_lock():
    global IS_MAIN, redis_client

    if not REDIS_URL:
        IS_MAIN = True
        return

    redis_client = redis.from_url(REDIS_URL)

    lock = await redis_client.set("bot_lock", "1", ex=60, nx=True)

    if lock:
        IS_MAIN = True
        logging.info("✅ MAIN INSTANCE")
    else:
        logging.warning("⛔ SECONDARY INSTANCE")

async def keep_lock_alive():
    while True:
        if IS_MAIN and redis_client:
            await redis_client.expire("bot_lock", 60)
        await asyncio.sleep(30)

# ======================
# 🛑 АНТИ-ДУБЛЬ
# ======================
LAST_UPDATE_ID = 0

@dp.update.outer_middleware()
async def anti_duplicate(handler, event, data):
    global LAST_UPDATE_ID
    upd = data.get("event_update")

    if upd and hasattr(upd, "update_id"):
        if upd.update_id <= LAST_UPDATE_ID:
            return
        LAST_UPDATE_ID = upd.update_id

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

        CREATE TABLE IF NOT EXISTS reminders(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            text TEXT,
            remind_at TEXT
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

# ======================
# FSM
# ======================
class ReminderFSM(StatesGroup):
    text = State()
    time = State()

# ======================
# TIME PARSER
# ======================
def parse_time(text):
    text = text.lower()
    now = datetime.now()

    if "вечером" in text:
        return now.replace(hour=19, minute=0)

    if "после работы" in text:
        return now.replace(hour=18, minute=30)

    if "на выходных" in text:
        days = (5 - now.weekday()) % 7
        return (now + timedelta(days=days)).replace(hour=12, minute=0)

    m = re.search(r'через (\d+) минут', text)
    h = re.search(r'через (\d+) час', text)

    if m:
        return now + timedelta(minutes=int(m.group(1)))
    if h:
        return now + timedelta(hours=int(h.group(1)))

    if "завтра" in text:
        return (now + timedelta(days=1)).replace(hour=9, minute=0)

    return None

# ======================
# MEMORY + EMOTION
# ======================
async def save_memory(uid, role, content):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO memory VALUES (?, ?, ?)", (uid, role, content))
        await db.commit()

async def get_memory(uid):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT role, content FROM memory WHERE user_id=? ORDER BY rowid DESC LIMIT 20",
            (uid,)
        )
        rows = await cur.fetchall()
        return [{"role": r[0], "content": r[1]} for r in reversed(rows)]

async def update_emotion(uid, text):
    mood = "нейтральное"
    if "груст" in text:
        mood = "грусть"
    elif "рад" in text:
        mood = "радость"

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO emotions VALUES (?, ?)", (uid, mood))
        await db.commit()

async def get_mood(uid):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT mood FROM emotions WHERE user_id=? ORDER BY rowid DESC LIMIT 1",
            (uid,)
        )
        row = await cur.fetchone()
        return row[0] if row else "нейтральное"

# ======================
# ДАВЛЕНИЕ + ANALYZE
# ======================
def pressure_text(streak, missed=False):
    if missed:
        return "Ты вчера пропустил. Это откат. Делаешь сегодня или сливаешь?"
    if streak >= 7:
        return "Ты уже в системе. Не ломай её."
    if streak >= 3:
        return "Неплохо. Но расслабишься — откатишься."
    return "Начал — доведи."

async def behavior_analyze(uid, text):
    mood = await get_mood(uid)

    if "устал" in text:
        return "Ты часто устаёшь. Добавим привычку: сон до 23:00?"

    if mood == "грусть":
        return "Окей. Сегодня без давления. Но не пропадай."

    return None

# ======================
# AI
# ======================
async def ask_ai(uid, text):
    ctx = await get_memory(uid)
    mood = await get_mood(uid)

    messages = [{"role": "system", "content": f"Настроение: {mood}. Будь давящим."}] + ctx + [{"role": "user", "content": text}]

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
        return "❌ AI ошибка"

# ======================
# REMINDERS
# ======================
async def send_reminder(uid, text):
    await bot.send_message(uid, f"⏰ {text}")

@dp.message(F.text.contains("напомни"))
async def reminder_start(msg: Message, state: FSMContext):
    await state.set_state(ReminderFSM.text)
    await state.update_data(text=msg.text)
    await msg.answer("Когда?")

@dp.message(ReminderFSM.text)
async def reminder_time(msg: Message, state: FSMContext):
    data = await state.get_data()
    dt = parse_time(msg.text)

    if not dt:
        await msg.answer("Не понял время")
        return

    scheduler.add_job(send_reminder, "date", run_date=dt, args=[msg.from_user.id, data["text"]])

    await msg.answer("Поставил ⏰")
    await state.clear()

# ======================
# HABITS
# ======================
@dp.callback_query(F.data.startswith("done_"))
async def done(call: CallbackQuery):
    hid = int(call.data.split("_")[1])
    now = datetime.now().date()

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT streak,last_done FROM habits WHERE id=?", (hid,))
        row = await cur.fetchone()

        streak, last = row
        last = datetime.fromisoformat(last).date() if last else None

        missed = last and last < now - timedelta(days=1)

        if last == now:
            await call.answer("Уже было")
            return

        streak = streak + 1 if last == now - timedelta(days=1) else 1

        await db.execute(
            "UPDATE habits SET streak=?, last_done=? WHERE id=?",
            (streak, now.isoformat(), hid)
        )
        await db.commit()

    await call.message.edit_text(pressure_text(streak, missed))

# ======================
# RETENTION
# ======================
async def retention():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id FROM users")
        users = await cur.fetchall()

    for u in users:
        try:
            await bot.send_message(u[0], "Ты пропал. Возвращайся.")
        except:
            pass

# ======================
# CHAT
# ======================
@dp.message()
async def chat(msg: Message):
    text = msg.text

    await save_memory(msg.from_user.id, "user", text)
    await update_emotion(msg.from_user.id, text)

    behavior = await behavior_analyze(msg.from_user.id, text)
    answer = await ask_ai(msg.from_user.id, text)

    if behavior:
        await msg.answer(behavior)

    await msg.answer(answer)

# ======================
# START
# ======================
@dp.message(CommandStart())
async def start(msg: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users VALUES (?, ?)",
            (msg.from_user.id, msg.from_user.first_name)
        )
        await db.commit()

    await msg.answer("Привет 👋")

# ======================
# MAIN
# ======================
async def main():
    await init_db()
    await acquire_lock()

    if IS_MAIN:
        scheduler.start()
        scheduler.add_job(retention, "interval", hours=12)
        asyncio.create_task(keep_lock_alive())

    if IS_MAIN:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    else:
        while True:
            await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())