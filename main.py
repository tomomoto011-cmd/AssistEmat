import asyncio
import logging
import os
import re
import random
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

import aiosqlite
import httpx
import redis.asyncio as redis

from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler

load_dotenv()
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
REDIS_URL = os.getenv("REDIS_URL")

ALLOWED_USERS = os.getenv("ALLOWED_USERS", "")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

DB_PATH = "bot.db"
scheduler = AsyncIOScheduler()

# ======================
# 🔥 REDIS LOCK (FIXED)
# ======================
IS_MAIN = False
redis_client = None

async def acquire_lock():
    global IS_MAIN, redis_client

    if not REDIS_URL:
        IS_MAIN = True
        logging.warning("⚠️ NO REDIS → RUNNING AS MAIN")
        return

    redis_client = redis.from_url(REDIS_URL)

    try:
        lock = await redis_client.set("bot_lock", os.getpid(), ex=60, nx=True)
        logging.info(f"LOCK OWNER: {os.getpid()}")

        if lock:
            IS_MAIN = True
            logging.info("✅ MAIN INSTANCE (lock acquired)")
        else:
            ttl = await redis_client.ttl("bot_lock")

            if ttl == -2:
                IS_MAIN = True
                logging.warning("⚠️ LOCK LOST → FORCING MAIN")
            else:
                logging.warning(f"⛔ SECONDARY INSTANCE (ttl={ttl})")

    except Exception as e:
        IS_MAIN = True
        logging.error(f"🚨 REDIS FAIL → RUN AS MAIN: {e}")

async def keep_lock_alive():
    while True:
        try:
            if IS_MAIN and redis_client:
                await redis_client.expire("bot_lock", 60)
        except Exception as e:
            logging.error(f"Lock refresh error: {e}")

        await asyncio.sleep(30)

# ======================
# 🛑 АНТИ-ДУБЛЬ
# ======================
LAST_UPDATE_ID = 0

@dp.update.outer_middleware()
async def anti_duplicate(handler, event, data):
    global LAST_UPDATE_ID
    upd = data.get("event_update")

    if upd and hasattr(upd, "update_id"):
        if upd.update_id <= LAST_UPDATE_ID:
            return
        LAST_UPDATE_ID = upd.update_id

    return await handler(event, data)

# ======================
# 🔐 AUTH
# ======================
def is_allowed(user_id: int):
    if not ALLOWED_USERS:
        return True
    return str(user_id) in ALLOWED_USERS.split(",")

