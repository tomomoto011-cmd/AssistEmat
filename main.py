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

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

DB_PATH = "bot.db"
scheduler = AsyncIOScheduler()

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
    age = State()
    gender = State()
    style = State()

class ReminderFSM(StatesGroup):
    text = State()
    time = State()

# ======================
# УТИЛЫ
# ======================
def fix_layout(text):
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

# ======================
# AI
# ======================
async def ask_ai(user_id, text, user):
    context = await get_memory(user_id)

    system_prompt = f"""
Ты — персональный ассистент.

Имя пользователя: {user['name']}
Стиль: {user['style']}

Правила:
- всегда отвечай на русском
- обращайся по имени
- если человек жалуется → эмпатия
- если здоровье → по делу
"""

    messages = [{"role": "system", "content": system_prompt}] + context + [
        {"role": "user", "content": text}
    ]

    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
            json={"model": "openai/gpt-4o-mini", "messages": messages}
        )
        data = r.json()
        return data["choices"][0]["message"]["content"]

# ======================
# НАПОМИНАНИЯ
# ======================
async def send_reminder(user_id, text):
    await bot.send_message(user_id, f"⏰ Напоминание: {text}")

async def load_reminders():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT user_id, text, remind_at FROM reminders")
        rows = await cursor.fetchall()

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
        remind_at = datetime.fromisoformat(message.text)
    except:
        await message.answer("Формат: 2026-05-01 18:00")
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO reminders(user_id, text, remind_at) VALUES (?, ?, ?)",
            (message.from_user.id, data["text"], remind_at.isoformat())
        )
        await db.commit()

    scheduler.add_job(send_reminder, "date", run_date=remind_at,
                      args=[message.from_user.id, data["text"]])

    await message.answer("Напоминание поставлено ⏰")
    await state.clear()

# ======================
# ПРИВЫЧКИ
# ======================
@dp.message(F.text.lower().contains("привычку"))
async def add_habit(message: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO habits(user_id, name) VALUES (?, ?)",
                         (message.from_user.id, message.text))
        await db.commit()
    await message.answer("Привычка добавлена 💪")

@dp.message(F.text.lower().contains("сделал"))
async def done_habit(message: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE habits SET done=1 WHERE user_id=?",
                         (message.from_user.id,))
        await db.commit()
    await message.answer("Отметил ✔️")

# ======================
# ГОЛОС
# ======================
@dp.message(F.voice)
async def voice_handler(message: Message):
    await message.answer("🎤 Голос получил (пока базово)")
    text = "распознанный текст"
    answer = await ask_ai(message.from_user.id, text, {"name": "друг", "style": "friend"})
    await message.answer(answer)

# ======================
# РЕГИСТРАЦИЯ
# ======================
async def user_exists(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,))
        return await cur.fetchone()

@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    if not await user_exists(message.from_user.id):
        await message.answer("Как тебя зовут?")
        await state.set_state(Register.name)
    else:
        await message.answer("С возвращением!")

@dp.message(Register.name)
async def reg_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Возраст?")
    await state.set_state(Register.age)

@dp.message(Register.age)
async def reg_age(message: Message, state: FSMContext):
    await state.update_data(age=message.text)
    await message.answer("Пол?")
    await state.set_state(Register.gender)

@dp.message(Register.gender)
async def reg_gender(message: Message, state: FSMContext):
    await state.update_data(gender=message.text)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Друг", callback_data="style_friend")],
        [InlineKeyboardButton(text="Советник", callback_data="style_advisor")]
    ])
    await message.answer("Стиль общения:", reply_markup=kb)

@dp.callback_query(F.data.startswith("style_"))
async def reg_style(call: CallbackQuery, state: FSMContext):
    style = call.data.replace("style_", "")
    data = await state.get_data()

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO users VALUES (?, ?, ?, ?, ?)",
            (call.from_user.id, data["name"], data["age"], data["gender"], style)
        )
        await db.commit()

    await call.message.answer("Готово!")
    await state.clear()

# ======================
# ОСНОВНОЙ ЧАТ
# ======================
@dp.message()
async def chat(message: Message):
    text = fix_layout(message.text)

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT * FROM users WHERE user_id=?", (message.from_user.id,))
        user = await cur.fetchone()

    if not user:
        await message.answer("Напиши /start")
        return

    user_dict = {"name": user[1], "style": user[4]}

    await update_emotion(message.from_user.id, text)
    await save_memory(message.from_user.id, "user", text)

    answer = await ask_ai(message.from_user.id, text, user_dict)

    await save_memory(message.from_user.id, "assistant", answer)

    await message.answer(answer)

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