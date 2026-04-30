import asyncio
import logging
import os
import re
import random
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

import aiosqlite
import httpx
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler

load_dotenv()
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

DB_PATH = "bot.db"
scheduler = AsyncIOScheduler()

# ======================
# 🛑 АНТИ-ДУБЛЬ
# ======================
IS_MAIN = True

if os.getenv("RAILWAY_ENVIRONMENT") == "production":
    replica = os.getenv("RAILWAY_REPLICA_ID")
    if replica and replica != "0":
        IS_MAIN = False
        logging.warning(f"⛔ Реплика {replica} без polling")

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

# ======================
# FSM
# ======================
class ReminderFSM(StatesGroup):
    text = State()
    time = State()

# ======================
# УТИЛЫ
# ======================
def fix_layout(text):
    if not text:
        return ""
    layout_map = str.maketrans(
        "qwertyuiop[]asdfghjkl;'zxcvbnm,.",
        "йцукенгшщзхъфывапролджэячсмитьбю"
    )
    return text.translate(layout_map)

# ======================
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
        return "Не давлю. Сделай хотя бы минимум сегодня."

    return None

# ======================
# AI
# ======================
async def ask_ai(user_id, text):
    context = await get_memory(user_id)
    mood = await get_mood(user_id)

    messages = [
        {"role": "system", "content": f"Настроение: {mood}. Будь чуть давящим и мотивирующим."}
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
# ПРИВЫЧКИ
# ======================
@dp.callback_query(F.data.startswith("done_"))
async def done_habit(call: CallbackQuery):
    hid = int(call.data.split("_")[1])
    now = datetime.now().date()

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT streak, last_done FROM habits WHERE id=?", (hid,))
        row = await cur.fetchone()

        streak, last_done = row
        last_done = datetime.fromisoformat(last_done).date() if last_done else None

        missed = False
        if last_done and last_done < now - timedelta(days=1):
            missed = True

        if last_done == now:
            await call.message.answer("Уже отмечено")
            return

        if last_done == now - timedelta(days=1):
            streak += 1
        else:
            streak = 1

        await db.execute(
            "UPDATE habits SET streak=?, last_done=? WHERE id=?",
            (streak, now.isoformat(), hid)
        )
        await db.commit()

    await call.message.edit_text(pressure_text(streak, missed))

# ======================
# ЧАТ
# ======================
@dp.message()
async def chat(message: Message):
    try:
        text = fix_layout(message.text)

        await save_memory(message.from_user.id, "user", text)
        await update_emotion(message.from_user.id, text)

        behavior = await behavior_analyze(message.from_user.id, text)

        answer = await ask_ai(message.from_user.id, text)

        await save_memory(message.from_user.id, "assistant", answer)

        if behavior:
            await message.answer(behavior)

        await message.answer(answer)

    except Exception as e:
        print("❌ CHAT ERROR:", e)
        await message.answer("Ошибка")

# ======================
# START
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

# ======================
# MAIN
# ======================
async def main():
    await init_db()

    if IS_MAIN:
        scheduler.start()
        scheduler.add_job(retention_ping, "interval", hours=12)

    logging.info(f"🚀 БОТ ЗАПУЩЕН | IS_MAIN={IS_MAIN}")

    try:
        if IS_MAIN:
            await bot.delete_webhook(drop_pending_updates=True)
            await dp.start_polling(bot)
        else:
            while True:
                await asyncio.sleep(3600)

    except Exception as e:
        logging.error(f"❌ MAIN CRASH: {e}")
        while True:
            await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())