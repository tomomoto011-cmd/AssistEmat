import asyncio
import logging
import os
import re
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
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
# 🛑 АНТИ-ДУБЛЬ (НОРМАЛЬНЫЙ)
# ======================
IS_MAIN = True

if os.getenv("RAILWAY_ENVIRONMENT") == "production":
    replica = os.getenv("RAILWAY_REPLICA_ID")
    if replica and replica != "0":
        IS_MAIN = False
        logging.warning(f"⛔ Реплика {replica} без polling")

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

        CREATE TABLE IF NOT EXISTS notes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            text TEXT,
            category TEXT
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
# 🧠 НАТУРАЛЬНЫЙ ПАРСЕР ВРЕМЕНИ
# ======================
def parse_time(text: str):
    text = text.lower()
    now = datetime.now()

    # через X минут/часов
    minutes = re.search(r'через (\d+) минут', text)
    hours = re.search(r'через (\d+) час', text)

    if minutes:
        return now + timedelta(minutes=int(minutes.group(1)))

    if hours:
        return now + timedelta(hours=int(hours.group(1)))

    # завтра
    if "завтра" in text:
        base = now + timedelta(days=1)
        if "вечер" in text:
            return base.replace(hour=19, minute=0)
        if "утро" in text:
            return base.replace(hour=9, minute=0)

        match = re.search(r'(\d{1,2}):(\d{2})', text)
        if match:
            return base.replace(hour=int(match.group(1)), minute=int(match.group(2)))

        return base.replace(hour=9, minute=0)

    # дни недели
    weekdays = {
        "понедельник": 0, "вторник": 1, "среду": 2,
        "четверг": 3, "пятницу": 4, "субботу": 5, "воскресенье": 6
    }

    for day, idx in weekdays.items():
        if day in text:
            days_ahead = (idx - now.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7

            base = now + timedelta(days=days_ahead)

            match = re.search(r'(\d{1,2}):(\d{2})', text)
            if match:
                return base.replace(hour=int(match.group(1)), minute=int(match.group(2)))

            return base.replace(hour=10, minute=0)

    # fallback ISO
    try:
        return datetime.fromisoformat(text)
    except:
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
# 💪 ПОВЕДЕНКА / STREAK
# ======================
def habit_feedback(streak):
    if streak == 1:
        return "Начало положено 💪"
    if streak == 3:
        return "Уже формируется привычка 🔥"
    if streak == 7:
        return "Ты стабилен. Это уже система ⚙️"
    if streak >= 30:
        return "Ты машина. Это уровень 🧠"
    return f"Серия: {streak}"

# ======================
# AI
# ======================
async def ask_ai(user_id, text):
    context = await get_memory(user_id)
    mood = await get_mood(user_id)

    messages = [
        {"role": "system", "content": f"Настроение: {mood}. Добавляй мотивацию если уместно."}
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
# НАПОМИНАНИЯ
# ======================
async def send_reminder(user_id, text):
    await bot.send_message(user_id, f"⏰ {text}")

async def load_reminders():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id, text, remind_at FROM reminders")
        rows = await cur.fetchall()

    for r in rows:
        dt = datetime.fromisoformat(r[2])
        scheduler.add_job(send_reminder, "date", run_date=dt, args=[r[0], r[1]])

@dp.message(F.text.lower().contains("напомни"))
async def reminder_start(message: Message, state: FSMContext):
    await state.set_state(ReminderFSM.text)
    await state.update_data(text=message.text)
    await message.answer("Когда? (например: завтра вечером, через 2 часа)")

@dp.message(ReminderFSM.text)
async def reminder_time(message: Message, state: FSMContext):
    data = await state.get_data()
    dt = parse_time(message.text)

    if not dt:
        await message.answer("Не понял время")
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO reminders(user_id, text, remind_at) VALUES (?, ?, ?)",
            (message.from_user.id, data["text"], dt.isoformat())
        )
        await db.commit()

    scheduler.add_job(send_reminder, "date", run_date=dt,
                      args=[message.from_user.id, data["text"]])

    await message.answer("⏰ Напоминание поставлено")
    await state.clear()

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

    await call.message.edit_text(habit_feedback(streak))

# ======================
# MAIN
# ======================
async def main():
    await init_db()

    if IS_MAIN:
        scheduler.start()
        await load_reminders()

    logging.info("🚀 БОТ ЗАПУЩЕН")

    if IS_MAIN:
        await dp.start_polling(bot)
    else:
        while True:
            await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())