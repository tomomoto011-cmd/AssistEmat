import os
import asyncio
import logging
from datetime import datetime, timedelta

from aiohttp import web
import asyncpg
import requests

from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

# ================= CONFIG =================

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

db = None

# ================= FSM =================

class ReminderState(StatesGroup):
    waiting_for_time = State()

# ================= DB =================

async def init_db():
    global db
    db = await asyncpg.create_pool(DATABASE_URL)

    async with db.acquire() as conn:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            text TEXT,
            remind_at TIMESTAMP
        );
        """)

# ================= MENU =================

menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📌 Напоминания")],
        [KeyboardButton(text="➕ Создать напоминание")]
    ],
    resize_keyboard=True
)

# ================= UTILS =================

def parse_time(text):
    text = text.lower()

    try:
        if "мин" in text:
            num = int("".join(filter(str.isdigit, text)) or 1)
            return datetime.now() + timedelta(minutes=num)

        if "час" in text:
            num = int("".join(filter(str.isdigit, text)) or 1)
            return datetime.now() + timedelta(hours=num)
    except:
        return None

    return None

# ================= AI =================

def detect_mode(text):
    t = text.lower()

    if any(x in t for x in ["груст", "плохо", "обид", "тревог", "одиноко"]):
        return "psycho"

    if any(x in t for x in ["болит", "температур", "кашель", "голова"]):
        return "doctor"

    return "normal"

def build_prompt(mode, text):
    if mode == "psycho":
        return f"""
Ты — эмпатичный собеседник.
Максимально поддержи человека, будь мягким и понимающим.

Сообщение:
{text}
"""

    if mode == "doctor":
        return f"""
Ты — спокойный врач.
Отвечай кратко, по делу, без назначения лекарств.

Сообщение:
{text}
"""

    return f"""
Ты — дружелюбный ассистент.
Общайся естественно и по-человечески.

Сообщение:
{text}
"""

def ask_ai(text):
    try:
        mode = detect_mode(text)
        prompt = build_prompt(mode, text)

        logging.info(f"🧠 MODE: {mode}")

        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "mistralai/mixtral-8x7b-instruct",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.8
            },
            timeout=20
        )

        if r.status_code != 200:
            logging.error(f"❌ AI HTTP: {r.text}")
            return None

        return r.json()["choices"][0]["message"]["content"]

    except Exception as e:
        logging.error(f"❌ AI ERROR: {e}")
        return None

# ================= SCHEDULER =================

async def scheduler():
    while True:
        async with db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM reminders WHERE remind_at <= NOW()"
            )

            for r in rows:
                try:
                    await bot.send_message(r["user_id"], f"⏰ {r['text']}")
                except:
                    pass

                await conn.execute("DELETE FROM reminders WHERE id=$1", r["id"])

        await asyncio.sleep(5)

# ================= HANDLERS =================

@dp.message(F.text == "/start")
async def start(message: types.Message):
    await message.answer("Привет! Я помогу 👇", reply_markup=menu)

# === напоминания ===

@dp.message(F.text.contains("напомни") | (F.text == "➕ Создать напоминание"))
async def create_reminder(message: types.Message, state: FSMContext):
    await state.update_data(text=message.text)
    await message.answer("Когда напомнить?")
    await state.set_state(ReminderState.waiting_for_time)

@dp.message(ReminderState.waiting_for_time)
async def set_time(message: types.Message, state: FSMContext):
    data = await state.get_data()

    remind_at = parse_time(message.text)

    if not remind_at:
        await message.answer("Напиши например: через 10 минут")
        return

    async with db.acquire() as conn:
        await conn.execute(
            "INSERT INTO reminders(user_id, text, remind_at) VALUES($1,$2,$3)",
            message.from_user.id,
            data["text"],
            remind_at
        )

    await message.answer("✅ Напоминание создано")
    await state.clear()

# === список ===

@dp.message(F.text == "📌 Напоминания")
async def list_reminders(message: types.Message):
    async with db.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM reminders WHERE user_id=$1",
            message.from_user.id
        )

    if not rows:
        await message.answer("Список пуст")
        return

    for r in rows:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="❌ Удалить",
                callback_data=f"del_{r['id']}"
            )]
        ])

        await message.answer(
            f"{r['text']}\n⏰ {r['remind_at']}",
            reply_markup=kb
        )

# === удаление ===

@dp.callback_query(F.data.startswith("del_"))
async def delete_reminder(callback: types.CallbackQuery):
    rid = int(callback.data.split("_")[1])

    async with db.acquire() as conn:
        await conn.execute("DELETE FROM reminders WHERE id=$1", rid)

    await callback.message.edit_text("❌ Удалено")

# === AI fallback ===

@dp.message()
async def chat(message: types.Message):
    text = message.text or ""

    reply = ask_ai(text)

    if not reply:
        reply = "Не совсем понял, уточни 🙏"

    await message.answer(reply)

# ================= HEALTH =================

async def health(request):
    return web.Response(text="OK")

async def start_health():
    app = web.Application()
    app.router.add_get("/", health)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

# ================= MAIN =================

async def main():
    logging.info("🚀 БОТ ЗАПУЩЕН")

    # анти-дубль (стабильный)
    run_uid = os.getenv("RAILWAY_RUN_UID")
    deploy_id = os.getenv("RAILWAY_DEPLOYMENT_ID")

    if run_uid and deploy_id and run_uid != deploy_id:
        logging.warning("⛔ Второй инстанс — выходим")
        return

    await init_db()
    await start_health()

    await bot.delete_webhook(drop_pending_updates=True)
    await asyncio.sleep(2)

    asyncio.create_task(scheduler())

    await dp.start_polling(bot)

# ================= ENTRY =================

if __name__ == "__main__":
    asyncio.run(main())