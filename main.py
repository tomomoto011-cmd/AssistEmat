# =========================================================
#  ASSISTEMPAT BOT v2.3 (OpenAI-primary + smart commands)
#  Архитектура: Grok (анализ) + OpenAI (основной ответ)
#  БД: Neon PostgreSQL + задачи + inline-кнопки
#  Внешние данные: ссылки на Яндекс (погода, кино, курсы)
# =========================================================

import asyncio
import logging
import os
import re
import signal
import json
import urllib.parse
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
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")  # 🔥 OpenAI — основной
QWEN_API_KEY = os.getenv("QWEN_API_KEY")  # опциональный фоллбэк
CITY_DEFAULT = os.getenv("CITY_DEFAULT", "Москва")
ALLOWED_USERS = os.getenv("ALLOWED_USERS", "")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
scheduler = AsyncIOScheduler(timezone=timezone.utc)
db_pool = None

# ======================
#  БАЗА ДАННЫХ
# ======================
async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    async with db_pool.acquire() as conn:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users(user_id BIGINT PRIMARY KEY, name TEXT, created_at TIMESTAMP DEFAULT NOW());
        CREATE TABLE IF NOT EXISTS memory(id SERIAL PRIMARY KEY, user_id BIGINT, role TEXT, content TEXT, created_at TIMESTAMP DEFAULT NOW());
        CREATE TABLE IF NOT EXISTS reminders(id SERIAL PRIMARY KEY, user_id BIGINT, text TEXT, remind_at TIMESTAMP);
        CREATE TABLE IF NOT EXISTS habits(id SERIAL PRIMARY KEY, user_id BIGINT, name TEXT, streak INTEGER DEFAULT 0, last_done DATE);
        CREATE TABLE IF NOT EXISTS emotions(id SERIAL PRIMARY KEY, user_id BIGINT, mood TEXT, created_at TIMESTAMP DEFAULT NOW());
        CREATE TABLE IF NOT EXISTS last_activity(user_id BIGINT PRIMARY KEY, last_time TIMESTAMP DEFAULT NOW());
        CREATE TABLE IF NOT EXISTS profile(user_id BIGINT PRIMARY KEY, name TEXT, age INTEGER, gender TEXT);
        CREATE TABLE IF NOT EXISTS message_tags(id SERIAL PRIMARY KEY, user_id BIGINT, message_id BIGINT, tags TEXT[], topic TEXT, created_at TIMESTAMP DEFAULT NOW());
        CREATE TABLE IF NOT EXISTS tasks(id SERIAL PRIMARY KEY, user_id BIGINT, title TEXT, description TEXT, status TEXT DEFAULT 'pending', priority TEXT DEFAULT 'medium', due_date TIMESTAMP, created_at TIMESTAMP DEFAULT NOW());
        """)
        await conn.execute("ALTER TABLE reminders ADD COLUMN IF NOT EXISTS remind_at TIMESTAMP")
        await conn.execute("ALTER TABLE habits ADD COLUMN IF NOT EXISTS streak INTEGER DEFAULT 0")
        await conn.execute("ALTER TABLE habits ADD COLUMN IF NOT EXISTS last_done DATE")
        await conn.execute("ALTER TABLE profile ADD COLUMN IF NOT EXISTS age INTEGER")
        await conn.execute("ALTER TABLE profile ADD COLUMN IF NOT EXISTS gender TEXT")
        await conn.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS priority TEXT DEFAULT 'medium'")
        await conn.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS due_date TIMESTAMP")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_user ON memory(user_id, created_at DESC)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_habits_user ON habits(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_reminders_time ON reminders(remind_at)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id, status)")
    logging.info("✅ PostgreSQL initialized")

# ======================
#  ССЫЛКИ НА ВНЕШНИЕ РЕСУРСЫ
# ======================
def get_weather_link(city: str) -> str:
    return f"https://yandex.ru/pogoda/{urllib.parse.quote(city)}"
def get_currency_link() -> str:
    return "https://www.cbr.ru/currency_base/daily/"
def get_cinema_link(city: str = "Москва") -> str:
    return f"https://afisha.yandex.ru/{urllib.parse.quote(city)}/cinema/"
def get_news_link() -> str:
    return "https://news.yandex.ru/"
def get_translate_link() -> str:
    return "https://translate.yandex.ru/"

# ======================
#  ЗАДАЧИ
# ======================
async def create_task(uid, title, description=None, priority="medium", due_date=None):
    async with db_pool.acquire() as conn:
        return await conn.fetchval("INSERT INTO tasks(user_id, title, description, priority, due_date) VALUES ($1,$2,$3,$4,$5) RETURNING id", uid, title, description, priority, due_date)
async def get_tasks(uid, status="pending"):
    async with db_pool.acquire() as conn:
        return await conn.fetch("SELECT id,title,description,priority,due_date,created_at FROM tasks WHERE user_id=$1 AND status=$2 ORDER BY created_at DESC", uid, status)
async def complete_task(uid, task_id):
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE tasks SET status='completed' WHERE id=$1 AND user_id=$2", task_id, uid)
async def delete_task(uid, task_id):
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM tasks WHERE id=$1 AND user_id=$2", task_id, uid)
async def get_task_stats(uid):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow("SELECT COUNT(*) FILTER (WHERE status='pending') as pending, COUNT(*) FILTER (WHERE status='completed') as completed FROM tasks WHERE user_id=$1", uid)

# ======================
#  INLINE КЛАВИАТУРЫ
# ======================
def main_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Задачи", callback_data="tasks_list"), InlineKeyboardButton(text="➕ Новая", callback_data="task_create")],
        [InlineKeyboardButton(text="🔁 Привычки", callback_data="habits_list"), InlineKeyboardButton(text="📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton(text="⏰ Напомнить", callback_data="reminders_list")],
        [InlineKeyboardButton(text="🌤 Погода", callback_data="ext_weather"), InlineKeyboardButton(text="💱 Курс", callback_data="ext_currency")],
        [InlineKeyboardButton(text="🎬 Афиша", callback_data="ext_cinema"), InlineKeyboardButton(text="📰 Новости", callback_data="ext_news")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile_show"), InlineKeyboardButton(text="❓ Помощь", callback_data="help_show")],
    ])
def task_actions_keyboard(task_id):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Выполнить", callback_data=f"task_complete_{task_id}")], [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"task_delete_{task_id}")]])
def external_link_keyboard(link: str, label: str = "Открыть"):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"🔗 {label}", url=link)]])

# ======================
#  GROK API (анализ + определение ссылок)
# ======================
async def call_grok_analysis(text: str, history: list = None, profile: dict = None) -> dict:
    if not GROK_API_KEY:
        return {"topic":"general","tags":[],"intent":"chat","emotional_tone":"neutral","action_items":[],"priority":"medium","refined_prompt":text,"is_task_creation":False,"external_link_needed":None,"external_link":None}
    try:
        history_ctx = "\n".join([f"{m['role']}: {m['content']}" for m in (history or [])[-5:]])
        user_info = f"Имя:{profile.get('name')},Возраст:{profile.get('age')},Пол:{profile.get('gender')}" if profile else ""
        prompt = f"""Анализируй сообщение. Верни ТОЛЬКО JSON:
