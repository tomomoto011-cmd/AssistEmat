# =========================================================
# 🧭 НАВИГАЦИЯ ПО ФАЙЛУ (CTRL+F)
# =========================================================
# [LOCK]         → Redis / анти-дубликаты
# [DB]           → база данных
# [MEMORY]       → память + эмоции
# [HABITS]       → привычки
# [REMINDERS]    → напоминания
# [AI]           → нейронка
# [UTILS]        → вспомогательные функции
# [CHAT]         → основной обработчик сообщений
# [MAIN]         → запуск бота
# =========================================================

import asyncio
import logging
import os
import re
import random
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

import aiosqlite
import httpx

# Redis: пробуем импортировать, но не падаем, если не установлен
try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logging.warning("⚠️ redis-py не установлен — работа без Redis")

from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
REDIS_URL = os.getenv("REDIS_URL")
ALLOWED_USERS = os.getenv("ALLOWED_USERS", "")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

DB_PATH = "bot.db"
scheduler = AsyncIOScheduler(timezone=timezone.utc)

# ======================
# 🔥 REDIS LOCK
# ======================
IS_MAIN = False
redis_client = None

async def acquire_lock():
    global IS_MAIN, redis_client

    if not REDIS_URL or not REDIS_AVAILABLE:
        IS_MAIN = True
        logging.warning("⚠️ NO REDIS → RUNNING AS MAIN")
        return

    try:
        redis_client = redis.from_url(REDIS_URL)
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
# ⚠️ Внимание: глобальный счётчик — подходит для одного инстанса
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
# 🗃 БАЗА ДАННЫХ
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
        CREATE TABLE IF NOT EXISTS last_activity(
            user_id INTEGER PRIMARY KEY,
            last_time TEXT
        );
        CREATE TABLE IF NOT EXISTS profile(
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            age INTEGER,
            gender TEXT
        );
        CREATE TABLE IF NOT EXISTS stats(
            user_id INTEGER PRIMARY KEY,
            xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1
        );
        """)
        await db.commit()

# ======================
# 🎭 FSM
# ======================
class ReminderFSM(StatesGroup):
    text = State()
    time = State()

# ======================
# ⏰ TIME PARSER (FIXED)
# ======================
def parse_time(text):
    text = text.lower()
    now = datetime.now()

    if "вечером" in text:
        dt = now.replace(hour=19, minute=0, second=0, microsecond=0)
        return dt if dt > now else dt + timedelta(days=1)

    if "после работы" in text:
        dt = now.replace(hour=18, minute=30, second=0, microsecond=0)
        return dt if dt > now else dt + timedelta(days=1)

    if "завтра" in text:
        return (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)

    m = re.search(r'через (\d+)\s*минут?', text)
    h = re.search(r'через (\d+)\s*час', text)

    if m:
        return now + timedelta(minutes=int(m.group(1)))
    if h:
        return now + timedelta(hours=int(h.group(1)))

    return None

# ======================
# 🧠 MEMORY + EMOTION
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
# 👁 ACTIVITY TRACKING
# ======================
async def update_last_activity(uid):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        INSERT INTO last_activity(user_id, last_time)
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET last_time=?
        """, (uid, datetime.now().isoformat(), datetime.now().isoformat()))
        await db.commit()

async def inactivity_check():
    """Проверяет пользователей, не активных 24+ часа"""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id, last_time FROM last_activity")
        users = await cur.fetchall()
    now = datetime.now()
    for uid, last in users:
        try:
            last_dt = datetime.fromisoformat(last)
            if now - last_dt > timedelta(hours=24):
                await bot.send_message(uid, "Ты пропал на 24ч. Возвращайся.")
        except Exception as e:
            logging.warning(f"Не удалось отправить напоминание пользователю {uid}: {e}")

# ======================
# 👤 PROFILE
# ======================
def extract_profile(text):
    text = text.lower()
    name = age = gender = None
    m = re.search(r"меня зовут (\w+)", text)
    if m:
        name = m.group(1)
    m = re.search(r"мне (\d{1,2})", text)
    if m:
        age = int(m.group(1))
    if "я парень" in text:
        gender = "male"
    if "я девушка" in text:
        gender = "female"
    return name, age, gender