# ======================
# БАЗА
# ======================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE IF NOT EXISTS memory(user_id INTEGER, role TEXT, content TEXT);
        CREATE TABLE IF NOT EXISTS reminders(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, text TEXT, remind_at TEXT);

        CREATE TABLE IF NOT EXISTS habits(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT,
            streak INTEGER DEFAULT 0,
            last_done TEXT
        );

        CREATE TABLE IF NOT EXISTS emotions(user_id INTEGER, mood TEXT);

        CREATE TABLE IF NOT EXISTS stats(
            user_id INTEGER PRIMARY KEY,
            xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1
        );
        """)
        await db.commit()

# ======================
# XP SYSTEM
# ======================


# ======================
# FSM
# ======================
class ReminderFSM(StatesGroup):
    text = State()
    time = State()

# ======================
# TIME PARSER
# ======================
def parse_time(text):
    text = text.lower()
    now = datetime.now()

    if "вечером" in text:
        return now.replace(hour=19, minute=0)

    if "после работы" in text:
        return now.replace(hour=18, minute=30)

    if "завтра" in text:
        return (now + timedelta(days=1)).replace(hour=9, minute=0)

    m = re.search(r'через (\d+) минут', text)
    h = re.search(r'через (\d+) час', text)

    if m:
        return now + timedelta(minutes=int(m.group(1)))
    if h:
        return now + timedelta(hours=int(h.group(1)))

    return None

# ======================
# MEMORY + EMOTION
# ======================
async def save_memory(uid, role, content):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO memory VALUES (?, ?, ?)", (uid, role, content))
        await db.commit()

async def get_memory(uid):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT role, content FROM memory WHERE user_id=? ORDER BY rowid DESC LIMIT 20",
            (uid,)
        )
        rows = await cur.fetchall()
        return [{"role": r[0], "content": r[1]} for r in reversed(rows)]

async def update_emotion(uid, text):
    mood = "нейтральное"
    if "груст" in text:
        mood = "грусть"
    elif "рад" in text:
        mood = "радость"
    elif "устал" in text:
        mood = "усталость"

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO emotions VALUES (?, ?)", (uid, mood))
        await db.commit()

async def get_mood(uid):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT mood FROM emotions WHERE user_id=? ORDER BY rowid DESC LIMIT 1",
            (uid,)
        )
        row = await cur.fetchone()
        return row[0] if row else "нейтральное"

# ======================
# HABITS
# ======================
async def create_habit(uid, name):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT id FROM habits WHERE user_id=? AND name=?", (uid, name))
        if await cur.fetchone():
            return
        await db.execute("INSERT INTO habits(user_id,name) VALUES (?,?)", (uid, name))
        await db.commit()

def habit_keyboard(hid):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Сделал", callback_data=f"done_{hid}")]
    ])

@dp.callback_query(F.data.startswith("done_"))
async def done(call: CallbackQuery):
    hid = int(call.data.split("_")[1])
    now = datetime.now().date()

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT streak,last_done FROM habits WHERE id=?", (hid,))
        row = await cur.fetchone()

        if not row:
            return

        streak, last = row
        last = datetime.fromisoformat(last).date() if last else None

        if last == now:
            await call.answer("Уже было")
            return

        streak = streak + 1 if last == now - timedelta(days=1) else 1

        await db.execute(
            "UPDATE habits SET streak=?, last_done=? WHERE id=?",
            (streak, now.isoformat(), hid)
        )
        await db.commit()

    await add_xp(call.from_user.id, 10)
    await call.message.edit_text(f"🔥 Стрик: {streak}")

# ======================
# BEHAVIOR
# ======================
async def behavior_analyze(uid, text):
    mood = await get_mood(uid)

    if "устал" in text:
        await create_habit(uid, "Сон до 23:00")
        return "Ты часто устаёшь. Добавил привычку: сон до 23:00"

    if "потом" in text:
        return "Вот это 'потом' тебя и убивает."

    if "не хочу" in text:
        return "Хочешь или нет — не важно. Важно сделаешь или нет."

    if "завтра" in text:
        return "Ты опять перекладываешь. Сделай сегодня."

    if mood == "грусть":
        return "Сегодня без давления. Но не пропадай."

    return None

# ======================
# HABIT CHECK
# ======================
async def habit_check():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT id,user_id,name,streak,last_done FROM habits")
        habits = await cur.fetchall()

    for hid, uid, name, streak, last in habits:
        if not last:
            continue

        last = datetime.fromisoformat(last).date()
        now = datetime.now().date()

        if last < now - timedelta(days=1):
            await bot.send_message(uid, f"{name}\nТы пропустил. Это откат.")

# ======================
# REMINDERS
# ======================
async def send_reminder(uid, text):
    await bot.send_message(uid, f"⏰ {text}")

@dp.message(F.text.contains("напомни"))
async def reminder_start(msg: Message, state: FSMContext):
    await state.set_state(ReminderFSM.text)
    await state.update_data(text=msg.text)
    await msg.answer("Когда?")

@dp.message(ReminderFSM.text)
async def reminder_time(msg: Message, state: FSMContext):
    data = await state.get_data()
    dt = parse_time(msg.text)

    if not dt:
        await msg.answer("Не понял время")
        return

    scheduler.add_job(send_reminder, "date", run_date=dt, args=[msg.from_user.id, data["text"]])
    await msg.answer("Поставил ⏰")
    await state.clear()

# ======================
# RETENTION
# ======================
async def retention():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id FROM users")
        users = await cur.fetchall()

    for u in users:
        try:
            await bot.send_message(u[0], "Ты пропал. Возвращайся.")
        except:
            pass

# ======================
# MORNING
# ======================
async def morning_ping():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id FROM users")
        users = await cur.fetchall()

    for u in users:
        try:
            await bot.send_message(u[0], "☀️ Доброе утро. План дня?")
        except:
            pass

# ======================
# AI
# ======================
async def ask_ai(uid, text):
    ctx = await get_memory(uid)
    mood = await get_mood(uid)

    system_prompt = f"""
