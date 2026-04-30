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

load_dotenv()

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
QWEN_API_KEY = os.getenv("QWEN_API_KEY")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

DB_PATH = "bot.db"


# ======================
# БАЗА
# ======================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            age TEXT,
            gender TEXT,
            style TEXT
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS notes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            text TEXT,
            category TEXT
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS memory(
            user_id INTEGER,
            role TEXT,
            content TEXT
        )
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
# РАСКЛАДКА
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
        await db.execute(
            "INSERT INTO memory VALUES (?, ?, ?)",
            (user_id, role, content)
        )
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
- если человек жалуется → режим психоанализа (макс эмпатия)
- если про здоровье → режим врача (четко и без лишней воды)
"""

    messages = [{"role": "system", "content": system_prompt}] + context + [
        {"role": "user", "content": text}
    ]

    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
                json={
                    "model": "openai/gpt-4o-mini",
                    "messages": messages
                }
            )
            data = r.json()
            return data["choices"][0]["message"]["content"]

    except:
        return "Ошибка ИИ"


# ======================
# РЕГИСТРАЦИЯ
# ======================
async def user_exists(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,))
        return await cursor.fetchone()


@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    if not await user_exists(message.from_user.id):
        await message.answer("Привет! Как тебя зовут?")
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

    await call.message.answer("Готово! Можешь писать 🙂")
    await state.clear()


# ======================
# НАПОМИНАНИЯ
# ======================
@dp.message(F.text.lower().contains("напомни"))
async def reminder_start(message: Message, state: FSMContext):
    await state.set_state(ReminderFSM.text)
    await state.update_data(text=message.text)
    await message.answer("Когда напомнить?")


@dp.message(ReminderFSM.text)
async def reminder_time(message: Message, state: FSMContext):
    data = await state.get_data()

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO notes(user_id, text, category) VALUES (?, ?, ?)",
            (message.from_user.id, data["text"], "напоминания")
        )
        await db.commit()

    await message.answer("Напоминание создано")
    await state.clear()


# ======================
# ЗАМЕТКИ
# ======================
@dp.message(F.text.lower().contains("запомни") | F.text.lower().contains("заметку"))
async def add_note(message: Message):
    text = message.text

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO notes(user_id, text, category) VALUES (?, ?, ?)",
            (message.from_user.id, text, "наблюдения")
        )
        await db.commit()

    await message.answer("Сохранил")


@dp.message(F.text.lower().contains("покажи"))
async def show_notes(message: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id, text FROM notes WHERE user_id=?",
            (message.from_user.id,)
        )
        notes = await cursor.fetchall()

    if not notes:
        await message.answer("Пусто")
        return

    for n in notes:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Удалить", callback_data=f"del_{n[0]}")]
        ])
        await message.answer(n[1], reply_markup=kb)


@dp.callback_query(F.data.startswith("del_"))
async def delete_note(call: CallbackQuery):
    note_id = int(call.data.split("_")[1])

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM notes WHERE id=?", (note_id,))
        await db.commit()

    await call.message.edit_text("Удалено")


# ======================
# ОСНОВНОЙ ЧАТ
# ======================
@dp.message()
async def chat(message: Message):
    text = fix_layout(message.text)

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT * FROM users WHERE user_id=?", (message.from_user.id,))
        user = await cursor.fetchone()

    if not user:
        await message.answer("Напиши /start")
        return

    user_dict = {
        "name": user[1],
        "style": user[4]
    }

    await save_memory(message.from_user.id, "user", text)

    answer = await ask_ai(message.from_user.id, text, user_dict)

    await save_memory(message.from_user.id, "assistant", answer)

    await message.answer(answer)


# ======================
# ЗАПУСК
# ======================
async def main():
    await init_db()
    logging.info("🚀 БОТ ЗАПУЩЕН")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())