Пользователь:{user_info}
Сообщение:{text}
История:{history_ctx}
Формат:{{"topic":"работа|учеба|здоровье|отношения|эмоции|быт|задача|погода|кино|финансы|новости|другое","tags":[],"intent":"chat|question|task|request_help|create_task|request_external_link","emotional_tone":"neutral|positive|negative|stressed|tired","action_items":[],"priority":"low|medium|high","refined_prompt":"...","is_task_creation":true/false,"external_link_needed":null|"weather"|"currency"|"cinema"|"news"|"translate","external_link_params":{{"city":"..."}} или null}}"""
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post("https://api.x.ai/v1/chat/completions", headers={"Authorization":f"Bearer {GROK_API_KEY}","Content-Type":"application/json"}, json={"model":"grok-beta","messages":[{"role":"user","content":prompt}],"temperature":0.3})
            r.raise_for_status()
            result = r.json()["choices"][0]["message"]["content"].strip()
            if result.startswith("```json"): result = result.replace("```json","").replace("```","").strip()
            data = json.loads(result)
            if data.get("external_link_needed")=="weather":
                city = data.get("external_link_params",{}).get("city") or CITY_DEFAULT
                data["external_link"] = get_weather_link(city); data["external_link_label"] = f"Погода в {city}"
            elif data.get("external_link_needed")=="currency":
                data["external_link"] = get_currency_link(); data["external_link_label"] = "Курс валют ЦБ"
            elif data.get("external_link_needed")=="cinema":
                city = data.get("external_link_params",{}).get("city") or CITY_DEFAULT
                data["external_link"] = get_cinema_link(city); data["external_link_label"] = f"Афиша: {city}"
            elif data.get("external_link_needed")=="news":
                data["external_link"] = get_news_link(); data["external_link_label"] = "Новости"
            elif data.get("external_link_needed")=="translate":
                data["external_link"] = get_translate_link(); data["external_link_label"] = "Переводчик"
            return data
    except Exception as e:
        logging.error(f"Grok error: {e}")
        return {"topic":"general","tags":[],"intent":"chat","emotional_tone":"neutral","action_items":[],"priority":"medium","refined_prompt":text,"is_task_creation":False,"external_link_needed":None,"external_link":None}

# ======================
#  OPENAI (ОСНОВНОЙ ОТВЕТ) — через OpenRouter
# ======================
async def call_openai_primary(user_text, grok_analysis, profile, mood, habits, memory, tasks_count=0):
    if not OPENROUTER_API_KEY:
        return await call_qwen_fallback(user_text, grok_analysis, profile, mood, habits, memory, tasks_count)
    
    user_name = profile.get("name") if profile else ""
    habit_list = ", ".join([h[0] for h in habits]) if habits else "не заданы"
    
    # Блок с ссылкой для контекста
    link_context = ""
    if grok_analysis.get("external_link"):
        link = grok_analysis["external_link"]
        label = grok_analysis.get("external_link_label", "Открыть")
        link_context = f"\n[Ссылка для пользователя: {label} — {link}]"
    
    system_prompt = f"""Ты — личный помощник {user_name if user_name else 'пользователя'}.
