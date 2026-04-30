import asyncio
import logging
import os
import re
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage

import asyncpg
import httpx

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
QWEN_API_KEY = os.getenv("QWEN_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ================= DB =================

db = None

async def init_db():
    global db
    db = await asyncpg.create_pool(DATABASE_URL)

    async with db.acquire() as conn:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            name TEXT,
            age INT,
            gender TEXT,
            style TEXT
        );
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            text TEXT,
            category TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            text TEXT,
            remind_at TIMESTAMP
        );
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS memory (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            role TEXT,
            content TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)

# ================= FSM =================

class ReminderState(StatesGroup):
    waiting_time = State()

# ================= UTILS =================

def detect_intent(text: str):
    text = text.lower()

    if "напомни" in text:
        return "reminder"
    if "запиши" in text or "заметка" in text:
        return "note"
    if "покажи" in text:
        return "show"

    return "chat"

def detect_category(text):
    if "куп" in text:
        return "покупки"
    if "наблюд" in text:
        return "наблюдения"
    return "общие"

def detect_mode(text):
    text = text.lower()

    if any(w in text for w in ["болит", "температура", "симптом"]):
        return "doctor"

    if any(w in text for w in ["обидел", "ссора", "чувствую", "переживаю"]):
        return "psy"

    return "normal"

# ================= AI =================

async def ask_ai(user_id, text, mode):
    async with db.acquire() as conn:
        rows = await conn.fetch("""
        SELECT role, content FROM memory
        WHERE user_id=$1
        ORDER BY created_at DESC
        LIMIT 20
        """, user_id)

    messages = [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    if mode == "psy":
        system = "Ты эмпатичный психолог. Максимально бережный."
    elif mode == "doctor":
        system = "Ты врач. Кратко и по делу. Без лекарств."
    else:
        system = "Ты дружелюбный ассистент."

    messages.insert(0, {"role": "system", "content": system})
    messages.append({"role": "user", "content": text})

    async with httpx.AsyncClient() as client:
        try:
            r = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
                json={"model": "openai/gpt-4o-mini", "messages": messages},
                timeout=20
            )
            data = r.json()
            answer = data["choices"][0]["message"]["content"]
        except:
            answer = "Ошибка AI"

    async with db.acquire() as conn:
        await conn.execute("INSERT INTO memory (user_id, role, content) VALUES ($1,$2,$3)", user_id, "user", text)
        await conn.execute("INSERT INTO memory (user_id, role, content) VALUES ($1,$2,$3)", user_id, "assistant", answer)

    return answer

# ================= HANDLERS =================

@dp.message(CommandStart())
async def start(msg: Message):
    await msg.answer("Привет. Я тебя запомню 🙂 Напиши что-нибудь.")

# -------- REMINDER --------

@dp.message(F.text)
async def handle(msg: Message, state: FSMContext):
    text = msg.text
    user_id = msg.from_user.id

    intent = detect_intent(text)

    # ===== НАПОМИНАНИЕ =====
    if intent == "reminder":
        await state.update_data(reminder_text=text)
        await msg.answer("Когда напомнить?")
        await state.set_state(ReminderState.waiting_time)
        return

    # ===== ПОКАЗАТЬ =====
    if "напомин" in text.lower():
        async with db.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM reminders WHERE user_id=$1", user_id)

        if not rows:
            await msg.answer("Нет напоминаний")
            return

        kb = []
        text_out = ""

        for r in rows:
            text_out += f"{r['text']} — {r['remind_at']}\n"
            kb.append([InlineKeyboardButton(
                text="❌ удалить",
                callback_data=f"del_rem_{r['id']}"
            )])

        await msg.answer(text_out, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
        return

    # ===== ЗАМЕТКА =====
    if intent == "note":
        category = detect_category(text)

        async with db.acquire() as conn:
            await conn.execute(
                "INSERT INTO notes (user_id,text,category) VALUES ($1,$2,$3)",
                user_id, text, category
            )

        await msg.answer(f"✅ Сохранил в {category}")
        return

    # ===== AI =====
    mode = detect_mode(text)
    answer = await ask_ai(user_id, text, mode)
    await msg.answer(answer)

# -------- FSM TIME --------

@dp.message(ReminderState.waiting_time)
async def set_time(msg: Message, state: FSMContext):
    user_id = msg.from_user.id
    data = await state.get_data()
    text = data["reminder_text"]

    # простая логика
    if "час" in msg.text:
        remind_at = datetime.now() + timedelta(hours=1)
    else:
        remind_at = datetime.now() + timedelta(minutes=1)

    async with db.acquire() as conn:
        await conn.execute(
            "INSERT INTO reminders (user_id,text,remind_at) VALUES ($1,$2,$3)",
            user_id, text, remind_at
        )

    await msg.answer("⏰ Напоминание создано")
    await state.clear()

# -------- DELETE --------

@dp.callback_query(F.data.startswith("del_rem_"))
async def delete_rem(cb: CallbackQuery):
    rid = int(cb.data.split("_")[-1])

    async with db.acquire() as conn:
        await conn.execute("DELETE FROM reminders WHERE id=$1", rid)

    await cb.message.edit_text("Удалено")

# ================= SCHEDULER =================

async def scheduler():
    while True:
        await asyncio.sleep(10)

        async with db.acquire() as conn:
            rows = await conn.fetch("""
            SELECT * FROM reminders
            WHERE remind_at <= NOW()
            """)

            for r in rows:
                await bot.send_message(r["user_id"], f"⏰ Напоминание: {r['text']}")
                await conn.execute("DELETE FROM reminders WHERE id=$1", r["id"])

# ================= MAIN =================

async def main():
    # анти-дубль
    if os.getenv("RAILWAY_ENVIRONMENT") == "production":
        if os.getenv("RAILWAY_REPLICA_ID") not in (None, "0"):
            logging.warning("⛔ Второй инстанс — выходим")
            return

    await init_db()

    asyncio.create_task(scheduler())

    logging.info("🚀 БОТ ЗАПУЩЕН")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())