import os
import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web
import requests

# ================= CONFIG =================

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")
QWEN_KEY = os.getenv("QWEN_API_KEY")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ================= MEMORY =================

user_memory = {}
notes_db = {}
reminders_db = {}

# ================= FSM =================

class ReminderFSM(StatesGroup):
    waiting_text = State()
    waiting_time = State()

# ================= UTILS =================

def safe_text(text):
    return text or ""

def is_russian(text):
    if not text:
        return False
    return any("а" <= c <= "я" or "А" <= c <= "Я" for c in text)

# ================= AI =================

def ask_openrouter(user_id, message):
    history = user_memory.get(user_id, [])

    messages = [{"role": "system", "content": "Отвечай ВСЕГДА на русском языке."}]
    messages += history[-20:]
    messages.append({"role": "user", "content": message})

    try:
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "mistralai/mixtral-8x7b-instruct",
                "messages": messages
            },
            timeout=15
        )

        if r.status_code != 200:
            logging.error(f"OpenRouter error: {r.text}")
            return None

        data = r.json()
        reply = data["choices"][0]["message"]["content"]

        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": reply})
        user_memory[user_id] = history[-40:]

        return reply

    except Exception as e:
        logging.error(f"OpenRouter exception: {e}")
        return None


def ask_qwen(message):
    try:
        r = requests.post(
            "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
            headers={
                "Authorization": f"Bearer {QWEN_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "qwen-turbo",
                "input": {
                    "messages": [
                        {"role": "system", "content": "Отвечай только на русском"},
                        {"role": "user", "content": message}
                    ]
                }
            },
            timeout=15
        )

        if r.status_code != 200:
            logging.error(f"Qwen error: {r.text}")
            return None

        return r.json()["output"]["text"]

    except Exception as e:
        logging.error(f"Qwen exception: {e}")
        return None

# ================= MENU =================

def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Заметки", callback_data="notes")],
        [InlineKeyboardButton(text="⏰ Напоминания", callback_data="reminders")]
    ])

# ================= COMMANDS =================

@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer(
        "Привет 👋 Я твой ассистент.\n\nВыбери раздел:",
        reply_markup=main_menu()
    )

# ================= CALLBACK =================

@dp.callback_query()
async def callbacks(call: types.CallbackQuery):
    user_id = call.from_user.id

    if call.data == "notes":
        notes = notes_db.get(user_id, [])
        text = "\n".join(notes) if notes else "Нет заметок"
        await call.message.answer(f"📝 Заметки:\n{text}")

    elif call.data == "reminders":
        rems = reminders_db.get(user_id, [])
        text = "\n".join([r["text"] for r in rems]) if rems else "Нет напоминаний"
        await call.message.answer(f"⏰ Напоминания:\n{text}")

# ================= NOTES =================

@dp.message(lambda m: m.text and "запомни" in m.text.lower())
async def save_note(message: types.Message):
    user_id = message.from_user.id
    text = message.text.replace("запомни", "").strip()

    notes_db.setdefault(user_id, []).append(text)
    await message.answer("📝 Сохранил")

# ================= REMINDER FSM =================

@dp.message(lambda m: m.text and "напомни" in m.text.lower())
async def start_reminder(message: types.Message, state: FSMContext):
    await state.set_state(ReminderFSM.waiting_text)
    await message.answer("Что напомнить?")

@dp.message(ReminderFSM.waiting_text)
async def get_text(message: types.Message, state: FSMContext):
    await state.update_data(text=message.text)
    await state.set_state(ReminderFSM.waiting_time)
    await message.answer("Когда напомнить?")

@dp.message(ReminderFSM.waiting_time)
async def get_time(message: types.Message, state: FSMContext):
    data = await state.get_data()
    text = data.get("text")

    remind_time = datetime.now() + timedelta(minutes=1)

    user_id = message.from_user.id

    reminders_db.setdefault(user_id, []).append({
        "text": text,
        "time": remind_time
    })

    asyncio.create_task(reminder_task(message.chat.id, text, remind_time))

    await message.answer("⏰ Напоминание создано (пока +1 минута)")
    await state.clear()

# ================= REMINDER TASK =================

async def reminder_task(chat_id, text, when):
    delay = (when - datetime.now()).total_seconds()
    await asyncio.sleep(max(0, delay))
    await bot.send_message(chat_id, f"🔔 Напоминание: {text}")

# ================= CHAT =================

@dp.message()
async def chat(message: types.Message):
    user_id = message.from_user.id
    text = safe_text(message.text)

    if not text:
        return

    if not is_russian(text):
        text = f"Ответь на русском: {text}"

    reply = ask_openrouter(user_id, text)

    if not reply:
        reply = ask_qwen(text)

    if not reply:
        reply = "⚠️ AI временно недоступен"

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

    await start_health()

    await bot.delete_webhook(drop_pending_updates=True)
    await asyncio.sleep(2)

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())