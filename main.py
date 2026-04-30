import os
import asyncio
import logging
import json
import re
from datetime import datetime, timedelta

import asyncpg
import requests

from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

# ================= CONFIG =================

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")
QWEN_KEY = os.getenv("QWEN_API_KEY")
DB_URL = os.getenv("DATABASE_URL")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ================= DB =================

pool = None

async def init_db():
    global pool
    pool = await asyncpg.create_pool(DB_URL)

    async with pool.acquire() as conn:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id BIGINT PRIMARY KEY,
            name TEXT,
            age INT,
            gender TEXT,
            style TEXT
        )
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS notes(
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            text TEXT,
            category TEXT
        )
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS reminders(
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            text TEXT,
            remind_at TIMESTAMP
        )
        """)

# ================= FSM =================

class ReminderFSM(StatesGroup):
    waiting_time = State()

class RegisterFSM(StatesGroup):
    name = State()
    age = State()
    gender = State()
    style = State()

# ================= MEMORY =================

user_memory = {}

def save_memory(user_id, role, content):
    history = user_memory.get(user_id, [])
    history.append({"role": role, "content": content})
    user_memory[user_id] = history[-20:]

# ================= UTILS =================

def fix_layout(text):
    layout_map = dict(zip(
        "qwertyuiop[]asdfghjkl;'zxcvbnm,.",
        "йцукенгшщзхъфывапролджэячсмитьбю"
    ))
    return "".join(layout_map.get(c, c) for c in text)

def detect_mode(text):
    text = text.lower()
    if any(x in text for x in ["плохо", "грустно", "обидел", "одиноко"]):
        return "psy"
    if any(x in text for x in ["болит", "температура", "симптом"]):
        return "doc"
    return "normal"

def build_prompt(mode):
    if mode == "psy":
        return "Ты эмпатичный психолог. Поддерживай, задавай мягкие вопросы."
    if mode == "doc":
        return "Ты врач. Коротко, по делу. Без лекарств."
    return "Ты дружелюбный ассистент. Отвечай по-русски."

# ================= AI =================

def ask_openrouter(messages):
    try:
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_KEY}"},
            json={
                "model": "qwen/qwen-2.5-7b-instruct",
                "messages": messages
            },
            timeout=15
        )
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"]
    except:
        pass
    return None

def ask_qwen(messages):
    try:
        r = requests.post(
            "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
            headers={
                "Authorization": f"Bearer {QWEN_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "qwen-turbo",
                "input": {"messages": messages}
            },
            timeout=15
        )
        if r.status_code == 200:
            return r.json()["output"]["text"]
    except:
        pass
    return None

# ================= REMINDERS =================

async def scheduler():
    while True:
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
            SELECT * FROM reminders
            WHERE remind_at <= NOW()
            """)
            for r in rows:
                await bot.send_message(r["user_id"], f"⏰ Напоминание: {r['text']}")
                await conn.execute("DELETE FROM reminders WHERE id=$1", r["id"])
        await asyncio.sleep(30)

# ================= HANDLERS =================

@dp.message(commands=["start"])
async def start(msg: types.Message, state: FSMContext):
    async with pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE id=$1", msg.from_user.id)

    if not user:
        await msg.answer("Как тебя зовут?")
        await state.set_state(RegisterFSM.name)
    else:
        await msg.answer(f"Привет, {user['name']} 👋")

@dp.message(RegisterFSM.name)
async def reg_name(msg: types.Message, state: FSMContext):
    await state.update_data(name=msg.text)
    await msg.answer("Сколько тебе лет?")
    await state.set_state(RegisterFSM.age)

@dp.message(RegisterFSM.age)
async def reg_age(msg: types.Message, state: FSMContext):
    await state.update_data(age=int(msg.text))
    await msg.answer("Пол?")
    await state.set_state(RegisterFSM.gender)

