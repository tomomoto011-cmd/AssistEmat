# =========================================================
#  ASSISTEMPAT BOT v2.2 (UTILITIES + INLINE)
#  Архитектура: Grok (анализ) + Qwen (эмпатия)
#  БД: Neon PostgreSQL + задачи + inline-кнопки
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
DATABASE_URL = os.getenv("DATABASE_URL")
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
        CREATE TABLE IF NOT EXISTS tasks(
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            title TEXT,
            description TEXT,
            status TEXT DEFAULT 'pending',
            priority TEXT DEFAULT 'medium',
            due_date TIMESTAMP,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)
        
        # Миграции
        await conn.execute("ALTER TABLE reminders ADD COLUMN IF NOT EXISTS remind_at TIMESTAMP")
        await conn.execute("ALTER TABLE habits ADD COLUMN IF NOT EXISTS streak INTEGER DEFAULT 0")
        await conn.execute("ALTER TABLE habits ADD COLUMN IF NOT EXISTS last_done DATE")
        await conn.execute("ALTER TABLE profile ADD COLUMN IF NOT EXISTS age INTEGER")
        await conn.execute("ALTER TABLE profile ADD COLUMN IF NOT EXISTS gender TEXT")
        await conn.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS priority TEXT DEFAULT 'medium'")
        await conn.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS due_date TIMESTAMP")
        
        # Индексы
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_user ON memory(user_id, created_at DESC)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_habits_user ON habits(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_reminders_time ON reminders(remind_at)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id, status)")
        
    logging.info("✅ PostgreSQL initialized + migrations applied")

# ======================
#  ЗАДАЧИ (TASKS)
# ======================
async def create_task(uid, title, description=None, priority="medium", due_date=None):
    async with db_pool.acquire() as conn:
        result = await conn.fetchval(
            "INSERT INTO tasks(user_id, title, description, priority, due_date) VALUES ($1, $2, $3, $4, $5) RETURNING id",
            uid, title, description, priority, due_date
        )
        return result

async def get_tasks(uid, status="pending"):
    async with db_pool.acquire() as conn:
        return await conn.fetch(
            "SELECT id, title, description, priority, due_date, created_at FROM tasks WHERE user_id=$1 AND status=$2 ORDER BY created_at DESC",
            uid, status
        )

async def complete_task(uid, task_id):
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE tasks SET status='completed' WHERE id=$1 AND user_id=$2", task_id, uid)

async def delete_task(uid, task_id):
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM tasks WHERE id=$1 AND user_id=$2", task_id, uid)

async def get_task_stats(uid):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT 
                COUNT(*) FILTER (WHERE status='pending') as pending,
                COUNT(*) FILTER (WHERE status='completed') as completed
            FROM tasks WHERE user_id=$1
        """, uid)
        return row

# ======================
#  INLINE КЛАВИАТУРЫ
# ======================
def main_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Мои задачи", callback_data="tasks_list")],
        [InlineKeyboardButton(text="🔁 Привычки", callback_data="habits_list")],
        [InlineKeyboardButton(text="⏰ Напоминания", callback_data="reminders_list")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats")],
    ])

def task_actions_keyboard(task_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Выполнить", callback_data=f"task_complete_{task_id}")],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"task_delete_{task_id}")],
    ])

def yes_no_keyboard(callback_data_yes, callback_data_no):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Да", callback_data=callback_data_yes),
         InlineKeyboardButton(text="Нет", callback_data=callback_data_no)],
    ])

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
    "topic": "работа|учеба|здоровье|отношения|эмоции|быт|задача|другое",
    "tags": ["тег1", "тег2"],
    "intent": "chat|question|task|complaint|request_help|create_task",
    "emotional_tone": "neutral|positive|negative|stressed|tired",
    "action_items": ["что нужно сделать"],
    "priority": "low|medium|high",
    "refined_prompt": "уточненный запрос",
    "is_task_creation": true/false (если пользователь хочет создать задачу)
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
        return {"topic": "general", "tags": [], "intent": "chat", "emotional_tone": "neutral", "action_items": [], "priority": "medium", "refined_prompt": text, "is_task_creation": False}

# ======================
#  QWEN API (Эмпат)
# ======================
async def call_qwen_empath(user_text, grok_analysis, profile, mood, habits, memory, tasks_count=0):
    if not QWEN_API_KEY:
        return await call_openrouter_fallback(user_text, grok_analysis, profile, mood, habits, memory, tasks_count)
    
    user_name = profile[0] if profile and profile[0] else ""
    habit_list = ", ".join([h[0] for h in habits]) if habits else "не заданы"
    
    system_prompt = f"""
