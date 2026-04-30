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
    if os.getenv("RAILWAY_REPLICA_ID") not in (None, "0"):
        print("⛔ Второй инстанс — выходим")
        exit()

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
# AI + fallback
# ======================
async def ask_ai(user_id, text, user):
    context = await get_memory(user_id)
    mood = await get_mood(user_id)

    system_prompt = f"""
Ты ассистент.
Имя: {user['name']}
Стиль: {user['style']}
Настроение пользователя: {mood}

Всегда отвечай на русском.
"""

    messages = [{"role": "system", "content": system_prompt}] + context + [
        {"role": "user", "content": text}
    ]

    # OpenRouter
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
                json={"model": "openai/gpt-4o-mini", "messages": messages},
                timeout=15
            )
            return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print("❌ OpenRouter:", e)

    # Qwen fallback
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
                headers={"Authorization": f"Bearer {QWEN_API_KEY}"},
                json={"input": {"messages": messages}},
                timeout=15
            )
            return r.json()["output"]["text"]
    except Exception as e:
        print("❌ Qwen:", e)

    return "❌ AI недоступен"

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
# ЗАМЕТКИ CRUD
# ======================
@dp.callback_query(F.data == "notes")
async def show_notes(call: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT id, text FROM notes WHERE user_id=?", (call.from_user.id,))
        rows = await cur.fetchall()

    if not rows:
        await call.message.answer("Нет заметок")
        return

    for n in rows:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Удалить", callback_data=f"del_note_{n[0]}")]
        ])
        await call.message.answer(n[1], reply_markup=kb)

@dp.callback_query(F.data.startswith("del_note_"))
async def delete_note(call: CallbackQuery):
    note_id = int(call.data.split("_")[2])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM notes WHERE id=?", (note_id,))
        await db.commit()
    await call.message.edit_text("Удалено")

# ======================
# НАПОМИНАНИЯ CRUD
# ======================
@dp.callback_query(F.data == "reminders")
async def show_reminders(call: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT id, text, remind_at FROM reminders WHERE user_id=?", (call.from_user.id,))
        rows = await cur.fetchall()

    for r in rows:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Удалить", callback_data=f"del_rem_{r[0]}")]
        ])
        await call.message.answer(f"{r[1]} ({r[2]})", reply_markup=kb)

@dp.callback_query(F.data.startswith("del_rem_"))
async def delete_rem(call: CallbackQuery):
    rid = int(call.data.split("_")[2])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM reminders WHERE id=?", (rid,))
        await db.commit()
    await call.message.edit_text("Удалено")

# ======================
# ПРИВЫЧКИ CRUD
# ======================
@dp.callback_query(F.data == "habits")
async def show_habits(call: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT id, name, done FROM habits WHERE user_id=?", (call.from_user.id,))
        rows = await cur.fetchall()

    for h in rows:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✔️ Сделал", callback_data=f"done_{h[0]}")]
        ])
        await call.message.answer(f"{h[1]} | {'✔' if h[2] else '❌'}", reply_markup=kb)

@dp.callback_query(F.data.startswith("done_"))
async def done_habit(call: CallbackQuery):
    hid = int(call.data.split("_")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE habits SET done=1 WHERE id=?", (hid,))
        await db.commit()
    await call.message.edit_text("Готово ✔️")

# ======================
# ГОЛОС (реальный)
# ======================
@dp.message(F.voice)
async def voice_handler(message: Message):
    file = await bot.get_file(message.voice.file_id)
    url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"

    async with httpx.AsyncClient() as client:
        audio = await client.get(url)

        r = await client.post(
            "https://openrouter.ai/api/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
            files={"file": ("voice.ogg", audio.content)}
        )
        text = r.json().get("text", "")

    await message.answer(f"🎤 {text}")

# ======================
# ЧАТ
# ======================
@dp.message()
async def chat(message: Message):
    try:
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

        await message.answer(answer, reply_markup=menu())

    except Exception as e:
        print("❌ CHAT ERROR:", e)
        await message.answer("Ошибка, попробуй ещё раз")

# ======================
# START
# ======================
@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await message.answer("Привет 👋", reply_markup=menu())

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