Контекст: настроение={mood}, тема={grok_analysis.get('topic')}, привычки={habit_list}, задач={tasks_count}{link_context}

ПРАВИЛА:
1. Отвечай как живой человек — НИКАКИХ "Привет!", "Я здесь чтобы помочь", "Не стесняйся"
2. Если есть [Ссылка для пользователя] — предложи её кратко: "Погоду смотри тут: [кнопка]"
3. Коротко, по делу. Максимум 3-4 предложения
4. Если вопрос по учебе/работе — дай конкретный ответ, не спрашивай "что именно?"
5. Эмодзи — максимум 1, только если уместно
6. Не повторяй одно и то же в соседних сообщениях

Примеры ХОРОШИХ ответов:
- "Понял. Местоимения заменяют существительные: я, ты, он, она. Суффиксы — это части слова после корня, например -ик-, -ок-."
- "Погоду в Волгограде смотри тут: [кнопка]. Одевайся теплее, там +5°."
- "Задачу создал. Срок — завтра в 18:00."

Примеры ПЛОХИХ (никогда не пиши):
- "Привет! Как могу помочь?"
- "Я здесь чтобы поддержать тебя"
- "Расскажи подробнее, что именно нужно?"

Отвечай естественно, как в обычном чате."""
    
    context = "\n".join([f"{m['role']}: {m['content']}" for m in memory[-10:]])
    messages = [{"role":"system","content":system_prompt},{"role":"user","content":f"Диалог:\n{context}\n\nСообщение:{user_text}"}]
    
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post("https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization":f"Bearer {OPENROUTER_API_KEY}","Content-Type":"application/json"},
                json={"model":"openai/gpt-4o-mini","messages":messages,"temperature":0.7,"max_tokens":400}, timeout=20)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logging.error(f"OpenRouter error: {e}")
        return await call_qwen_fallback(user_text, grok_analysis, profile, mood, habits, memory, tasks_count)

# ======================
#  QWEN (фоллбэк, если OpenAI недоступен)
# ======================
async def call_qwen_fallback(user_text, grok_analysis, profile, mood, habits, memory, tasks_count=0):
    if not QWEN_API_KEY:
        return "Не могу сейчас ответить. Попробуй позже."
    user_name = profile.get("name") if profile else ""
    system_prompt = f"Ты — помощник {user_name}. Отвечай кратко, по делу. Настроение:{mood}. Тема:{grok_analysis.get('topic')}."
    context = "\n".join([f"{m['role']}: {m['content']}" for m in memory[-10:]])
    messages = [{"role":"system","content":system_prompt},{"role":"user","content":f"{context}\n\n{user_text}"}]
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post("https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
                headers={"Authorization":f"Bearer {QWEN_API_KEY}"},
                json={"model":"qwen-max","messages":messages,"temperature":0.7}, timeout=15)
            r.raise_for_status()
            return r.json()["output"]["text"].strip()
    except:
        return "Не могу сейчас ответить. Попробуй позже."

# ======================
#  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ======================
async def save_memory(uid, role, content):
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO memory(user_id,role,content) VALUES ($1,$2,$3)", uid, role, content)
        await conn.execute("DELETE FROM memory WHERE user_id=$1 AND id NOT IN (SELECT id FROM memory WHERE user_id=$1 ORDER BY created_at DESC LIMIT 50)", uid)
async def get_memory(uid):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT role,content FROM memory WHERE user_id=$1 ORDER BY created_at DESC LIMIT 20", uid)
        return [{"role":r["role"],"content":r["content"]} for r in reversed(rows)]
async def update_emotion(uid, text):
    mood = "нейтральное"
    if any(w in text for w in ["груст","печаль","тоск","плохо"]): mood = "грусть"
    elif any(w in text for w in ["рад","счастлив","круто"]): mood = "радость"
    elif any(w in text for w in ["устал","выгор","нет сил"]): mood = "усталость"
    elif any(w in text for w in ["тревож","беспоко","нерв"]): mood = "тревога"
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO emotions(user_id,mood) VALUES ($1,$2)", uid, mood)
async def get_mood(uid):
    async with db_pool.acquire() as conn:
        row = await conn.fetchval("SELECT mood FROM emotions WHERE user_id=$1 ORDER BY created_at DESC LIMIT 1", uid)
        return row or "нейтральное"
async def update_last_activity(uid):
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO last_activity(user_id,last_time) VALUES ($1,NOW()) ON CONFLICT(user_id) DO UPDATE SET last_time=NOW()", uid)
async def get_profile(uid):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT name,age,gender FROM profile WHERE user_id=$1", uid)
        return {"name":row["name"],"age":row["age"],"gender":row["gender"]} if row else None
async def save_profile(uid, name=None, age=None, gender=None):
    async with db_pool.acquire() as conn:
        await conn.execute("""INSERT INTO profile(user_id,name,age,gender) VALUES ($1,$2,$3,$4) ON CONFLICT(user_id) DO UPDATE SET name=COALESCE($2,profile.name),age=COALESCE($3,profile.age),gender=COALESCE($4,profile.gender)""", uid, name, age, gender)
def extract_profile(text):
    text = text.lower(); name=age=gender=None
    m = re.search(r"меня зовут (\w+)", text)
    if m: name = m.group(1).capitalize()
    m = re.search(r"мне (\d{1,2})", text)
    if m: age = int(m.group(1))
    if "я парень" in text or "я мужчина" in text: gender = "male"
    if "я девушка" in text or "я женщина" in text: gender = "female"
    return name, age, gender
async def create_habit(uid, name):
    async with db_pool.acquire() as conn:
        if not await conn.fetchval("SELECT id FROM habits WHERE user_id=$1 AND name=$2", uid, name):
            await conn.execute("INSERT INTO habits(user_id,name) VALUES ($1,$2)", uid, name)
async def get_habits(uid):
    async with db_pool.acquire() as conn:
        return await conn.fetch("SELECT id,name,streak,last_done FROM habits WHERE user_id=$1", uid)
def parse_time(text):
    text = text.lower(); now = datetime.now()
    if "вечером" in text: dt = now.replace(hour=19,minute=0); return dt if dt>now else dt+timedelta(days=1)
    if "после работы" in text: dt = now.replace(hour=18,minute=30); return dt if dt>now else dt+timedelta(days=1)
    if "завтра" in text: return (now+timedelta(days=1)).replace(hour=9,minute=0)
    m = re.search(r'через (\d+)\s*минут?', text); h = re.search(r'через (\d+)\s*час', text)
    if m: return now+timedelta(minutes=int(m.group(1)))
    if h: return now+timedelta(hours=int(h.group(1)))
    return None

# ======================
#  FSM
# ======================
class TaskFSM(StatesGroup):
    title=State(); description=State(); priority=State(); due_date=State()

# ======================
#  ХЕНДЛЕРЫ: КОМАНДЫ
# ======================
@dp.message(Command("start"))
async def cmd_start(msg:Message, state:FSMContext):
    await state.clear()
    profile = await get_profile(msg.from_user.id)
    name = profile["name"] if profile and profile["name"] else ""
    await msg.answer(f"Привет, {name}." if name else "Привет. Как тебя зовут?", reply_markup=main_menu_keyboard())
@dp.message(Command("help"))
async def cmd_help(msg:Message):
    await msg.answer("📋 **Команды:**\n/task — задача\n/tasks — список\n/habits — привычки\n/profile — данные\n/stats — статистика\n/weather [город] — погода\n/currency — курс\n/cinema [город] — афиша\n\nИли кнопки внизу 👇", parse_mode="Markdown", reply_markup=main_menu_keyboard())
@dp.message(Command("profile"))
async def cmd_profile(msg:Message):
    p = await get_profile(msg.from_user.id)
    if p and p["name"]: await msg.answer(f"👤 {p['name']}" + (f", {p['age']} лет" if p['age'] else "") + (f", {p['gender']}" if p['gender'] else ""))
    else: await msg.answer("Нет данных. Напиши: 'меня зовут...', 'мне 25'")
@dp.message(Command("stats"))
async def cmd_stats(msg:Message):
    s = await get_task_stats(msg.from_user.id)
    await msg.answer(f"📊 Задачи: {s['pending'] or 0} активных, {s['completed'] or 0} выполнено")
@dp.message(Command("weather"))
async def cmd_weather(msg:Message):
    city = CITY_DEFAULT; parts = msg.text.split(maxsplit=1)
    if len(parts)>1: city = parts[1]
    await msg.answer(f"🌤 Погода в {city}:", reply_markup=external_link_keyboard(get_weather_link(city), f"Яндекс.Погода: {city}"))
@dp.message(Command("currency"))
async def cmd_currency(msg:Message):
    await msg.answer("💱 Курс валют ЦБ РФ:", reply_markup=external_link_keyboard(get_currency_link(), "Открыть ЦБ"))
@dp.message(Command("cinema"))
async def cmd_cinema(msg:Message):
    city = CITY_DEFAULT; parts = msg.text.split(maxsplit=1)
    if len(parts)>1: city = parts[1]
    await msg.answer(f"🎬 Афиша: {city}", reply_markup=external_link_keyboard(get_cinema_link(city), f"Афиша: {city}"))

# ======================
#  ХЕНДЛЕРЫ: ЗАДАЧИ
# ======================
@dp.message(Command("task"))
async def cmd_task_start(msg:Message, state:FSMContext):
    await state.set_state(TaskFSM.title); await msg.answer("📝 Название задачи:")
@dp.message(TaskFSM.title)
async def task_title(msg:Message, state:FSMContext):
    await state.update_data(title=msg.text); await state.set_state(TaskFSM.description); await msg.answer("📄 Описание (или /skip):")
@dp.message(TaskFSM.description, F.text=="/skip")
async def task_skip_desc(msg:Message, state:FSMContext):
    await state.update_data(description=None); await state.set_state(TaskFSM.priority); await msg.answer("⚡ Приоритет: низкий / средний / высокий")
@dp.message(TaskFSM.description)
async def task_description(msg:Message, state:FSMContext):
    await state.update_data(description=msg.text); await state.set_state(TaskFSM.priority); await msg.answer("⚡ Приоритет: низкий / средний / высокий")
@dp.message(TaskFSM.priority)
async def task_priority(msg:Message, state:FSMContext):
    p = msg.text.lower(); priority = "high" if "высок" in p else ("low" if "низк" in p else "medium")
    await state.update_data(priority=priority); await state.set_state(TaskFSM.due_date); await msg.answer("📅 Срок (или /skip):")
@dp.message(TaskFSM.due_date)
async def task_finish(msg:Message, state:FSMContext):
    data = await state.get_data(); due = parse_time(msg.text) if msg.text!="/skip" else None
    tid = await create_task(msg.from_user.id, data["title"], data.get("description"), data["priority"], due)
    await msg.answer(f"✅ Задача #{tid} создана", reply_markup=task_actions_keyboard(tid)); await state.clear()
@dp.message(Command("tasks"))
async def cmd_tasks(msg:Message):
    tasks = await get_tasks(msg.from_user.id)
    if not tasks: await msg.answer("📋 Нет активных задач. Отдыхай!", reply_markup=main_menu_keyboard()); return
    text = "📋 **Задачи:**\n" + "\n".join([f"• {t['title']}" + (f" ({t['due_date'].strftime('%d.%m')})" if t['due_date'] else "") + f" | ID:{t['id']}" for t in tasks[:5]])
    await msg.answer(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())

# ======================
#  CALLBACKS
# ======================
@dp.callback_query(F.data=="tasks_list")
async def cb_tasks(call:CallbackQuery):
    tasks = await get_tasks(call.from_user.id)
    text = "📋 Задачи:\n" + "\n".join([f"• {t['title']} | ID:{t['id']}" for t in tasks[:5]]) if tasks else "Нет задач"
    await call.message.edit_text(text, reply_markup=main_menu_keyboard())
@dp.callback_query(F.data=="task_create")
async def cb_task_create(call:CallbackQuery):
    await call.message.answer("📝 Название новой задачи:"); await call.answer("Используй /task для создания", show_alert=True)
@dp.callback_query(F.data=="habits_list")
async def cb_habits(call:CallbackQuery):
    habits = await get_habits(call.from_user.id)
    text = "🔁 Привычки:\n" + "\n".join([f"• {h['name']}: {h['streak']} дн." for h in habits]) if habits else "Нет привычек"
    await call.message.edit_text(text, reply_markup=main_menu_keyboard())
@dp.callback_query(F.data=="reminders_list")
async def cb_reminders(call:CallbackQuery):
    await call.message.answer("⏰ Напоминания: напиши 'напомни [что] [когда]'\nПример: 'напомни выпить воды через 2 часа'"); await call.answer()
@dp.callback_query(F.data=="stats")
async def cb_stats(call:CallbackQuery):
    s = await get_task_stats(call.from_user.id)
    await call.answer(f"📊 Задачи: {s['pending'] or 0} активных, {s['completed'] or 0} выполнено", show_alert=True)
@dp.callback_query(F.data=="profile_show")
async def cb_profile(call:CallbackQuery):
    p = await get_profile(call.from_user.id)
    text = f"👤 {p['name']}" + (f", {p['age']} лет" if p and p['age'] else "") + (f", {p['gender']}" if p and p['gender'] else "") if p and p['name'] else "Нет данных"
    await call.answer(text, show_alert=True)
@dp.callback_query(F.data=="help_show")
async def cb_help(call:CallbackQuery):
    await call.message.answer("📋 **Справка:**\n• Задачи: /task, /tasks\n• Привычки: /habits\n• Погода: /weather [город]\n• Курс: /currency\n• Афиша: /cinema [город]\n\nИли просто пиши как другу 💬", parse_mode="Markdown"); await call.answer()
@dp.callback_query(F.data=="ext_weather")
async def cb_ext_weather(call:CallbackQuery):
    profile = await get_profile(call.from_user.id); city = profile.get("name") if profile and profile.get("name") else CITY_DEFAULT
    await call.message.answer(f"🌤 Погода в {city}:", reply_markup=external_link_keyboard(get_weather_link(city), f"Яндекс.Погода: {city}")); await call.answer()
@dp.callback_query(F.data=="ext_currency")
async def cb_ext_currency(call:CallbackQuery):
    await call.message.answer("💱 Курс валют ЦБ РФ:", reply_markup=external_link_keyboard(get_currency_link(), "Открыть ЦБ")); await call.answer()
@dp.callback_query(F.data=="ext_cinema")
async def cb_ext_cinema(call:CallbackQuery):
    profile = await get_profile(call.from_user.id); city = profile.get("name") if profile and profile.get("name") else CITY_DEFAULT
    await call.message.answer(f"🎬 Афиша: {city}", reply_markup=external_link_keyboard(get_cinema_link(city), f"Афиша: {city}")); await call.answer()
@dp.callback_query(F.data=="ext_news")
async def cb_ext_news(call:CallbackQuery):
    await call.message.answer("📰 Новости:", reply_markup=external_link_keyboard(get_news_link(), "Яндекс.Новости")); await call.answer()
@dp.callback_query(F.data.startswith("task_complete_"))
async def cb_task_done(call:CallbackQuery):
    tid = int(call.data.split("_")[-1]); await complete_task(call.from_user.id, tid); await call.answer("✅ Готово!", show_alert=True); await call.message.delete()
@dp.callback_query(F.data.startswith("task_delete_"))
async def cb_task_del(call:CallbackQuery):
    tid = int(call.data.split("_")[-1]); await delete_task(call.from_user.id, tid); await call.answer("🗑 Удалено", show_alert=True); await call.message.delete()

# ======================
#  УМНЫЙ ПАРСЕР КОМАНД (русские слова)
# ======================
RU_COMMANDS = {
    "меню":"show_menu","главное меню":"show_menu","кнопки":"show_menu",
    "задачи":"list_tasks","мои задачи":"list_tasks","список дел":"list_tasks",
    "новая задача":"create_task","добавить задачу":"create_task",
    "привычки":"list_habits","мои привычки":"list_habits",
    "погода":"ext_weather","погода в":"ext_weather","как погода":"ext_weather",
    "курс":"ext_currency","курс доллара":"ext_currency","валюта":"ext_currency",
    "кино":"ext_cinema","афиша":"ext_cinema","что в кино":"ext_cinema",
    "новости":"ext_news","что нового":"ext_news",
    "профиль":"profile_show","обо мне":"profile_show",
    "помощь":"help_show","что умеешь":"help_show",
}
def parse_ru_command(text:str) -> str|None:
    text_lower = text.lower().strip()
    for keyword,cmd in RU_COMMANDS.items():
        if keyword in text_lower: return cmd
    return None

# ======================
#  ОСНОВНОЙ ЧАТ
# ======================
@dp.message()
async def chat(msg:Message, state:FSMContext):
    if not msg.text or await state.get_state(): return
    uid = msg.from_user.id; text = msg.text.strip()
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO users(user_id,name) VALUES ($1,$2) ON CONFLICT DO NOTHING", uid, msg.from_user.first_name)
    await update_last_activity(uid)
    profile = await get_profile(uid)
    if not profile or not profile["name"]:
        name,age,gender = extract_profile(text)
        if name or age or gender:
            await save_profile(uid,name,age,gender); profile = {"name":name,"age":age,"gender":gender}
            await msg.answer(f"Запомнил: {name}" if name else "Запомнил тебя"); return
    memory = await get_memory(uid); mood = await get_mood(uid); habits = await get_habits(uid); tasks_count = (await get_task_stats(uid))["pending"] or 0
    await save_memory(uid,"user",text); await update_emotion(uid,text)
    
    # 🔥 Парсер русских команд
    cmd = parse_ru_command(text)
    if cmd:
        if cmd=="show_menu": await msg.answer("📋 Меню:", reply_markup=main_menu_keyboard()); return
        elif cmd=="list_tasks": await cmd_tasks(msg); return
        elif cmd=="create_task": await cmd_task_start(msg, state); return
        elif cmd=="list_habits": await cb_habits_list(msg); return
        elif cmd=="ext_weather":
            city_match = re.search(r"в ([\w\s\-]+?)(?:\?|$)", text.lower())
            city = city_match.group(1).strip() if city_match else CITY_DEFAULT
            await msg.answer(f"🌤 Погода в {city}:", reply_markup=external_link_keyboard(get_weather_link(city), f"Яндекс.Погода: {city}")); return
        elif cmd=="ext_currency": await cmd_currency(msg); return
        elif cmd=="ext_cinema":
            city_match = re.search(r"в ([\w\s\-]+?)(?:\?|$)", text.lower())
            city = city_match.group(1).strip() if city_match else CITY_DEFAULT
            await msg.answer(f"🎬 Афиша: {city}", reply_markup=external_link_keyboard(get_cinema_link(city), f"Афиша: {city}")); return
        elif cmd=="ext_news": await cb_ext_news(msg); return
        elif cmd=="profile_show": await cmd_profile(msg); return
        elif cmd=="help_show": await cmd_help(msg); return
    
    grok = await call_grok_analysis(text, memory, profile)
    
    # Если ссылка — отправляем сразу
    if grok.get("external_link"):
        await msg.answer(f"{grok.get('external_link_label','Открыть')}:", reply_markup=external_link_keyboard(grok["external_link"], grok.get("external_link_label","Открыть"))); return
    
    if grok.get("is_task_creation") or any(w in text.lower() for w in ["задач","сделай","надо"]):
        await msg.answer("Создать задачу? Напиши /task или нажми кнопку 👇", reply_markup=main_menu_keyboard()); return
    
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO message_tags(user_id,message_id,tags,topic) VALUES ($1,$2,$3,$4)", uid, msg.message_id, grok.get("tags",[]), grok.get("topic"))
    
    # 🔥 OpenAI — основной ответ
    answer = await call_openai_primary(text, grok, profile, mood, habits, memory, tasks_count)
    await msg.answer(answer)

# ======================
#  ПЛАНИРОВЩИК
# ======================
async def morning_ping():
    async with db_pool.acquire() as conn: users = await conn.fetch("SELECT user_id FROM users")
    for u in users:
        try: await bot.send_message(u["user_id"], "☀️ Доброе утро. План на день?")
        except: pass
async def habit_check():
    async with db_pool.acquire() as conn: habits = await conn.fetch("SELECT id,user_id,name,last_done FROM habits")
    now = datetime.now().date()
    for h in habits:
        if h["last_done"] and datetime.fromisoformat(str(h["last_done"])).date() < now - timedelta(days=1):
            try: await bot.send_message(h["user_id"], f"🔁 '{h['name']}' пропущена")
            except: pass
async def task_reminder_check():
    async with db_pool.acquire() as conn:
        tasks = await conn.fetch("SELECT user_id,title,due_date FROM tasks WHERE status='pending' AND due_date IS NOT NULL AND due_date <= NOW() + INTERVAL '1 hour' AND due_date > NOW() - INTERVAL '1 hour'")
    for task in tasks:
        try: await bot.send_message(task["user_id"], f"⏰ Скоро дедлайн: {task['title']}")
        except: pass
async def inactivity_check():
    async with db_pool.acquire() as conn: users = await conn.fetch("SELECT user_id FROM last_activity WHERE last_time < NOW() - INTERVAL '24 hours'")
    for u in users:
        try: await bot.send_message(u["user_id"], "Давно не виделись. Как дела?")
        except: pass

# ======================
#  ЗАПУСК
# ======================
async def main():
    loop = asyncio.get_running_loop(); stop_event = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT): loop.add_signal_handler(sig, stop_event.set)
    await init_db()
    logging.info("✅ AssistEmpat v2.3 запущен (OpenAI-primary + smart commands)")
    scheduler.start()
    scheduler.add_job(morning_ping, "cron", hour=9)
    scheduler.add_job(habit_check, "interval", hours=6)
    scheduler.add_job(task_reminder_check, "interval", minutes=30)
    scheduler.add_job(inactivity_check, "interval", hours=24)
    await bot.delete_webhook(drop_pending_updates=True)
    await asyncio.sleep(1)
    polling_task = asyncio.create_task(dp.start_polling(bot))
    await asyncio.wait([polling_task, asyncio.create_task(stop_event.wait())], return_when=asyncio.FIRST_COMPLETED)
    logging.info("👋 Бот остановлен")
    await db_pool.close(); await bot.session.close()

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: logging.info("👋 Остановлено пользователем")