Ты — личный помощник {user_name if user_name else 'пользователя'}. 

Контекст:
- Настроение: {mood}
- Тема: {grok_analysis.get('topic')}
- Привычки: {habit_list}
- Активных задач: {tasks_count}

Стиль общения:
1. Отвечай как живой человек — без фраз "я не жив", "я бот", "я ИИ"
2. Коротко, по делу, без воды
3. Если видишь, что человек хочет создать задачу — предложи сделать это через /task или кнопки
4. Не используй шаблонные фразы вроде "я здесь чтобы помочь"
5. Если вопрос конкретный — дай конкретный ответ
6. Эмодзи используй редко (максимум 1 на сообщение)

Примеры ХОРОШИХ ответов:
- "Понял. Что именно нужно сделать?"
- "Вижу, задач много. Давай разберёмся по порядку."
- "По поводу {grok_analysis.get('topic')}: расскажи подробнее."
- "Можешь создать задачу командой /task или через меню."

Примеры ПЛОХИХ ответов (НИКОГДА не пиши так):
- "Я не жив, но здесь чтобы помочь"
- "Я способен отвечать на вопросы"
- "Я здесь, чтобы помочь тебе"
- "Не стесняйся, спрашивай!"

Отвечай естественно, как в обычном чате.
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
        return await call_openrouter_fallback(user_text, grok_analysis, profile, mood, habits, memory, tasks_count)

async def call_openrouter_fallback(user_text, grok_analysis, profile, mood, habits, memory, tasks_count=0):
    user_name = profile[0] if profile and profile[0] else ""
    system_prompt = f"Ты — помощник {user_name}. Отвечай кратко, по делу, как живой человек. Избегай фраз 'я бот', 'я не жив'. Настроение: {mood}. Тем: {grok_analysis.get('topic')}."
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
#  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
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
class TaskFSM(StatesGroup):
    title = State()
    description = State()
    priority = State()
    due_date = State()

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
#  ХЕНДЛЕРЫ: КОМАНДЫ
# ======================
@dp.message(Command("start"))
async def cmd_start(msg: Message, state: FSMContext):
    await state.clear()
    profile = await get_profile(msg.from_user.id)
    name = profile["name"] if profile and profile["name"] else ""
    greeting = f"Привет, {name}." if name else "Привет. Как тебя зовут?"
    await msg.answer(greeting, reply_markup=main_menu_keyboard())

@dp.message(Command("help"))
async def cmd_help(msg: Message):
    await msg.answer("""
📋 **Команды:**
/task — создать задачу
/tasks — мои задачи
/habits — привычки
/remind — напоминание
/profile — данные о себе
/stats — статистика

Или используй кнопки внизу.
""", parse_mode="Markdown", reply_markup=main_menu_keyboard())

@dp.message(Command("profile"))
async def cmd_profile(msg: Message):
    profile = await get_profile(msg.from_user.id)
    if profile and profile["name"]:
        info = f"👤 Профиль:\nИмя: {profile['name']}\n"
        if profile['age']: info += f"Возраст: {profile['age']}\n"
        if profile['gender']: info += f"Пол: {'мужской' if profile['gender'] == 'male' else 'женский'}\n"
        await msg.answer(info)
    else:
        await msg.answer("Нет данных. Напиши: 'меня зовут...', 'мне 25 лет'")

@dp.message(Command("stats"))
async def cmd_stats(msg: Message):
    stats = await get_task_stats(msg.from_user.id)
    habits = await get_habits(msg.from_user.id)
    text = f"📊 **Статистика**\n"
    text += f"Задачи: {stats['pending'] or 0} активных, {stats['completed'] or 0} выполнено\n"
    text += f"Привычки: {len(habits)}\n"
    await msg.answer(text, parse_mode="Markdown")