@dp.message(RegisterFSM.gender)
async def reg_gender(msg: types.Message, state: FSMContext):
    await state.update_data(gender=msg.text)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Друг", callback_data="style_friend")],
        [InlineKeyboardButton(text="Советник", callback_data="style_adv")]
    ])

    await msg.answer("Выбери стиль общения:", reply_markup=kb)
    await state.set_state(RegisterFSM.style)

@dp.callback_query(lambda c: c.data.startswith("style_"))
async def reg_style(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()

    async with pool.acquire() as conn:
        await conn.execute("""
        INSERT INTO users VALUES($1,$2,$3,$4,$5)
        """, cb.from_user.id, data["name"], data["age"], data["gender"], cb.data)

    await cb.message.answer("Готово 👍")
    await state.clear()

# ================= NOTES =================

@dp.message(lambda m: "запомни" in m.text.lower())
async def save_note(msg: types.Message):
    text = msg.text.replace("запомни", "").strip()

    category = "наблюдения"
    if "купить" in text:
        category = "покупки"

    async with pool.acquire() as conn:
        await conn.execute("""
        INSERT INTO notes(user_id,text,category)
        VALUES($1,$2,$3)
        """, msg.from_user.id, text, category)

    await msg.answer(f"✅ Сохранено в {category}")

@dp.message(lambda m: "покажи" in m.text.lower())
async def show_notes(msg: types.Message):
    async with pool.acquire() as conn:
        notes = await conn.fetch("""
        SELECT * FROM notes WHERE user_id=$1
        """, msg.from_user.id)

    for n in notes:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ удалить", callback_data=f"del_{n['id']}")
        ]])
        await msg.answer(n["text"], reply_markup=kb)

@dp.callback_query(lambda c: c.data.startswith("del_"))
async def delete_note(cb: types.CallbackQuery):
    note_id = int(cb.data.split("_")[1])

    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM notes WHERE id=$1", note_id)

    await cb.message.edit_text("Удалено")

# ================= REMINDER =================

@dp.message(lambda m: "напомни" in m.text.lower())
async def reminder_start(msg: types.Message, state: FSMContext):
    text = msg.text.replace("напомни", "").strip()

    await state.update_data(text=text)
    await msg.answer("Когда напомнить?")
    await state.set_state(ReminderFSM.waiting_time)

@dp.message(ReminderFSM.waiting_time)
async def reminder_time(msg: types.Message, state: FSMContext):
    data = await state.get_data()

    # очень простая логика
    remind_at = datetime.now() + timedelta(minutes=1)

    async with pool.acquire() as conn:
        await conn.execute("""
        INSERT INTO reminders(user_id,text,remind_at)
        VALUES($1,$2,$3)
        """, msg.from_user.id, data["text"], remind_at)

    await msg.answer("⏰ Напоминание создано (пока +1 минута)")
    await state.clear()

# ================= CHAT =================

@dp.message()
async def chat(msg: types.Message):
    text = fix_layout(msg.text)

    mode = detect_mode(text)
    system = build_prompt(mode)

    history = user_memory.get(msg.from_user.id, [])

    messages = [{"role": "system", "content": system}] + history
    messages.append({"role": "user", "content": text})

    reply = ask_openrouter(messages)

    if not reply:
        reply = ask_qwen(messages)

    if not reply:
        reply = "Я сейчас немного туплю 😅"

    save_memory(msg.from_user.id, "user", text)
    save_memory(msg.from_user.id, "assistant", reply)

    await msg.answer(reply)

# ================= MAIN =================

async def main():
    logging.info("🚀 БОТ ЗАПУЩЕН")

    # анти-дубль
    if os.getenv("RAILWAY_ENVIRONMENT") == "production":
        if os.getenv("RAILWAY_REPLICA_ID") not in (None, "0"):
            logging.warning("⛔ Второй инстанс — выходим")
            return

    await init_db()

    asyncio.create_task(scheduler())

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())