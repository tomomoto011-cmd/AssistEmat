import asyncio
import logging
import os
from datetime import datetime

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
QWEN_API_KEY = os.getenv("QWEN_API_KEY")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

DB_PATH = "bot.db"
scheduler = AsyncIOScheduler()

# ======================
# 🛑 АНТИ-ДУБЛЬ
# ======================
if os.getenv("RAILWAY_ENVIRONMENT") == "production":
    replica = os.getenv("RAILWAY_REPLICA_ID")
    if replica and replica != "0":
        logging.warning(f"⛔ Реплика {replica} остановлена")
        import time
        while True:
            time.sleep(1000)

# ======================
# БАЗА
# ======================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            age TEXT,
            gender TEXT,
            style TEXT
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
            done INTEGER DEFAULT 0
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
class Register(StatesGroup):
    name = State()

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
# AI
# ======================
async def ask_ai(user_id, text, user):
    context = await get_memory(user_id)
    mood = await get_mood(user_id)

    system_prompt = f"""
Имя: {user['name']}
Стиль: {user['style']}
Настроение: {mood}

Отвечай на русском.
"""

    messages = [{"role": "system", "content": system_prompt}] + context + [
        {"role": "user", "content": text}
    ]

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
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
                    headers={"Authorization": f"Bearer {QWEN_API_KEY}"},
                    json={"input": {"messages": messages}},
                    timeout=15
                )
                return r.json()["output"]["text"]
        except:
            return "❌ AI недоступен"

# ======================
# НАПОМИНАНИЯ
# ======================
async def send_reminder(user_id, text):
    await bot.send_message(user_id, f"⏰ Напоминание: {text}")

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
    await message.answer("Когда? (пример: 2026-05-01 18:00)")

@dp.message(ReminderFSM.text)
async def reminder_time(message: Message, state: FSMContext):
    data = await state.get_data()
    try:
        dt = datetime.fromisoformat(message.text)
    except:
        await message.answer("Неверный формат")
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO reminders(user_id, text, remind_at) VALUES (?, ?, ?)",
            (message.from_user.id, data["text"], dt.isoformat())
        )
        await db.commit()

    scheduler.add_job(send_reminder, "date", run_date=dt,
                      args=[message.from_user.id, data["text"]])

    await message.answer("⏰ Готово")
    await state.clear()

# ======================
# ЗАМЕТКИ
# ======================
@dp.message(F.text.lower().contains("запомни"))
async def add_note(message: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO notes(user_id, text, category) VALUES (?, ?, ?)",
            (message.from_user.id, message.text, "общие")
        )
        await db.commit()

    await message.answer("📌 Сохранил")

# ======================
# ПРИВЫЧКИ
# ======================
@dp.message(F.text.lower().contains("привычка"))
async def add_habit(message: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO habits(user_id, name) VALUES (?, ?)",
            (message.from_user.id, message.text)
        )
        await db.commit()

    await message.answer("💪 Добавил привычку")

# ======================
# МЕНЮ
# ======================
def menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📌 Заметки", callback_data="notes")],
        [InlineKeyboardButton(text="⏰ Напоминания", callback_data="reminders")],
        [InlineKeyboardButton(text="💪 Привычки", callback_data="habits")]
    ])

# ======================
# СТАРТ
# ======================
@dp.message(CommandStart())
async def start(message: Message):
    await message.answer("Привет 👋", reply_markup=menu())

# ======================
# ЧАТ
# ======================
@dp.message()
async def chat(message: Message):
    try:
        text = fix_layout(message.text)

        await save_memory(message.from_user.id, "user", text)
        await update_emotion(message.from_user.id, text)

        answer = await ask_ai(
            message.from_user.id,
            text,
            {"name": "друг", "style": "friend"}
        )

        await save_memory(message.from_user.id, "assistant", answer)

        await message.answer(answer, reply_markup=menu())

    except Exception as e:
        print("❌ CHAT ERROR:", e)
        await message.answer("Ошибка")

# ======================
# MAIN
# ======================
async def main():
    await init_db()
    scheduler.start()
    await load_reminders()

    logging.info("🚀 БОТ ЗАПУЩЕН")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())