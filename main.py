import os
import asyncio
import logging
from datetime import datetime, timedelta

import httpx
import asyncpg
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ---------------- ЛОГИ ----------------
logging.basicConfig(level=logging.INFO)

# ---------------- ENV ----------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
QWEN_API_KEY = os.getenv("QWEN_API_KEY")

# ---------------- АНТИ-ДУБЛЬ ----------------
if os.getenv("RAILWAY_ENVIRONMENT") == "production":
    if os.getenv("RAILWAY_REPLICA_ID") not in (None, "0"):
        logging.warning("⛔ Второй инстанс — выходим")
        exit()

# ---------------- INIT ----------------
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
scheduler = AsyncIOScheduler()

# ---------------- FSM ----------------
class Register(StatesGroup):
    name = State()
    age = State()
    gender = State()
    style = State()

class ReminderFSM(StatesGroup):
    text = State()
    time = State()

# ---------------- БД ----------------
db = None

async def init_db():
    global db
    db = await asyncpg.create_pool(DATABASE_URL)

    async with db.acquire() as conn:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            name TEXT,
            age TEXT,
            gender TEXT,
            style TEXT
        )
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            text TEXT,
            category TEXT
        )
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            text TEXT,
            remind_at TIMESTAMP
        )
        """)

# ---------------- OPENROUTER ----------------
async def ask_ai(prompt):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }

    data = {
        "model": "qwen/qwen-2.5-7b-instruct",
        "messages": [
            {"role": "system", "content": "Отвечай всегда на русском языке."},
            {"role": "user", "content": prompt}
        ]
    }

    async with httpx.AsyncClient() as client:
        r = await client.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=data)
        return r.json()["choices"][0]["message"]["content"]

# ---------------- УТИЛЫ ----------------
def fix_layout(text):
    layout = dict(zip(
        "qwertyuiop[]asdfghjkl;'zxcvbnm,.",
        "йцукенгшщзхъфывапролджэячсмитьбю"
    ))
    return "".join(layout.get(c, c) for c in text.lower())

def detect_mode(text):
    text = text.lower()
    if any(w in text for w in ["боль", "температура", "болит"]):
        return "doctor"
    if any(w in text for w in ["обидел", "чувствую", "расстроен"]):
        return "psy"
    return "normal"

# ---------------- START ----------------
@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    user = await db.fetchrow("SELECT * FROM users WHERE user_id=$1", message.from_user.id)

    if user:
        await message.answer(f"С возвращением, {user['name']} 👋")
        return

    await message.answer("Привет! Как тебя зовут?")
    await state.set_state(Register.name)

# ---------------- РЕГИСТРАЦИЯ ----------------
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

    await message.answer("Стиль общения?", reply_markup=kb)

@dp.callback_query(F.data.startswith("style_"))
async def reg_style(call: CallbackQuery, state: FSMContext):
    style = call.data.split("_")[1]
    data = await state.get_data()

    async with db.acquire() as conn:
        await conn.execute("""
        INSERT INTO users (user_id, name, age, gender, style)
        VALUES ($1,$2,$3,$4,$5)
        """, call.from_user.id, data["name"], data["age"], data["gender"], style)

    await call.message.answer("Готово! Теперь можем общаться 🙂")
    await state.clear()

# ---------------- НАПОМИНАНИЯ ----------------
@dp.message(F.text.contains("напомни"))
async def reminder_start(message: Message, state: FSMContext):
    await state.update_data(text=message.text)
    await message.answer("Когда напомнить?")
    await state.set_state(ReminderFSM.time)

@dp.message(ReminderFSM.time)
async def reminder_set(message: Message, state: FSMContext):
    text = (await state.get_data())["text"]

    remind_at = datetime.now() + timedelta(minutes=1)

    async with db.acquire() as conn:
        rid = await conn.fetchval("""
        INSERT INTO reminders (user_id, text, remind_at)
        VALUES ($1,$2,$3) RETURNING id
        """, message.from_user.id, text, remind_at)

    scheduler.add_job(send_reminder, "date", run_date=remind_at,
                      args=[message.chat.id, text])

    await message.answer("Напоминание создано ✅")
    await state.clear()

async def send_reminder(chat_id, text):
    await bot.send_message(chat_id, f"⏰ Напоминание: {text}")

# ---------------- ЗАМЕТКИ ----------------
@dp.message(F.text.contains("запомни") | F.text.contains("запиши"))
async def save_note(message: Message):
    text = message.text

    async with db.acquire() as conn:
        await conn.execute("""
        INSERT INTO notes (user_id, text, category)
        VALUES ($1,$2,$3)
        """, message.from_user.id, text, "общие")

    await message.answer("Заметка сохранена 📌")

@dp.message(F.text.contains("покажи заметки"))
async def show_notes(message: Message):
    async with db.acquire() as conn:
        notes = await conn.fetch("SELECT * FROM notes WHERE user_id=$1", message.from_user.id)

    if not notes:
        await message.answer("Нет заметок")
        return

    for n in notes:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Удалить", callback_data=f"del_{n['id']}")]
        ])
        await message.answer(n["text"], reply_markup=kb)

@dp.callback_query(F.data.startswith("del_"))
async def delete_note(call: CallbackQuery):
    nid = int(call.data.split("_")[1])

    async with db.acquire() as conn:
        await conn.execute("DELETE FROM notes WHERE id=$1", nid)

    await call.message.edit_text("Удалено ❌")

# ---------------- AI ----------------
@dp.message()
async def ai_handler(message: Message):
    text = fix_layout(message.text)

    mode = detect_mode(text)

    if mode == "psy":
        prompt = f"Отвечай максимально эмпатично: {text}"
    elif mode == "doctor":
        prompt = f"Отвечай как врач, сухо и по делу: {text}"
    else:
        prompt = text

    answer = await ask_ai(prompt)
    await message.answer(answer)

# ---------------- MAIN ----------------
async def main():
    await init_db()
    scheduler.start()

    logging.info("🚀 БОТ ЗАПУЩЕН")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())