Ты — персональный ассистент и система контроля пользователя.

Ты:
- ведёшь его привычки
- отслеживаешь поведение
- помнишь диалог

- иногда давишь, если он сливается
- помогаешь, но не даёшь расслабляться

Настроение пользователя: {mood}

Никогда не говори, что ты "не ведешь профиль" или "не запоминаешь".
Ты уже это делаешь.

Отвечай:
- коротко
- по делу
- живо
- иногда жестко
"""

    messages = [{"role": "system", "content": system_prompt}] + ctx + [{"role": "user", "content": text}]

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
        return "❌ AI ошибка"
    
# ======================
# UTILS
# ======================
def is_meaningful(text: str):
    text = text.lower().strip()

    if len(text) < 5:
        return False

    garbage = ["ыва", "asdf", "123", "qwe"]
    if any(g in text for g in garbage):
        return False

    return True


# ======================
# CHAT
# ======================
@dp.message()
async def chat(msg: Message):
    if not msg.text:
        return

    uid = msg.from_user.id

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users VALUES (?, ?)",
            (uid, msg.from_user.first_name)
        )
        await db.commit()

    text = msg.text

    # 🔥 добавляем привычки в контекст
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT name FROM habits WHERE user_id=?",
            (uid,)
        )
        habits = await cur.fetchall()

    if habits:
        habit_list = ", ".join([h[0] for h in habits])
        text += f"\n(его привычки: {habit_list})"

    # сохраняем память и эмоции
    await save_memory(uid, "user", text)
    await update_emotion(uid, text)



    # ======================
    # BEHAVIOR
    # ======================
    behavior = await behavior_analyze(uid, text)
    if behavior:
        await msg.answer(behavior)

    # ======================
    # AI
    # ======================
    answer = await ask_ai(uid, text)
    await msg.answer(answer)
# ======================
# MAIN
# ======================
async def main():
    await init_db()
    async def acquire_lock():
     global IS_MAIN, redis_client

    if not REDIS_URL:
        IS_MAIN = True
        logging.warning("⚠️ NO REDIS → RUNNING AS MAIN")
        return

    redis_client = redis.from_url(REDIS_URL)

    try:
        lock = await redis_client.set("bot_lock", os.getpid(), ex=60, nx=True)
        logging.info(f"LOCK OWNER: {os.getpid()}")

        if lock:
            IS_MAIN = True
            logging.info("✅ MAIN INSTANCE (lock acquired)")
        else:
            ttl = await redis_client.ttl("bot_lock")

            # 🔥 если lock почти умер — перехватываем
            if ttl < 10:
                await redis_client.set("bot_lock", os.getpid(), ex=60)
                IS_MAIN = True
                logging.warning("⚠️ FORCE TAKEOVER LOCK")
            else:
                logging.warning(f"⛔ SECONDARY INSTANCE (ttl={ttl})")

    except Exception as e:
        IS_MAIN = True
        logging.error(f"🚨 REDIS FAIL → RUN AS MAIN: {e}")

    if IS_MAIN:
        scheduler.start()
        logging.info("🚀 Scheduler started")

        scheduler.add_job(retention, "interval", hours=12)
        scheduler.add_job(habit_check, "interval", hours=6)
        scheduler.add_job(morning_ping, "cron", hour=9)

        asyncio.create_task(keep_lock_alive())

    if IS_MAIN:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    else:
        while True:
            await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())