# ======================
#  ХЕНДЛЕРЫ: ЗАДАЧИ
# ======================
@dp.message(Command("task"))
async def cmd_task_start(msg: Message, state: FSMContext):
    await state.set_state(TaskFSM.title)
    await msg.answer("📝 Название задачи:")

@dp.message(TaskFSM.title)
async def task_title(msg: Message, state: FSMContext):
    await state.update_data(title=msg.text)
    await state.set_state(TaskFSM.description)
    await msg.answer("📄 Описание (или пропусти /skip):")

@dp.message(TaskFSM.description, F.text == "/skip")
async def task_skip_desc(msg: Message, state: FSMContext):
    await state.update_data(description=None)
    await state.set_state(TaskFSM.priority)
    await msg.answer("⚡ Приоритет (low/medium/high):", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Низкий", callback_data="priority_low"),
         InlineKeyboardButton(text="Средний", callback_data="priority_medium"),
         InlineKeyboardButton(text="Высокий", callback_data="priority_high")],
    ]))

@dp.message(TaskFSM.description)
async def task_description(msg: Message, state: FSMContext):
    await state.update_data(description=msg.text)
    await state.set_state(TaskFSM.priority)
    await msg.answer("⚡ Приоритет (low/medium/high):")

@dp.message(TaskFSM.priority)
async def task_priority(msg: Message, state: FSMContext):
    priority = msg.text.lower() if msg.text.lower() in ["low", "medium", "high"] else "medium"
    await state.update_data(priority=priority)
    await state.set_state(TaskFSM.due_date)
    await msg.answer("📅 Срок (или /skip):")

@dp.message(TaskFSM.due_date, F.text == "/skip")
async def task_skip_date(msg: Message, state: FSMContext):
    data = await state.get_data()
    task_id = await create_task(msg.from_user.id, data["title"], data.get("description"), data["priority"])
    await msg.answer(f"✅ Задача создана (ID: {task_id})", reply_markup=task_actions_keyboard(task_id))
    await state.clear()

@dp.message(TaskFSM.due_date)
async def task_due_date(msg: Message, state: FSMContext):
    due_date = parse_time(msg.text)
    data = await state.get_data()
    task_id = await create_task(msg.from_user.id, data["title"], data.get("description"), data["priority"], due_date)
    await msg.answer(f"✅ Задача создана (ID: {task_id})\nСрок: {due_date.strftime('%d.%m %H:%M') if due_date else 'не указан'}", 
                    reply_markup=task_actions_keyboard(task_id))
    await state.clear()

@dp.message(Command("tasks"))
async def cmd_tasks(msg: Message):
    tasks = await get_tasks(msg.from_user.id, "pending")
    if not tasks:
        await msg.answer("📋 Нет активных задач. Отдыхай!")
        return
    
    text = "📋 **Активные задачи:**\n\n"
    for i, task in enumerate(tasks, 1):
        text += f"{i}. **{task['title']}**\n"
        if task['description']:
            text += f"   {task['description']}\n"
        text += f"   Приоритет: {task['priority']}"
        if task['due_date']:
            text += f" | Срок: {task['due_date'].strftime('%d.%m %H:%M')}"
        text += f"\n   ID: {task['id']}\n\n"
    
    await msg.answer(text, parse_mode="Markdown")

# ======================
#  ХЕНДЛЕРЫ: CALLBACKS
# ======================
@dp.callback_query(F.data == "tasks_list")
async def cb_tasks_list(call: CallbackQuery):
    tasks = await get_tasks(call.from_user.id, "pending")
    if not tasks:
        await call.answer("Нет активных задач", show_alert=True)
        return
    
    text = "📋 **Задачи:**\n"
    for task in tasks[:5]:
        text += f"• {task['title']}"
        if task['due_date']:
            text += f" (до {task['due_date'].strftime('%d.%m')})"
        text += f"\n  ID: {task['id']}\n"
    
    await call.message.edit_text(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())

@dp.callback_query(F.data == "habits_list")
async def cb_habits_list(call: CallbackQuery):
    habits = await get_habits(call.from_user.id)
    if not habits:
        await call.answer("Нет привычек", show_alert=True)
        return
    
    text = "🔁 **Привычки:**\n"
    for h in habits:
        text += f"• {h['name']}: {h['streak']} дней\n"
    
    await call.message.edit_text(text, reply_markup=main_menu_keyboard())