async def save_profile(uid, name=None, age=None, gender=None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        INSERT INTO profile(user_id, name, age, gender)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
        name=COALESCE(?, name),
        age=COALESCE(?, age),
        gender=COALESCE(?, gender)
        """, (uid, name, age, gender, name, age, gender))
        await db.commit()

async def get_profile(uid):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT name, age, gender FROM profile WHERE user_id=?", (uid,))
        return await cur.fetchone()

# ======================
# 🔁 HABITS
# ======================
async def create_habit(uid, name):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT id FROM habits WHERE user_id=? AND name=?", (uid, name))
        if await cur.fetchone():
            return  # Уже есть
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
        last_date = datetime.fromisoformat(last).date() if last else None
        if last_date == now:
            await call.answer("Уже было сегодня 👍")
            return
        streak = streak + 1 if last_date == now - timedelta(days=1) else 1
        await db.execute(
            "UPDATE habits SET streak=?, last_done=? WHERE id=?",
            (streak, now.isoformat(), hid)
        )
        await db.commit()
    await call.message.edit_text(f"🔥 Стрик: {streak} дня")

# ======================
# 🧭 BEHAVIOR ANALYSIS
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
# 🔍 HABIT CHECK (ежедневный)
# ======================
async def habit_check():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT id,user_id,name,streak,last_done FROM habits")
        habits = await cur.fetchall()
    for hid, uid, name, streak, last in habits:
        if not last:
            continue
        try:
            last_date = datetime.fromisoformat(last).date()
            now = datetime.now().date()
            if last_date < now - timedelta(days=1):
                await bot.send_message(uid, f"{name}\nТы пропустил. Это откат.")
        except Exception as e:
            logging.warning(f"Ошибка в habit_check для {uid}: {e}")

# ======================
# ⏰ REMINDERS
# ======================
async def send_reminder(uid, text):
    try:
        await bot.send_message(uid, f"⏰ {text}")
    except Exception as e:
        logging.warning(f"Не удалось отправить напоминание: {e}")

@dp.message(F.text.contains("напомни"))
async def reminder_start(msg: Message, state: FSMContext):
    await state.set_state(ReminderFSM.text)
    await state.update_data(text=msg.text)
    await msg.answer("Когда напомнить? (например: 'через 30 минут', 'вечером', 'завтра')")

@dp.message(ReminderFSM.text)
async def reminder_time(msg: Message, state: FSMContext):
    data = await state.get_data()
    dt = parse_time(msg.text)
    if not dt:
        await msg.answer("Не понял время. Попробуй: 'через 10 минут', 'вечером', 'завтра в 9'")
        return
    scheduler.add_job(send_reminder, "date", run_date=dt, args=[msg.from_user.id, data["text"]])
    await msg.answer(f"Поставил ⏰ на {dt.strftime('%H:%M')}")
    await state.clear()

# ======================
# ♻️ RETENTION & MORNING
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
# 🤖 AI (OpenRouter)
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
- помогаешь держать фокус
ВАЖНО:
- если ситуация серьёзная (здоровье, травмы, стресс) → будь спокойным и адекватным
- не дави в таких случаях
- сначала помощь, потом дисциплина
Настроение пользователя: {mood}
Отвечай:
- коротко
- по делу
- живо
- без лишней агрессии
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
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logging.error(f"AI request failed: {e}")
        return "❌ AI ошибка. Попробуй позже."

# ======================
# 🔍 UTILS
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
# 💬 CHAT HANDLER
# ======================
@dp.message()
async def chat(msg: Message):
    if not msg.text:
        return
    uid = msg.from_user.id
    await update_last_activity(uid)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO users VALUES (?, ?)", (uid, msg.from_user.first_name))
        await db.commit()
    text = msg.text
    # Добавляем привычки в контекст
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT name FROM habits WHERE user_id=?", (uid,))
        habits = await cur.fetchall()
    if habits:
        habit_list = ", ".join([h[0] for h in habits])
        text += f"\n(его привычки: {habit_list})"
    # Сохраняем память и эмоции
    await save_memory(uid, "user", text)
    await update_emotion(uid, text)
    # Behavior analysis
    behavior = await behavior_analyze(uid, text)
    if behavior:
        await msg.answer(behavior)
    # AI response
    answer = await ask_ai(uid, text)
    await msg.answer(answer)

# =========================================================
# === 🚀 MAIN ENTRYPOINT ===
# =========================================================
async def main():
    await init_db()
    await acquire_lock()
    if IS_MAIN:
        scheduler.start()
        logging.info("🚀 Scheduler started")
        scheduler.add_job(retention, "interval", hours=12)
        scheduler.add_job(habit_check, "interval", hours=6)
        scheduler.add_job(morning_ping, "cron", hour=9)
        scheduler.add_job(inactivity_check, "interval", hours=1)
        asyncio.create_task(keep_lock_alive())
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    else:
        logging.info("⏳ Secondary instance — waiting...")
        while True:
            await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("👋 Bot stopped by user")