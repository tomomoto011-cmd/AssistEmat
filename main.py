# =========================================================
#  ASSISTEMPAT BOT v2.1 (FIXED)
#  Архитектура: Grok (анализ) + Qwen (эмпатия)
#  БД: Neon PostgreSQL (с авто-миграциями)
# =========================================================

import asyncio
import logging
import os
import re
import random
import signal
import json
from datetime import datetime, timedelta, timezone, date

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

import asyncpg
import httpx
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ======================
#  КОНФИГУРАЦИЯ
# ======================
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")  # Neon
GROK_API_KEY = os.getenv("GROK_API_KEY")
QWEN_API_KEY = os.getenv("QWEN_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
ALLOWED_USERS = os.getenv("ALLOWED_USERS", "")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
scheduler = AsyncIOScheduler(timezone=timezone.utc)

db_pool = None

# ======================
#  БАЗА ДАННЫХ + МИГРАЦИИ
# ======================
async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    
    async with db_pool.acquire() as conn:
        # 1. Создаем таблицы
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users(
            user_id BIGINT PRIMARY KEY,
            name TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS memory(
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            role TEXT,
            content TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS reminders(
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            text TEXT,
            remind_at TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS habits(
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            name TEXT,
            streak INTEGER DEFAULT 0,
            last_done DATE
        );
        CREATE TABLE IF NOT EXISTS emotions(
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            mood TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS last_activity(
            user_id BIGINT PRIMARY KEY,
            last_time TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS profile(
            user_id BIGINT PRIMARY KEY,
            name TEXT,
            age INTEGER,
            gender TEXT
        );
        CREATE TABLE IF NOT EXISTS message_tags(
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            message_id BIGINT,
            tags TEXT[],
            topic TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)
        
        # 2. МИГРАЦИИ: добавляем колонки, если их нет
        # Это чинит ошибку "column does not exist"
        await conn.execute("ALTER TABLE reminders ADD COLUMN IF NOT EXISTS remind_at TIMESTAMP")
        await conn.execute("ALTER TABLE habits ADD COLUMN IF NOT EXISTS streak INTEGER DEFAULT 0")
        await conn.execute("ALTER TABLE habits ADD COLUMN IF NOT EXISTS last_done DATE")
        await conn.execute("ALTER TABLE profile ADD COLUMN IF NOT EXISTS age INTEGER")
        await conn.execute("ALTER TABLE profile ADD COLUMN IF NOT EXISTS gender TEXT")
        
        # 3. Индексы
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_user ON memory(user_id, created_at DESC)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_habits_user ON habits(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_reminders_time ON reminders(remind_at)")
        
    logging.info("✅ PostgreSQL initialized + migrations applied")

# ======================
#  GROK API (Секретарь)
# ======================
async def call_grok_analysis(text: str, history: list = None) -> dict:
    if not GROK_API_KEY:
        return {
            "topic": "general", "tags": [], "intent": "chat",
            "emotional_tone": "neutral", "action_items": [],
            "priority": "medium", "refined_prompt": text
        }
    
    try:
        history_context = "\n".join([f"{m['role']}: {m['content']}" for m in (history or [])[-5:]])
        prompt = f"""
Анализируй сообщение. Верни ТОЛЬКО JSON:

Сообщение: {text}
История: {history_context}

Формат:
{{
    "topic": "работа|учеба|здоровье|отношения|эмоции|быт|другое",
    "tags": ["тег1", "тег2"],
    "intent": "chat|question|task|complaint|request_help",
    "emotional_tone": "neutral|positive|negative|stressed|tired",
    "action_items": [],
    "priority": "low|medium|high",
    "refined_prompt": "уточненный запрос для ответа"
}}
"""
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                "https://api.x.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROK_API_KEY}", "Content-Type": "application/json"},
                json={"model": "grok-beta", "messages": [{"role": "user", "content": prompt}], "temperature": 0.3}
            )
            r.raise_for_status()
            result = r.json()["choices"][0]["message"]["content"].strip()
            if result.startswith("```json"):
                result = result.replace("```json", "").replace("```", "").strip()
            data = json.loads(result)
            return data
    except Exception as e:
        logging.error(f"Grok error: {e}")
        return {"topic": "general", "tags": [], "intent": "chat", "emotional_tone": "neutral", "action_items": [], "priority": "medium", "refined_prompt": text}

# ======================
#  QWEN API (Эмпат)
# ======================
async def call_qwen_empath(user_text, grok_analysis, profile, mood, habits, memory):
    if not QWEN_API_KEY:
        return await call_openrouter_fallback(user_text, grok_analysis, profile, mood, habits, memory)
    
    user_name = profile[0] if profile and profile[0] else "друг"
    habit_list = ", ".join([h[0] for h in habits]) if habits else "не заданы"
    
    system_prompt = f"""
Ты — помощник {user_name}. Стиль: спокойный, конкретный, без излишней эмоциональности.
Контекст: настроение={mood}, тема={grok_analysis.get('topic')}, привычки={habit_list}.

Правила:
1. Без эмодзи или минимум (1 на сообщение)
2. Без фраз "я рядом", "ты важен" — это фальшь
3. Если проблема — предложи решение. Если вопрос — дай ответ
4. Кратко (до 150 слов), по делу
5. Не давай медицинских советов

Примеры хороших ответов:
- "Понял. Что именно беспокоит?"
- "Вижу, что устал. Может, отложить на завтра?"
- "По учебе: какой предмет сейчас сложный?"

Отвечай по-русски.
"""
    context = "\n".join([f"{m['role']}: {m['content']}" for m in memory[-10:]])
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Диалог:\n{context}\n\nСообщение: {user_text}"}
    ]
    
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(
                "https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
                headers={"Authorization": f"Bearer {QWEN_API_KEY}", "Content-Type": "application/json"},
                json={"model": "qwen-max", "messages": messages, "temperature": 0.7, "max_tokens": 500}
            )
            r.raise_for_status()
            return r.json()["output"]["text"].strip()
    except Exception as e:
        logging.error(f"Qwen error: {e}")
        return await call_openrouter_fallback(user_text, grok_analysis, profile, mood, habits, memory)

async def call_openrouter_fallback(user_text, grok_analysis, profile, mood, habits, memory):
    user_name = profile[0] if profile and profile[0] else "друг"
    system_prompt = f"Ты — помощник {user_name}. Отвечай спокойно, по делу. Настроение: {mood}. Тема: {grok_analysis.get('topic')}."
    context = "\n".join([f"{m['role']}: {m['content']}" for m in memory[-10:]])
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": f"{context}\n\n{user_text}"}]
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
                json={"model": "openai/gpt-4o-mini", "messages": messages, "temperature": 0.7},
                timeout=15
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logging.error(f"OpenRouter error: {e}")
        return "Не могу сейчас ответить. Попробуй позже."

# ======================
#  ДБ ФУНКЦИИ
# ======================
async def save_memory(uid, role, content):
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO memory(user_id, role, content) VALUES ($1, $2, $3)", uid, role, content)
        await conn.execute("DELETE FROM memory WHERE user_id=$1 AND id NOT IN (SELECT id FROM memory WHERE user_id=$1 ORDER BY created_at DESC LIMIT 50)", uid)

async def get_memory(uid):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT role, content FROM memory WHERE user_id=$1 ORDER BY created_at DESC LIMIT 20", uid)
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

async def update_emotion(uid, text):
    mood = "нейтральное"
    if any(w in text for w in ["груст", "печаль", "тоск", "плохо"]): mood = "грусть"
    elif any(w in text for w in ["рад", "счастлив", "круто", "отлично"]): mood = "радость"
    elif any(w in text for w in ["устал", "выгор", "нет сил", "тяжело"]): mood = "усталость"
    elif any(w in text for w in ["тревож", "беспоко", "нерв", "страш"]): mood = "тревога"
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO emotions(user_id, mood) VALUES ($1, $2)", uid, mood)

async def get_mood(uid):
    async with db_pool.acquire() as conn:
        row = await conn.fetchval("SELECT mood FROM emotions WHERE user_id=$1 ORDER BY created_at DESC LIMIT 1", uid)
        return row or "нейтральное"

async def update_last_activity(uid):
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO last_activity(user_id, last_time) VALUES ($1, NOW()) ON CONFLICT(user_id) DO UPDATE SET last_time=NOW()", uid)

async def get_profile(uid):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow("SELECT name, age, gender FROM profile WHERE user_id=$1", uid)

async def save_profile(uid, name=None, age=None, gender=None):
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO profile(user_id, name, age, gender) VALUES ($1, $2, $3, $4)
            ON CONFLICT(user_id) DO UPDATE SET
            name=COALESCE($2, profile.name), age=COALESCE($3, profile.age), gender=COALESCE($4, profile.gender)
        """, uid, name, age, gender)

def extract_profile(text):
    text = text.lower()
    name = age = gender = None
    m = re.search(r"меня зовут (\w+)", text)
    if m: name = m.group(1).capitalize()
    m = re.search(r"мне (\d{1,2})", text)
    if m: age = int(m.group(1))
    if "я парень" in text or "я мужчина" in text: gender = "male"
    if "я девушка" in text or "я женщина" in text: gender = "female"
    return name, age, gender

async def create_habit(uid, name):
    async with db_pool.acquire() as conn:
        exists = await conn.fetchval("SELECT id FROM habits WHERE user_id=$1 AND name=$2", uid, name)
        if not exists:
            await conn.execute("INSERT INTO habits(user_id, name) VALUES ($1, $2)", uid, name)

async def get_habits(uid):
    async with db_pool.acquire() as conn:
        return await conn.fetch("SELECT id, name, streak, last_done FROM habits WHERE user_id=$1", uid)

# ======================
#  FSM
# ======================
class ReminderFSM(StatesGroup):
    text = State()
    time = State()

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
    if m: return now + timedelta(minutes=int(m.group(1)))
    if h: return now + timedelta(hours=int(h.group(1)))
    return None

# ======================
#  ХЕНДЛЕРЫ
# ======================
@dp.message(Command("start"))
async def cmd_start(msg: Message, state: FSMContext):
    await state.clear()
    profile = await get_profile(msg.from_user.id)
    name = profile["name"] if profile and profile["name"] else ""
    greeting = f"Привет, {name}." if name else "Привет. Я твой помощник. Как тебя зовут?"
    await msg.answer(greeting)

@dp.message(Command("help"))
async def cmd_help(msg: Message):
    await msg.answer("""
AssistEmpat — личный помощник
• Привычки, напоминания, анализ настроения
• Пиши как другу: "напомни выпить воды через 2 часа"
• /start — начать, /profile — данные о себе
""")

@dp.message(Command("profile"))
async def cmd_profile(msg: Message):
    profile = await get_profile(msg.from_user.id)
    if profile and profile["name"]:
        info = f"Профиль:\nИмя: {profile['name']}\n"
        if profile['age']: info += f"Возраст: {profile['age']}\n"
        if profile['gender']: info += f"Пол: {'мужской' if profile['gender'] == 'male' else 'женский'}\n"
        await msg.answer(info)
    else:
        await msg.answer("Нет данных. Напиши: 'меня зовут...', 'мне 25 лет'")

@dp.message(F.text.contains("напомни"))
async def reminder_start(msg: Message, state: FSMContext):
    await state.set_state(ReminderFSM.text)
    await state.update_data(text=msg.text, uid=msg.from_user.id)
    await msg.answer("Когда? (например: 'через 30 минут', 'вечером')")

@dp.message(ReminderFSM.text)
async def reminder_time(msg: Message, state: FSMContext):
    data = await state.get_data()
    dt = parse_time(msg.text)
    if not dt:
        await msg.answer("Не понял время.")
        return
    # Сохраняем в БД
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO reminders(user_id, text, remind_at) VALUES ($1, $2, $3)", data["uid"], data["text"], dt)
    # Планируем задачу
    scheduler.add_job(send_stored_reminder, "date", run_date=dt, args=[data["uid"], data["text"]], id=f"rem_{data['uid']}_{int(dt.timestamp())}")
    await msg.answer(f"Напомню в {dt.strftime('%H:%M')}")
    await state.clear()

async def send_stored_reminder(uid, text):
    try:
        await bot.send_message(uid, f"⏰ {text}")
        # Удаляем выполненное напоминание
        async with db_pool.acquire() as conn:
            await conn.execute("DELETE FROM reminders WHERE user_id=$1 AND text=$2", uid, text)
    except Exception as e:
        logging.error(f"Failed to send reminder: {e}")

@dp.callback_query(F.data.startswith("done_"))
async def done_habit(call: CallbackQuery):
    hid = int(call.data.split("_")[1])
    now = datetime.now().date()
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT streak, last_done FROM habits WHERE id=$1", hid)
        if not row: return
        streak, last = row["streak"], row["last_done"]
        last_date = last if isinstance(last, date) else (datetime.fromisoformat(str(last)).date() if last else None)
        if last_date == now:
            await call.answer("Уже отмечено", show_alert=True)
            return
        streak = streak + 1 if last_date == now - timedelta(days=1) else 1
        await conn.execute("UPDATE habits SET streak=$1, last_done=$2 WHERE id=$3", streak, now.isoformat(), hid)
    await call.message.edit_text(f"Стрик: {streak} дней")

# ======================
#  ОСНОВНОЙ ЧАТ
# ======================
@dp.message()
async def chat(msg: Message, state: FSMContext):
    if not msg.text: return
    uid = msg.from_user.id
    text = msg.text.strip()
    
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO users(user_id, name) VALUES ($1, $2) ON CONFLICT DO NOTHING", uid, msg.from_user.first_name)
    
    await update_last_activity(uid)
    
    profile = await get_profile(uid)
    if not profile or not profile["name"]:
        name, age, gender = extract_profile(text)
        if name or age or gender:
            await save_profile(uid, name, age, gender)
            await msg.answer(f"Запомнил. {f'Имя: {name}' if name else ''}")
            return
    
    if "напомни" in text.lower() and not any(w in text for w in ["через", "в ", "завтра", "сегодня"]):
        await msg.answer("Уточни время: 'напомни ... через 2 часа'")
        return
    
    memory = await get_memory(uid)
    mood = await get_mood(uid)
    habits = await get_habits(uid)
    
    await save_memory(uid, "user", text)
    await update_emotion(uid, text)
    
    grok_data = await call_grok_analysis(text, memory)
    
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO message_tags(user_id, message_id, tags, topic) VALUES ($1, $2, $3, $4)",
                          uid, msg.message_id, grok_data.get("tags", []), grok_data.get("topic"))
    
    answer = await call_qwen_empath(text, grok_data, profile, mood, habits, memory)
    await msg.answer(answer)

# ======================
#  ПЛАНИРОВЩИК
# ======================
async def morning_ping():
    async with db_pool.acquire() as conn:
        users = await conn.fetch("SELECT user_id FROM users")
    for u in users:
        try: await bot.send_message(u["user_id"], "Доброе утро. План на сегодня?")
        except: pass

async def habit_check():
    async with db_pool.acquire() as conn:
        habits = await conn.fetch("SELECT id, user_id, name, streak, last_done FROM habits")
    now = datetime.now().date()
    for h in habits:
        if h["last_done"]:
            last = h["last_done"] if isinstance(h["last_done"], date) else datetime.fromisoformat(str(h["last_done"])).date()
            if last < now - timedelta(days=1):
                try: await bot.send_message(h["user_id"], f"Привычка '{h['name']}' пропущена. Продолжай.")
                except: pass

async def inactivity_check():
    async with db_pool.acquire() as conn:
        users = await conn.fetch("SELECT user_id, last_time FROM last_activity WHERE last_time < NOW() - INTERVAL '24 hours'")
    for u in users:
        try: await bot.send_message(u["user_id"], "Давно не виделись. Как дела?")
        except: pass

# ======================
#  ЗАПУСК
# ======================
async def main():
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)
    
    await init_db()
    logging.info("✅ AssistEmpat v2.1 запущен (Neon + миграции)")
    
    scheduler.start()
    scheduler.add_job(morning_ping, "cron", hour=9)
    scheduler.add_job(habit_check, "interval", hours=6)
    scheduler.add_job(inactivity_check, "interval", hours=24)
    
    await bot.delete_webhook(drop_pending_updates=True)
    polling_task = asyncio.create_task(dp.start_polling(bot))
    
    await asyncio.wait([polling_task, asyncio.create_task(stop_event.wait())], return_when=asyncio.FIRST_COMPLETED)
    logging.info("👋 Бот остановлен")
    
    await db_pool.close()
    await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("👋 Остановлено пользователем")