@dp.callback_query(F.data == "reminders_list")
async def cb_reminders_list(call: CallbackQuery):
    await call.answer("Напоминания в разработке", show_alert=True)

@dp.callback_query(F.data == "stats")
async def cb_stats(call: CallbackQuery):
    stats = await get_task_stats(call.from_user.id)
    text = f"📊 Задачи: {stats['pending'] or 0} активных, {stats['completed'] or 0} выполнено"
    await call.answer(text, show_alert=True)

@dp.callback_query(F.data.startswith("task_complete_"))
async def cb_task_complete(call: CallbackQuery):
    task_id = int(call.data.split("_")[-1])
    await complete_task(call.from_user.id, task_id)
    await call.answer("✅ Выполнено!", show_alert=True)
    await call.message.delete()

@dp.callback_query(F.data.startswith("task_delete_"))
async def cb_task_delete(call: CallbackQuery):
    task_id = int(call.data.split("_")[-1])
    await delete_task(call.from_user.id, task_id)
    await call.answer("🗑 Удалено", show_alert=True)
    await call.message.delete()

@dp.callback_query(F.data.startswith("priority_"))
async def cb_priority(call: CallbackQuery):
    priority = call.data.split("_")[1]
    await call.message.answer(f"Выбран приоритет: {priority}")
    # Здесь нужна более сложная логика FSM — упрощено

# ======================
#  ОСНОВНОЙ ЧАТ
# ======================
@dp.message()
async def chat(msg: Message, state: FSMContext):
    if not msg.text: return
    if await state.get_state(): return  # Если пользователь в FSM — не обрабатываем
    
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
    
    memory = await get_memory(uid)
    mood = await get_mood(uid)
    habits = await get_habits(uid)
    tasks_count = (await get_task_stats(uid))["pending"] or 0
    
    await save_memory(uid, "user", text)
    await update_emotion(uid, text)
    
    grok_data = await call_grok_analysis(text, memory)
    
    # Если Grok определил создание задачи
    if grok_data.get("is_task_creation") or "задач" in text.lower() or "сделай" in text.lower():
        await msg.answer("Создать задачу? Используй /task или кнопку ниже.", reply_markup=main_menu_keyboard())
        return
    
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO message_tags(user_id, message_id, tags, topic) VALUES ($1, $2, $3, $4)",
                          uid, msg.message_id, grok_data.get("tags", []), grok_data.get("topic"))
    
    answer = await call_qwen_empath(text, grok_data, profile, mood, habits, memory, tasks_count)
    await msg.answer(answer)

# ======================
#  ПЛАНИРОВЩИК
# ======================
async def morning_ping():
    async with db_pool.acquire() as conn:
        users = await conn.fetch("SELECT user_id FROM users")
    for u in users:
        try: await bot.send_message(u["user_id"], "Доброе утро. Какой план?")
        except: pass

async def habit_check():
    async with db_pool.acquire() as conn:
        habits = await conn.fetch("SELECT id, user_id, name, streak, last_done FROM habits")
    now = datetime.now().date()
    for h in habits:
        if h["last_done"]:
            last = h["last_done"] if isinstance(h["last_done"], date) else datetime.fromisoformat(str(h["last_done"])).date()
            if last < now - timedelta(days=1):
                try: await bot.send_message(h["user_id"], f"Привычка '{h['name']}' пропущена.")
                except: pass

async def task_reminder_check():
    """Проверяет задачи с дедлайном"""
    async with db_pool.acquire() as conn:
        tasks = await conn.fetch("""
            SELECT user_id, title, due_date FROM tasks 
            WHERE status='pending' AND due_date IS NOT NULL 
            AND due_date <= NOW() + INTERVAL '1 hour'
            AND due_date > NOW() - INTERVAL '1 hour'
        """)
    for task in tasks:
        try:
            await bot.send_message(task["user_id"], f"⏰ Скоро дедлайн: {task['title']}")
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
    logging.info("✅ AssistEmpat v2.2 запущен (Tasks + Inline)")
    
    scheduler.start()
    scheduler.add_job(morning_ping, "cron", hour=9)
    scheduler.add_job(habit_check, "interval", hours=6)
    scheduler.add_job(task_reminder_check, "interval", minutes=30)
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