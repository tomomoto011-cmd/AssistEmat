# =========================================================
#  ASSISTEMPAT BOT v3.2 (Full APIs + Profile Edit)
#  Архитектура: Grok (анализ) + OpenAI (универсальный ответ)
#  Утилиты: Задачи (полноценные) / Заметки / Календарь / Профиль
#  Внешние данные: OpenWeather, TMDB, ExchangeRate, NewsAPI
# =========================================================

import asyncio
import logging
import os
import re
import signal
import json
import urllib.parse
import hashlib
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
from aiohttp import web

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ======================
#  КОНФИГУРАЦИЯ
# ======================
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
GROK_API_KEY = os.getenv("GROK_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
QWEN_API_KEY = os.getenv("QWEN_API_KEY")
CITY_DEFAULT = os.getenv("CITY_DEFAULT", "Москва")
ALLOWED_USERS = os.getenv("ALLOWED_USERS", "")
HEALTH_PORT = int(os.getenv("PORT", os.getenv("RAILWAY_PUBLIC_PORT", 8080)))

# 🔥 API-ключи для внешних данных
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
TMDB_API_KEY = os.getenv("TMDB_API_KEY")
EXCHANGERATE_API_KEY = os.getenv("EXCHANGERATE_API_KEY")
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
scheduler = AsyncIOScheduler(timezone=timezone.utc)
db_pool = None

# ======================
#  🔥 УМНОЕ ИСПРАВЛЕНИЕ РАСКЛАДКИ
# ======================
LAYOUT_MAP = {
    'q':'й','w':'ц','e':'у','r':'к','t':'е','y':'н','u':'г','i':'ш','o':'щ','p':'з','[':'х',']':'ъ',
    'a':'ф','s':'ы','d':'в','f':'а','g':'п','h':'р','j':'о','k':'л','l':'д',';':'ж',"'":'э',
    'z':'я','x':'ч','c':'с','v':'м','b':'и','n':'т','m':'ь',',':'б','.':'ю','/':'.'
}

def fix_layout(text: str) -> str:
    if not text or len(text) < 4: return text
    safe_words = ['меню', 'инлайн', 'задача', 'привычк', 'напомн', 'погод', 'кино', 'новост', 'курс', 'профиль', 'помощь', 'статистик', 'заметк', 'календар']
    if any(sw in text.lower() for sw in safe_words): return text
    if text.isascii() and text.isalpha():
        converted = ''.join(LAYOUT_MAP.get(c.lower(), c) for c in text)
        if any('\u0400' <= c <= '\u04FF' for c in converted): return converted
    return text

# ======================
#  🔥 ДЕТЕКЦИЯ КРИЗИСОВ
# ======================
CRISIS_KEYWORDS = ["суицид", "умер", "не хочу жить", "убить себя", "паник", "не могу дышать", "сердце", "давление"]
FRUSTRATION_KEYWORDS = ["скотина", "бесчувственный", "ты тупой", "опять", "достал", "хватит", "бесит"]
RESET_KEYWORDS = ["привет", "здравствуй", "отбой", "стоп", "новое", "другое", "меню", "пока"]

def is_crisis(text: str) -> tuple[bool, str]:
    text_lower = text.lower()
    if any(w in text_lower for w in ["суицид", "умер", "не хочу жить", "убить себя"]): return True, "critical"
    if any(w in text_lower for w in ["паник", "не могу дышать", "сердце", "давление"]): return True, "medical_emergency"
    return False, ""

def should_reset_context(text: str) -> bool:
    return any(kw in text.lower().strip() for kw in RESET_KEYWORDS)

# ======================
#  🔥 БАЗА ДАННЫХ
# ======================
async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    async with db_pool.acquire() as conn:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users(user_id BIGINT PRIMARY KEY, name TEXT, age INTEGER, gender TEXT, created_at TIMESTAMP DEFAULT NOW());
        CREATE TABLE IF NOT EXISTS memory(id SERIAL PRIMARY KEY, user_id BIGINT, role TEXT, content TEXT, created_at TIMESTAMP DEFAULT NOW());
        CREATE TABLE IF NOT EXISTS reminders(id SERIAL PRIMARY KEY, user_id BIGINT, text TEXT, remind_at TIMESTAMP);
        CREATE TABLE IF NOT EXISTS habits(id SERIAL PRIMARY KEY, user_id BIGINT, name TEXT, streak INTEGER DEFAULT 0, last_done DATE);
        CREATE TABLE IF NOT EXISTS emotions(id SERIAL PRIMARY KEY, user_id BIGINT, mood TEXT, created_at TIMESTAMP DEFAULT NOW());
        CREATE TABLE IF NOT EXISTS last_activity(user_id BIGINT PRIMARY KEY, last_time TIMESTAMP DEFAULT NOW());
        CREATE TABLE IF NOT EXISTS message_tags(id SERIAL PRIMARY KEY, user_id BIGINT, message_id BIGINT, tags TEXT[], topic TEXT, created_at TIMESTAMP DEFAULT NOW());
        CREATE TABLE IF NOT EXISTS response_log(id SERIAL PRIMARY KEY, user_id BIGINT, content_hash TEXT, created_at TIMESTAMP DEFAULT NOW());
        CREATE TABLE IF NOT EXISTS notes(id SERIAL PRIMARY KEY, user_id BIGINT, content TEXT, created_at TIMESTAMP DEFAULT NOW(), tags TEXT[]);
        CREATE TABLE IF NOT EXISTS calendar_events(id SERIAL PRIMARY KEY, user_id BIGINT, title TEXT, description TEXT, event_date TIMESTAMP, reminder_before INTERVAL, created_at TIMESTAMP DEFAULT NOW());
        """)
        
        # 🔥 Полноценная таблица задач
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks(
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            title TEXT NOT NULL,
            description TEXT,
            status TEXT DEFAULT 'pending',
            priority TEXT DEFAULT 'medium',
            due_date TIMESTAMP,
            category TEXT DEFAULT 'general',
            tags TEXT[],
            parent_id INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
            recurrence TEXT,
            attachments TEXT[],
            created_at TIMESTAMP DEFAULT NOW(),
            completed_at TIMESTAMP
        );
        """)
        
        # 🔥 Профиль с городом
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS profile(
            user_id BIGINT PRIMARY KEY,
            name TEXT,
            age INTEGER,
            gender TEXT,
            city TEXT DEFAULT 'Москва',
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );
        """)
        
        # Миграции
        await conn.execute("ALTER TABLE reminders ADD COLUMN IF NOT EXISTS remind_at TIMESTAMP")
        await conn.execute("ALTER TABLE habits ADD COLUMN IF NOT EXISTS streak INTEGER DEFAULT 0")
        await conn.execute("ALTER TABLE habits ADD COLUMN IF NOT EXISTS last_done DATE")
        await conn.execute("ALTER TABLE notes ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW()")
        await conn.execute("ALTER TABLE notes ADD COLUMN IF NOT EXISTS tags TEXT[]")
        await conn.execute("ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS reminder_before INTERVAL")
        await conn.execute("ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW()")
        await conn.execute("ALTER TABLE response_log ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW()")
        
        # Миграции для задач
        await conn.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS category TEXT DEFAULT 'general'")
        await conn.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS tags TEXT[]")
        await conn.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS parent_id INTEGER REFERENCES tasks(id) ON DELETE CASCADE")
        await conn.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS recurrence TEXT")
        await conn.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS attachments TEXT[]")
        await conn.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP")
        
        # 🔥 Миграция для профиля
        await conn.execute("ALTER TABLE profile ADD COLUMN IF NOT EXISTS city TEXT DEFAULT 'Москва'")
        await conn.execute("ALTER TABLE profile ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW()")
        
        # Индексы
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_user ON memory(user_id, created_at DESC)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_habits_user ON habits(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_reminders_time ON reminders(remind_at)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id, status)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_category ON tasks(user_id, category)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(user_id, parent_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_response_log ON response_log(user_id, created_at DESC)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_notes_user ON notes(user_id, created_at DESC)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_calendar_user ON calendar_events(user_id, event_date)")
        
    logging.info("✅ PostgreSQL initialized + profile with city + full tasks")

# ======================
#  🔥 ANTI-LOOP
# ======================
async def is_duplicate_response(uid: int, new_text: str) -> bool:
    if not new_text or len(new_text.strip()) < 5: return False
    new_hash = hashlib.md5(new_text.strip().lower().encode()).hexdigest()
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT content_hash FROM response_log WHERE user_id=$1 ORDER BY created_at DESC LIMIT 3", uid)
        if new_hash in [r["content_hash"] for r in rows]: return True
        await conn.execute("INSERT INTO response_log(user_id, content_hash) VALUES ($1, $2)", uid, new_hash)
        await conn.execute("DELETE FROM response_log WHERE user_id=$1 AND id NOT IN (SELECT id FROM response_log WHERE user_id=$1 ORDER BY created_at DESC LIMIT 20)", uid)
    return False

# ======================
#  🔥 ВНЕШНИЕ ДАННЫЕ (API + фоллбэк)
# ======================
async def get_weather_data(city: str) -> dict | None:
    if not OPENWEATHER_API_KEY: return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get("https://api.openweathermap.org/data/2.5/weather",
                params={"q": city, "appid": OPENWEATHER_API_KEY, "units": "metric", "lang": "ru"})
            r.raise_for_status()
            data = r.json()
            return {
                "temp": data["main"]["temp"], "feels_like": data["main"]["feels_like"],
                "description": data["weather"][0]["description"], "humidity": data["main"]["humidity"],
                "wind": data["wind"]["speed"], "icon": data["weather"][0]["icon"]
            }
    except Exception as e:
        logging.warning(f"Weather API error: {e}")
        return None

def get_weather_link(city: str) -> str:
    return f"https://yandex.ru/pogoda/{urllib.parse.quote(city)}"

async def get_currency_data(base="RUB") -> dict | None:
    if not EXCHANGERATE_API_KEY: return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"https://v6.exchangerate-api.com/v6/{EXCHANGERATE_API_KEY}/latest/{base}")
            r.raise_for_status()
            data = r.json()
            return data.get("conversion_rates", {})
    except Exception as e:
        logging.warning(f"Currency API error: {e}")
        return None

def get_currency_link() -> str:
    return "https://www.cbr.ru/currency_base/daily/"

async def get_cinema_data(city: str) -> list | None:
    if not TMDB_API_KEY: return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # TMDB не фильтрует по городу, показываем популярные фильмы
            r = await client.get("https://api.themoviedb.org/3/movie/now_playing",
                params={"api_key": TMDB_API_KEY, "language": "ru-RU", "page": 1})
            r.raise_for_status()
            data = r.json()
            return [{"title": m["title"], "rating": m.get("vote_average", 0)} for m in data.get("results", [])[:5]]
    except Exception as e:
        logging.warning(f"Cinema API error: {e}")
        return None

def get_cinema_link(city: str = "Москва") -> str:
    return f"https://afisha.yandex.ru/{urllib.parse.quote(city)}/cinema/"

async def get_news_data(category="general", lang="ru") -> list | None:
    if not NEWSAPI_KEY: return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get("https://newsapi.org/v2/top-headlines",
                params={"apiKey": NEWSAPI_KEY, "country": "ru", "language": lang, "pageSize": 5})
            r.raise_for_status()
            data = r.json()
            return [{"title": a["title"], "url": a["url"]} for a in data.get("articles", [])[:5]]
    except Exception as e:
        logging.warning(f"News API error: {e}")
        return None

def get_news_link() -> str:
    return "https://news.yandex.ru/"

def get_translate_link() -> str:
    return "https://translate.yandex.ru/"

# ======================
#  🔥 ЗАДАЧИ (ПОЛНОЦЕННЫЕ)
# ======================
async def create_task(uid, title, description=None, priority="medium", due_date=None, category="general", tags=None, parent_id=None, recurrence=None, attachments=None):
    async with db_pool.acquire() as conn:
        return await conn.fetchval("""
            INSERT INTO tasks(user_id, title, description, priority, due_date, category, tags, parent_id, recurrence, attachments)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) RETURNING id
        """, uid, title, description, priority, due_date, category, tags, parent_id, recurrence, attachments)

async def get_tasks(uid, status="pending", category=None, parent_id=None):
    async with db_pool.acquire() as conn:
        query = "SELECT id, title, description, priority, due_date, category, tags, parent_id, recurrence, attachments, created_at FROM tasks WHERE user_id=$1 AND status=$2"
        params = [uid, status]
        if category:
            query += " AND category=$3"; params.append(category)
        if parent_id is not None:
            query += " AND parent_id=$3" if not category else " AND parent_id=$4"; params.append(parent_id)
        query += " ORDER BY created_at DESC"
        return await conn.fetch(query, *params)

async def get_task_by_id(uid, task_id):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM tasks WHERE id=$1 AND user_id=$2", task_id, uid)

async def complete_task(uid, task_id):
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE tasks SET status='completed', completed_at=NOW() WHERE id=$1 AND user_id=$2", task_id, uid)

async def delete_task(uid, task_id):
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM tasks WHERE id=$1 AND user_id=$2", task_id, uid)

async def get_task_stats(uid):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow("""
            SELECT COUNT(*) FILTER (WHERE status='pending') as pending,
                   COUNT(*) FILTER (WHERE status='completed') as completed,
                   COUNT(*) FILTER (WHERE category='work') as work,
                   COUNT(*) FILTER (WHERE category='personal') as personal,
                   COUNT(*) FILTER (WHERE category='shopping') as shopping
            FROM tasks WHERE user_id=$1
        """, uid)

async def get_subtasks(uid, parent_id):
    async with db_pool.acquire() as conn:
        return await conn.fetch("SELECT id, title, status, priority FROM tasks WHERE user_id=$1 AND parent_id=$2 ORDER BY created_at", uid, parent_id)

# ======================
#  🔥 ЗАМЕТКИ / КАЛЕНДАРЬ / ПРИВЫЧКИ
# ======================
async def create_note(uid, content, tags=None):
    async with db_pool.acquire() as conn:
        return await conn.fetchval("INSERT INTO notes(user_id, content, tags) VALUES ($1, $2, $3) RETURNING id", uid, content, tags)
async def get_notes(uid, limit=10, search=None):
    async with db_pool.acquire() as conn:
        if search:
            return await conn.fetch("SELECT id, content, tags, created_at FROM notes WHERE user_id=$1 AND (content ILIKE $2 OR tags::text ILIKE $2) ORDER BY created_at DESC LIMIT $3", uid, f"%{search}%", limit)
        return await conn.fetch("SELECT id, content, tags, created_at FROM notes WHERE user_id=$1 ORDER BY created_at DESC LIMIT $2", uid, limit)
async def delete_note(uid, note_id):
    async with db_pool.acquire() as conn: await conn.execute("DELETE FROM notes WHERE id=$1 AND user_id=$2", note_id, uid)

async def create_calendar_event(uid, title, description, event_date, reminder_before=None):
    async with db_pool.acquire() as conn:
        return await conn.fetchval("INSERT INTO calendar_events(user_id, title, description, event_date, reminder_before) VALUES ($1,$2,$3,$4,$5) RETURNING id", uid, title, description, event_date, reminder_before)
async def get_calendar_events(uid, from_date=None, limit=10):
    async with db_pool.acquire() as conn:
        query = "SELECT id, title, description, event_date, reminder_before FROM calendar_events WHERE user_id=$1"
        params = [uid]
        if from_date:
            query += " AND event_date >= $2 ORDER BY event_date ASC LIMIT $3"; params.extend([from_date, limit])
        else:
            query += " ORDER BY event_date ASC LIMIT $2"; params.append(limit)
        return await conn.fetch(query, *params)

async def get_habits(uid):
    async with db_pool.acquire() as conn: return await conn.fetch("SELECT id,name,streak,last_done FROM habits WHERE user_id=$1", uid)
async def create_habit(uid, name):
    async with db_pool.acquire() as conn:
        if not await conn.fetchval("SELECT id FROM habits WHERE user_id=$1 AND name=$2", uid, name):
            await conn.execute("INSERT INTO habits(user_id,name) VALUES ($1,$2)", uid, name)

# ======================
#  🔥 ПРОФИЛЬ
# ======================
async def get_profile(uid):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT name, age, gender, city FROM profile WHERE user_id=$1", uid)
        return dict(row) if row else None

async def save_profile(uid, name=None, age=None, gender=None, city=None):
    async with db_pool.acquire() as conn:
        updates, params, idx = [], [uid], 2
        for field, value in [("name", name), ("age", age), ("gender", gender), ("city", city)]:
            if value is not None:
                updates.append(f"{field}=${idx}"); params.append(value); idx += 1
        if updates:
            updates.append("updated_at=NOW()")
            query = f"INSERT INTO profile(user_id,name,age,gender,city) VALUES ($1,$2,$3,$4,$5) ON CONFLICT(user_id) DO UPDATE SET {', '.join(updates)}"
            await conn.execute(query, *params)

# ======================
#  INLINE КЛАВИАТУРЫ
# ======================
def main_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Задачи", callback_data="tasks_list"), InlineKeyboardButton(text="📝 Заметки", callback_data="notes_list")],
        [InlineKeyboardButton(text="🔁 Привычки", callback_data="habits_list"), InlineKeyboardButton(text="📅 Календарь", callback_data="calendar_list")],
        [InlineKeyboardButton(text="⏰ Напомнить", callback_data="reminders_list"), InlineKeyboardButton(text="📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton(text="🌤 Погода", callback_data="ext_weather"), InlineKeyboardButton(text="💱 Курс", callback_data="ext_currency")],
        [InlineKeyboardButton(text="🎬 Афиша", callback_data="ext_cinema"), InlineKeyboardButton(text="📰 Новости", callback_data="ext_news")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile_show"), InlineKeyboardButton(text="❓ Помощь", callback_data="help_show")],
    ])

def profile_edit_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Имя", callback_data="profile_edit_name"), InlineKeyboardButton(text="✏️ Возраст", callback_data="profile_edit_age")],
        [InlineKeyboardButton(text="✏️ Город", callback_data="profile_edit_city"), InlineKeyboardButton(text="✏️ Пол", callback_data="profile_edit_gender")],
        [InlineKeyboardButton(text="✅ Готово", callback_data="profile_done")]
    ])

def task_category_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💼 Работа", callback_data="cat_work"), InlineKeyboardButton(text="🏠 Личное", callback_data="cat_personal"), InlineKeyboardButton(text="🛒 Покупки", callback_data="cat_shopping")],
        [InlineKeyboardButton(text="🔧 Другое", callback_data="cat_general")]
    ])

def task_priority_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔴 Высокий", callback_data="pri_high"), InlineKeyboardButton(text="🟡 Средний", callback_data="pri_medium"), InlineKeyboardButton(text="🟢 Низкий", callback_data="pri_low")]
    ])

def task_recurrence_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Ежедневно", callback_data="rec_daily"), InlineKeyboardButton(text="📅 Еженедельно", callback_data="rec_weekly"), InlineKeyboardButton(text="🗓 Ежемесячно", callback_data="rec_monthly")],
        [InlineKeyboardButton(text="❌ Без повтора", callback_data="rec_none")]
    ])

def task_actions_keyboard(task_id, has_subtasks=False):
    buttons = [[InlineKeyboardButton(text="✅ Выполнить", callback_data=f"task_complete_{task_id}")]]
    if has_subtasks: buttons.append([InlineKeyboardButton(text="📝 Подзадачи", callback_data=f"task_subtasks_{task_id}")])
    buttons.append([InlineKeyboardButton(text="🗑 Удалить", callback_data=f"task_delete_{task_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def note_actions_keyboard(note_id):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🗑 Удалить заметку", callback_data=f"note_delete_{note_id}")]])

def external_link_keyboard(link: str, label: str = "Открыть"):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"🔗 {label}", url=link)]])

# ======================
#  FSM
# ======================
class TaskFSM(StatesGroup):
    title = State(); description = State(); priority = State(); due_date = State()
    category = State(); tags = State(); recurrence = State(); attachments = State()
class NoteFSM(StatesGroup): content=State(); tags=State()
class CalendarFSM(StatesGroup): title=State(); description=State(); event_date=State()
class ProfileEditFSM(StatesGroup): field=State(); value=State()

# ======================
#  GROK API
# ======================
async def call_grok_analysis(text: str, history: list = None, profile: dict = None) -> dict:
    if not GROK_API_KEY:
        return {"topic":"general","tags":[],"intent":"chat","emotional_tone":"neutral","action_items":[],"priority":"medium","refined_prompt":text,"is_task_creation":False,"external_link_needed":None,"external_link":None}
    try:
        history_ctx = "\n".join([f"{m['role']}: {m['content']}" for m in (history or [])[-5:]])
        user_info = f"Имя:{profile.get('name')},Возраст:{profile.get('age')},Пол:{profile.get('gender')},Город:{profile.get('city')}" if profile else ""
        prompt = f"""Анализируй сообщение. Верни ТОЛЬКО JSON:
Пользователь:{user_info}
Сообщение:{text}
История:{history_ctx}
Формат:{{"topic":"работа|учеба|здоровье|отношения|эмоции|быт|задача|заметка|календарь|погода|кино|финансы|новости|кризис|другое","tags":[],"intent":"chat|question|task|request_help|create_task|create_note|create_event|request_external_link|crisis_support","emotional_tone":"neutral|positive|negative|stressed|tired|distressed|angry","action_items":[],"priority":"low|medium|high|critical","refined_prompt":"...","is_task_creation":true/false,"external_link_needed":null|"weather"|"currency"|"cinema"|"news"|"translate","external_link_params":{{"city":"..."}} или null}}"""
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post("https://api.x.ai/v1/chat/completions", headers={"Authorization":f"Bearer {GROK_API_KEY}","Content-Type":"application/json"}, json={"model":"grok-beta","messages":[{"role":"user","content":prompt}],"temperature":0.3})
            r.raise_for_status()
            result = r.json()["choices"][0]["message"]["content"].strip()
            if result.startswith("```json"): result = result.replace("```json","").replace("```","").strip()
            data = json.loads(result)
            city = profile.get("city") if profile else CITY_DEFAULT
            if data.get("external_link_needed")=="weather":
                data["external_link"] = get_weather_link(city); data["external_link_label"] = f"Погода в {city}"
            elif data.get("external_link_needed")=="currency":
                data["external_link"] = get_currency_link(); data["external_link_label"] = "Курс валют ЦБ"
            elif data.get("external_link_needed")=="cinema":
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
#  🔥 OPENAI (УНИВЕРСАЛЬНЫЙ ПРОМПТ)
# ======================
async def call_openai_primary(user_text, grok_analysis, profile, mood, habits, memory, tasks_count=0):
    if not OPENROUTER_API_KEY: return await call_qwen_fallback(user_text, grok_analysis, profile, mood, habits, memory, tasks_count)
    
    user_name = profile.get("name") if profile else ""
    habit_list = ", ".join([h[0] for h in habits]) if habits else "не заданы"
    city = profile.get("city") if profile else CITY_DEFAULT
    link_context = ""
    if grok_analysis.get("external_link"):
        link = grok_analysis["external_link"]
        label = grok_analysis.get("external_link_label", "Открыть")
        link_context = f"\n[Ссылка: {label} — {link}]"
    
    system_prompt = f"""Ты — личный помощник {user_name if user_name else 'пользователя'}.
Контекст: настроение={mood}, тема={grok_analysis.get('topic')}, привычки={habit_list}, задач={tasks_count}, город={city}{link_context}

ПРАВИЛА:
1. Практичность: Давай конкретные советы ("Приложи холод на 15-20 минут")
2. Эмпатия: Если стресс — сначала поддержка, потом советы
3. Краткость: 2-4 предложения, по делу
4. Естественность: Без "Привет! Чем могу помочь?", "Не стесняйся"
5. Без повторов: Никогда не повторяй один ответ дважды
6. Смена темы: Если "привет"/"отбой"/"стоп" — забудь старое
7. Юмор: Можно подшутить (доброжелательно), если уместно
8. Кризисы: При серьёзных проблемах — мягко направляй к специалистам
9. Утилиты: Если пользователь просит меню/инлайны/заметки/календарь — покажи кнопки или помоги создать
10. Город: Используй город из профиля ({city}) для погоды/афиши

Примеры ХОРОШИХ ответов:
- "В {city} сейчас +12°, дождь. Возьми зонт. 🌧"
- "Понимаю, что тяжело. Расскажи, что именно произошло? Давай разберёмся."
- "Да, босс! Записал: выпить воду через 2 часа. Напомню! ✅"

Отвечай естественно, как в обычном чате."""
    
    filtered_memory = []
    seen = set()
    for msg in reversed(memory[-12:]):
        content = msg["content"].strip()
        if content and len(content) > 3 and content not in seen:
            filtered_memory.insert(0, msg)
            seen.add(content)
        if len(filtered_memory) >= 6: break
    
    context = "\n".join([f"{m['role']}: {m['content']}" for m in filtered_memory])
    messages = [{"role":"system","content":system_prompt},{"role":"user","content":f"Диалог:\n{context}\n\nТекущее:{user_text}"}]
    
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post("https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization":f"Bearer {OPENROUTER_API_KEY}","Content-Type":"application/json"},
                json={"model":"openai/gpt-4o-mini","messages":messages,"temperature":0.7,"max_tokens":400}, timeout=20)
            r.raise_for_status()
            answer = r.json()["choices"][0]["message"]["content"].strip()
            if await is_duplicate_response(profile.get("user_id") if profile else 0, answer):
                return get_fallback_response(user_text, mood)
            return answer
    except Exception as e:
        logging.error(f"OpenRouter error: {e}")
        return get_fallback_response(user_text, mood)

def get_fallback_response(user_text: str, mood: str) -> str:
    if mood == "грусть": return "Понимаю, что непросто. Расскажи подробнее? Я слушаю. 🤍"
    if mood == "тревога": return "Всё будет хорошо. Что именно беспокоит? Давай разберёмся."
    if mood == "усталость": return "Отдохни. Не перегружай себя. 🫂"
    if any(w in user_text.lower() for w in ['меню', 'инлайн', 'кнопк', 'замет', 'календар', 'утилит']):
        return "📋 Меню доступно по кнопкам внизу! Или напиши: /help для списка команд."
    return "Понял. Что ещё нужно?"

async def call_qwen_fallback(user_text, grok_analysis, profile, mood, habits, memory, tasks_count=0):
    if not QWEN_API_KEY: return "Не могу сейчас ответить. Попробуй позже."
    user_name = profile.get("name") if profile else ""
    system_prompt = f"Ты — помощник {user_name}. Отвечай кратко, по делу. Настроение:{mood}. Тема:{grok_analysis.get('topic')}."
    context = "\n".join([f"{m['role']}: {m['content']}" for m in memory[-6:]])
    messages = [{"role":"system","content":system_prompt},{"role":"user","content":f"{context}\n\n{user_text}"}]
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post("https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
                headers={"Authorization":f"Bearer {QWEN_API_KEY}"},
                json={"model":"qwen-max","messages":messages,"temperature":0.7}, timeout=15)
            r.raise_for_status()
            return r.json()["output"]["text"].strip()
    except: return "Не могу сейчас ответить. Попробуй позже."

# ======================
#  ВСПОМОГАТЕЛЬНЫЕ
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
    async with db_pool.acquire() as conn: await conn.execute("INSERT INTO emotions(user_id,mood) VALUES ($1,$2)", uid, mood)
async def get_mood(uid):
    async with db_pool.acquire() as conn:
        row = await conn.fetchval("SELECT mood FROM emotions WHERE user_id=$1 ORDER BY created_at DESC LIMIT 1", uid)
        return row or "нейтральное"
async def update_last_activity(uid):
    async with db_pool.acquire() as conn: await conn.execute("INSERT INTO last_activity(user_id,last_time) VALUES ($1,NOW()) ON CONFLICT(user_id) DO UPDATE SET last_time=NOW()", uid)
def extract_profile(text):
    text = text.lower(); name=age=gender=city=None
    m = re.search(r"меня зовут (\w+)", text)
    if m: name = m.group(1).capitalize()
    m = re.search(r"мне (\d{1,2})", text)
    if m: age = int(m.group(1))
    if "я парень" in text or "я мужчина" in text: gender = "male"
    if "я девушка" in text or "я женщина" in text: gender = "female"
    m = re.search(r"город[ :]+([\w\s\-]+?)(?:\?|$)", text)
    if m: city = m.group(1).strip()
    return name, age, gender, city
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
    await msg.answer("""📋 **Команды и утилиты:**
📝 Заметки: /note [текст] или кнопка "📝 Заметки"
📅 Календарь: /event [название] [дата] или кнопка "📅 Календарь"
📋 Задачи: /task или кнопка "📋 Задачи"
  • Подзадачи: /subtask [родитель] • Повторы: /recurring [задача] [ежедневно/еженедельно]
  • Категории: работа/личное/покупки
🔁 Привычки: /habit [название] или кнопка "🔁 Привычки"
⏰ Напоминания: "напомни [что] [когда]"
🌤 Погода: /weather [город] или кнопка (использует город из профиля)
💱 Курс: /currency или кнопка
🎬 Афиша: /cinema [город] или кнопка (использует город из профиля)
📰 Новости: /news или кнопка
👤 Профиль: /profile (просмотр) | /profile edit (редактирование)
📊 Статистика: /stats

Или просто нажми кнопку внизу 👇""", parse_mode="Markdown", reply_markup=main_menu_keyboard())

@dp.message(Command("profile"))
async def cmd_profile(msg:Message, state:FSMContext):
    p = await get_profile(msg.from_user.id)
    if not p:
        await msg.answer("Нет данных. Напиши: 'меня зовут...', 'мне 25', 'город: СПб'")
        return
    text = f"👤 **Профиль**\n"
    text += f"Имя: {p['name'] or 'не указано'}\n"
    text += f"Возраст: {p['age'] or 'не указан'}\n"
    text += f"Пол: {p['gender'] or 'не указан'}\n"
    text += f"Город: {p['city'] or CITY_DEFAULT} 🌍\n\n"
    text += "✏️ Нажми /profile edit или кнопку 👤 Профиль, чтобы изменить"
    await msg.answer(text, parse_mode="Markdown", reply_markup=profile_edit_keyboard())

@dp.message(Command("profile", "edit"))
async def cmd_profile_edit(msg:Message, state:FSMContext):
    await state.set_state(ProfileEditFSM.field)
    await msg.answer("✏️ Что изменить?", reply_markup=profile_edit_keyboard())

@dp.message(Command("stats"))
async def cmd_stats(msg:Message):
    s = await get_task_stats(msg.from_user.id)
    text = f"📊 **Статистика**\n"
    text += f"Задачи: {s['pending'] or 0} активных, {s['completed'] or 0} выполнено\n"
    text += f"  • Работа: {s['work'] or 0} | Личное: {s['personal'] or 0} | Покупки: {s['shopping'] or 0}\n"
    text += f"Заметки: {len(await get_notes(msg.from_user.id, limit=100))}\n"
    text += f"События: {len(await get_calendar_events(msg.from_user.id, limit=100))}"
    await msg.answer(text, parse_mode="Markdown")

# ======================
#  🔥 ПРОФИЛЬ: РЕДАКТИРОВАНИЕ
# ======================
@dp.callback_query(F.data.startswith("profile_edit_"))
async def profile_edit_cb(call:CallbackQuery, state:FSMContext):
    field = call.data.split("_")[-1]
    await state.update_data(field=field)
    await state.set_state(ProfileEditFSM.value)
    prompts = {"name": "✏️ Введите новое имя:", "age": "✏️ Введите возраст (число):",
               "gender": "✏️ Введите пол (муж/жен/другое):", "city": "✏️ Введите город (для погоды/афиши):"}
    await call.message.answer(prompts.get(field, "✏️ Введите значение:"))
    await call.answer()

@dp.message(ProfileEditFSM.value)
async def profile_save_value(msg:Message, state:FSMContext):
    data = await state.get_data()
    field, value = data.get("field"), msg.text.strip()
    if field == "age":
        try: value = int(value)
        except: await msg.answer("❌ Возраст должен быть числом"); return
    await save_profile(msg.from_user.id, **{field: value})
    await msg.answer(f"✅ {field} обновлено: {value}")
    await state.clear()
    p = await get_profile(msg.from_user.id)
    text = f"👤 **Профиль**\nИмя: {p['name'] or 'не указано'}\nВозраст: {p['age'] or 'не указан'}\n"
    text += f"Пол: {p['gender'] or 'не указан'}\nГород: {p['city'] or CITY_DEFAULT} 🌍"
    await msg.answer(text, parse_mode="Markdown", reply_markup=profile_edit_keyboard())

@dp.callback_query(F.data=="profile_done")
async def profile_done_cb(call:CallbackQuery, state:FSMContext):
    await state.clear()
    await call.answer("✅ Профиль сохранён", show_alert=True)

# ======================
#  🔥 ХЕНДЛЕРЫ: ЗАМЕТКИ / КАЛЕНДАРЬ / ЗАДАЧИ
# ======================
# (хендлеры заметок, календаря и задач идентичны v3.0 - сокращено для краткости)
@dp.message(Command("note"))
async def cmd_note_start(msg:Message, state:FSMContext):
    await state.set_state(NoteFSM.content)
    await msg.answer("📝 Что записать в заметку? (или /skip для отмены)")

@dp.message(lambda m: m.text and re.search(r'(?i)(заметк|запиш|сохрани).*:', m.text))
async def text_note_start(msg:Message, state:FSMContext):
    await state.set_state(NoteFSM.content)
    await msg.answer("📝 Что записать в заметку? (или /skip для отмены)")

@dp.message(NoteFSM.content, F.text=="/skip")
async def note_skip(msg:Message, state:FSMContext): await state.clear(); await msg.answer("❌ Отменено")
@dp.message(NoteFSM.content)
async def note_content(msg:Message, state:FSMContext):
    await state.update_data(content=msg.text)
    await state.set_state(NoteFSM.tags)
    await msg.answer("🏷 Теги (через запятую, или /skip):")
@dp.message(NoteFSM.tags, F.text=="/skip")
async def note_tags_skip(msg:Message, state:FSMContext):
    data = await state.get_data()
    note_id = await create_note(msg.from_user.id, data["content"], None)
    await msg.answer(f"✅ Заметка #{note_id} сохранена", reply_markup=note_actions_keyboard(note_id))
    await state.clear()
@dp.message(NoteFSM.tags)
async def note_tags(msg:Message, state:FSMContext):
    tags = [t.strip() for t in msg.text.split(",") if t.strip()]
    data = await state.get_data()
    note_id = await create_note(msg.from_user.id, data["content"], tags)
    await msg.answer(f"✅ Заметка #{note_id} сохранена с тегами: {', '.join(tags)}", reply_markup=note_actions_keyboard(note_id))
    await state.clear()
@dp.message(Command("notes"))
async def cmd_notes(msg:Message):
    notes = await get_notes(msg.from_user.id)
    if not notes: await msg.answer("📝 Нет заметок. Создать? /note", reply_markup=main_menu_keyboard()); return
    text = "📝 **Твои заметки:**\n\n" + "\n\n".join([f"#{n['id']} {n['content'][:100]}{'...' if len(n['content'])>100 else ''}\n🏷 {', '.join(n['tags'] or [])}\n🕐 {n['created_at'].strftime('%d.%m %H:%M')}" for n in notes[:5]])
    await msg.answer(text, reply_markup=main_menu_keyboard())

@dp.message(Command("event"))
async def cmd_event_start(msg:Message, state:FSMContext):
    await state.set_state(CalendarFSM.title)
    await msg.answer("📅 Название события:")
@dp.message(lambda m: m.text and re.search(r'(?i)(событи|встреч|план|календар).*:', m.text))
async def text_event_start(msg:Message, state:FSMContext):
    await state.set_state(CalendarFSM.title)
    await msg.answer("📅 Название события:")
@dp.message(CalendarFSM.title)
async def event_title(msg:Message, state:FSMContext):
    await state.update_data(title=msg.text)
    await state.set_state(CalendarFSM.description)
    await msg.answer("📄 Описание (или /skip):")
@dp.message(CalendarFSM.description, F.text=="/skip")
async def event_desc_skip(msg:Message, state:FSMContext):
    await state.update_data(description=None)
    await state.set_state(CalendarFSM.event_date)
    await msg.answer("🗓 Когда? (например: 'завтра в 18:00', 'через 2 часа'):")
@dp.message(CalendarFSM.description)
async def event_description(msg:Message, state:FSMContext):
    await state.update_data(description=msg.text)
    await state.set_state(CalendarFSM.event_date)
    await msg.answer("🗓 Когда? (например: 'завтра в 18:00', 'через 2 часа'):")
@dp.message(CalendarFSM.event_date)
async def event_date(msg:Message, state:FSMContext):
    event_date = parse_time(msg.text)
    if not event_date: await msg.answer("❌ Не понял дату. Попробуй: 'завтра в 18:00'"); return
    data = await state.get_data()
    event_id = await create_calendar_event(msg.from_user.id, data["title"], data.get("description"), event_date)
    await msg.answer(f"✅ Событие #{event_id} добавлено: {data['title']}\n🗓 {event_date.strftime('%d.%m %H:%M')}")
    await state.clear()
@dp.message(Command("calendar"))
async def cmd_calendar(msg:Message):
    events = await get_calendar_events(msg.from_user.id)
    if not events: await msg.answer("📅 Нет событий. Добавить? /event", reply_markup=main_menu_keyboard()); return
    text = "📅 **Ближайшие события:**\n\n" + "\n\n".join([f"• {e['title']}\n🗓 {e['event_date'].strftime('%d.%m %H:%M')}\n{e['description'] or ''}" for e in events[:5]])
    await msg.answer(text, reply_markup=main_menu_keyboard())

@dp.message(Command("task"))
async def cmd_task_start(msg:Message, state:FSMContext):
    await state.set_state(TaskFSM.title)
    await msg.answer("📝 Название задачи:")
@dp.message(TaskFSM.title)
async def task_title(msg:Message, state:FSMContext):
    await state.update_data(title=msg.text)
    await state.set_state(TaskFSM.description)
    await msg.answer("📄 Описание (или /skip):")
@dp.message(TaskFSM.description, F.text=="/skip")
async def task_skip_desc(msg:Message, state:FSMContext):
    await state.update_data(description=None)
    await state.set_state(TaskFSM.priority)
    await msg.answer("⚡ Приоритет:", reply_markup=task_priority_keyboard())
@dp.message(TaskFSM.description)
async def task_description(msg:Message, state:FSMContext):
    await state.update_data(description=msg.text)
    await state.set_state(TaskFSM.priority)
    await msg.answer("⚡ Приоритет:", reply_markup=task_priority_keyboard())
@dp.callback_query(F.data.startswith("pri_"))
async def task_priority_cb(call:CallbackQuery, state:FSMContext):
    priority = call.data.split("_")[1]
    await state.update_data(priority=priority)
    await call.message.edit_text(f"✅ Приоритет: {priority}")
    await state.set_state(TaskFSM.due_date)
    await call.message.answer("📅 Срок (или /skip):")
@dp.message(TaskFSM.due_date, F.text=="/skip")
async def task_skip_due(msg:Message, state:FSMContext):
    await state.update_data(due_date=None)
    await state.set_state(TaskFSM.category)
    await msg.answer("📂 Категория:", reply_markup=task_category_keyboard())
@dp.message(TaskFSM.due_date)
async def task_due_date(msg:Message, state:FSMContext):
    due = parse_time(msg.text)
    await state.update_data(due_date=due)
    await state.set_state(TaskFSM.category)
    await msg.answer("📂 Категория:", reply_markup=task_category_keyboard())
@dp.callback_query(F.data.startswith("cat_"))
async def task_category_cb(call:CallbackQuery, state:FSMContext):
    category = call.data.split("_")[1]
    await state.update_data(category=category)
    await call.message.edit_text(f"✅ Категория: {category}")
    await state.set_state(TaskFSM.tags)
    await call.message.answer("🏷 Теги (через запятую, или /skip):")
@dp.message(TaskFSM.tags, F.text=="/skip")
async def task_skip_tags(msg:Message, state:FSMContext):
    await state.update_data(tags=None)
    await state.set_state(TaskFSM.recurrence)
    await msg.answer("🔄 Повторение:", reply_markup=task_recurrence_keyboard())
@dp.message(TaskFSM.tags)
async def task_tags(msg:Message, state:FSMContext):
    tags = [t.strip() for t in msg.text.split(",") if t.strip()]
    await state.update_data(tags=tags)
    await state.set_state(TaskFSM.recurrence)
    await msg.answer("🔄 Повторение:", reply_markup=task_recurrence_keyboard())
@dp.callback_query(F.data.startswith("rec_"))
async def task_recurrence_cb(call:CallbackQuery, state:FSMContext):
    recurrence = call.data.split("_")[1] if call.data != "rec_none" else None
    await state.update_data(recurrence=recurrence)
    await call.message.edit_text(f"✅ Повтор: {recurrence or 'нет'}")
    await state.set_state(TaskFSM.attachments)
    await call.message.answer("📎 Вложения (ссылки через запятую, или /skip):")
@dp.message(TaskFSM.attachments, F.text=="/skip")
async def task_skip_attachments(msg:Message, state:FSMContext):
    await _finish_task_creation(msg, state, None)
@dp.message(TaskFSM.attachments)
async def task_attachments(msg:Message, state:FSMContext):
    attachments = [a.strip() for a in msg.text.split(",") if a.strip()]
    await _finish_task_creation(msg, state, attachments)
async def _finish_task_creation(msg:Message, state:FSMContext, attachments):
    data = await state.get_data()
    task_id = await create_task(uid=msg.from_user.id, title=data["title"], description=data.get("description"),
        priority=data.get("priority", "medium"), due_date=data.get("due_date"), category=data.get("category", "general"),
        tags=data.get("tags"), parent_id=None, recurrence=data.get("recurrence"), attachments=attachments)
    await msg.answer(f"✅ Задача #{task_id} создана: {data['title']}", reply_markup=task_actions_keyboard(task_id))
    await state.clear()
@dp.message(Command("tasks"))
async def cmd_tasks(msg:Message):
    tasks = await get_tasks(msg.from_user.id)
    if not tasks: await msg.answer("📋 Нет активных задач. Отдыхай!", reply_markup=main_menu_keyboard()); return
    text = "📋 **Задачи:**\n" + "\n".join([f"• {t['title']}" + (f" ({t['due_date'].strftime('%d.%m')})" if t['due_date'] else "") + f" | {t['category']} | ID:{t['id']}" for t in tasks[:5]])
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
    await call.message.answer("📝 Название новой задачи:"); await call.answer("Используй /task", show_alert=True)
@dp.callback_query(F.data.startswith("task_complete_"))
async def cb_task_done(call:CallbackQuery):
    tid = int(call.data.split("_")[-1])
    await complete_task(call.from_user.id, tid)
    await call.answer("✅ Готово!", show_alert=True)
    await call.message.delete()
@dp.callback_query(F.data.startswith("task_delete_"))
async def cb_task_del(call:CallbackQuery):
    tid = int(call.data.split("_")[-1])
    await delete_task(call.from_user.id, tid)
    await call.answer("🗑 Удалено", show_alert=True)
    await call.message.delete()
@dp.callback_query(F.data.startswith("task_subtasks_"))
async def cb_task_subtasks(call:CallbackQuery):
    parent_id = int(call.data.split("_")[-1])
    subtasks = await get_subtasks(call.from_user.id, parent_id)
    text = "📋 Подзадачи:\n" + "\n".join([f"• {st['title']} ({st['status']})" for st in subtasks]) if subtasks else "Нет подзадач"
    await call.message.answer(text)
@dp.callback_query(F.data=="notes_list")
async def cb_notes(call:CallbackQuery):
    notes = await get_notes(call.from_user.id)
    text = "📝 Заметки:\n" + "\n".join([f"#{n['id']} {n['content'][:50]}..." for n in notes[:5]]) if notes else "Нет заметок"
    await call.message.edit_text(text, reply_markup=main_menu_keyboard())
@dp.callback_query(F.data=="calendar_list")
async def cb_calendar(call:CallbackQuery):
    events = await get_calendar_events(call.from_user.id)
    text = "📅 События:\n" + "\n".join([f"• {e['title']} ({e['event_date'].strftime('%d.%m')})" for e in events[:5]]) if events else "Нет событий"
    await call.message.edit_text(text, reply_markup=main_menu_keyboard())
@dp.callback_query(F.data=="habits_list")
async def cb_habits(call:CallbackQuery):
    habits = await get_habits(call.from_user.id)
    text = "🔁 Привычки:\n" + "\n".join([f"• {h['name']}: {h['streak']} дн." for h in habits]) if habits else "Нет привычек"
    await call.message.edit_text(text, reply_markup=main_menu_keyboard())
@dp.callback_query(F.data=="reminders_list")
async def cb_reminders(call:CallbackQuery):
    await call.message.answer("⏰ Напоминания: напиши 'напомни [что] [когда]'"); await call.answer()
@dp.callback_query(F.data=="stats")
async def cb_stats(call:CallbackQuery):
    s = await get_task_stats(call.from_user.id)
    await call.answer(f"📊 Задачи: {s['pending'] or 0} активных", show_alert=True)
@dp.callback_query(F.data=="profile_show")
async def cb_profile(call:CallbackQuery):
    p = await get_profile(call.from_user.id)
    text = f"👤 {p['name']}" + (f", {p['age']} лет" if p and p['age'] else "") if p and p['name'] else "Нет данных"
    await call.answer(text, show_alert=True)
@dp.callback_query(F.data=="help_show")
async def cb_help(call:CallbackQuery):
    await call.answer("Справка: /task, /note, /event, /habits, /weather [город]", show_alert=True)

# ======================
#  🔥 ВНЕШНИЕ ДАННЫЕ: CALLBACKS С API
# ======================
@dp.callback_query(F.data=="ext_weather")
async def cb_ext_weather(call:CallbackQuery):
    profile = await get_profile(call.from_user.id)
    city = profile.get("city") if profile and profile.get("city") else CITY_DEFAULT
    weather = await get_weather_data(city)
    if weather:
        text = f"🌤 **{city}**\n🌡 {weather['temp']}° (ощущается {weather['feels_like']}°)\n"
        text += f"☁️ {weather['description'].capitalize()}\n💧 Влажность: {weather['humidity']}%\n🌬 Ветер: {weather['wind']} м/с"
        await call.message.answer(text)
    else:
        await call.message.answer(f"🌤 Погода в {city}:", reply_markup=external_link_keyboard(get_weather_link(city), f"Яндекс.Погода: {city}"))
    await call.answer()

@dp.callback_query(F.data=="ext_currency")
async def cb_ext_currency(call:CallbackQuery):
    rates = await get_currency_data()
    if rates:
        text = f"💱 **Курс валют** (к рублю):\n"
        text += f"🇺🇸 1$ = {rates.get('USD', 0):.2f}₽\n"
        text += f"🇪🇺 1€ = {rates.get('EUR', 0):.2f}₽\n"
        text += f"🇬🇧 1£ = {rates.get('GBP', 0):.2f}₽\n"
        text += f"🇨🇳 1¥ = {rates.get('CNY', 0):.2f}₽"
        await call.message.answer(text)
    else:
        await call.message.answer("💱 Курс валют:", reply_markup=external_link_keyboard(get_currency_link(), "Открыть ЦБ"))
    await call.answer()

@dp.callback_query(F.data=="ext_cinema")
async def cb_ext_cinema(call:CallbackQuery):
    profile = await get_profile(call.from_user.id)
    city = profile.get("city") if profile and profile.get("city") else CITY_DEFAULT
    movies = await get_cinema_data(city)
    if movies:
        text = f"🎬 **В прокате сейчас**:\n\n"
        text += "\n".join([f"• {m['title']} ⭐ {m['rating']:.1f}" for m in movies])
        text += f"\n\n🔗 Полная афиша: {city}"
        await call.message.answer(text, reply_markup=external_link_keyboard(get_cinema_link(city), f"Афиша: {city}"))
    else:
        await call.message.answer(f"🎬 Афиша: {city}", reply_markup=external_link_keyboard(get_cinema_link(city), f"Афиша: {city}"))
    await call.answer()

@dp.callback_query(F.data=="ext_news")
async def cb_ext_news(call:CallbackQuery):
    news = await get_news_data()
    if news:
        text = "📰 **Главные новости**:\n\n"
        text += "\n".join([f"• {n['title']}" for n in news])
        text += f"\n\n🔗 Все новости"
        await call.message.answer(text, reply_markup=external_link_keyboard(get_news_link(), "Яндекс.Новости"))
    else:
        await call.message.answer("📰 Новости:", reply_markup=external_link_keyboard(get_news_link(), "Яндекс.Новости"))
    await call.answer()

@dp.callback_query(F.data.startswith("note_delete_"))
async def cb_note_del(call:CallbackQuery):
    nid = int(call.data.split("_")[-1])
    await delete_note(call.from_user.id, nid)
    await call.answer("🗑 Заметка удалена", show_alert=True)
    await call.message.delete()

# ======================
#  ПАРСЕР КОМАНД
# ======================
RU_COMMANDS = {"меню":"show_menu","главное меню":"show_menu","кнопки":"show_menu","инлайн":"show_menu","задачи":"list_tasks","мои задачи":"list_tasks","список дел":"list_tasks","новая задача":"create_task","добавить задачу":"create_task","заметк":"notes_list","добавить заметку":"note_create","мои заметки":"notes_list","календар":"calendar_list","событи":"event_create","встреч":"event_create","план":"event_create","привычки":"list_habits","мои привычки":"list_habits","погода":"ext_weather","погода в":"ext_weather","как погода":"ext_weather","курс":"ext_currency","курс доллара":"ext_currency","валюта":"ext_currency","кино":"ext_cinema","афиша":"ext_cinema","что в кино":"ext_cinema","новости":"ext_news","что нового":"ext_news","профиль":"profile_show","обо мне":"profile_show","помощь":"help_show","что умеешь":"help_show"}
def parse_ru_command(text:str) -> str|None:
    text_lower = text.lower().strip()
    for keyword,cmd in RU_COMMANDS.items():
        if keyword in text_lower: return cmd
    return None

# ======================
#  🔥 ОСНОВНОЙ ЧАТ
# ======================
@dp.message()
async def chat(msg:Message, state:FSMContext):
    if not msg.text or await state.get_state(): return
    uid = msg.from_user.id
    original_text = msg.text.strip()
    text = fix_layout(original_text)
    
    async with db_pool.acquire() as conn: await conn.execute("INSERT INTO users(user_id,name) VALUES ($1,$2) ON CONFLICT DO NOTHING", uid, msg.from_user.first_name)
    await update_last_activity(uid)
    profile = await get_profile(uid)
    if not profile or not profile["name"]:
        name,age,gender,city = extract_profile(text)
        if name or age or gender or city:
            await save_profile(uid, name=name, age=age, gender=gender, city=city)
            profile = await get_profile(uid)
            await msg.answer(f"Запомнил: {name or city or 'данные'}"); return
    
    if should_reset_context(text) or any(kw in text.lower() for kw in FRUSTRATION_KEYWORDS):
        async with db_pool.acquire() as conn:
            await conn.execute("DELETE FROM memory WHERE user_id=$1 AND id IN (SELECT id FROM memory WHERE user_id=$1 ORDER BY created_at DESC LIMIT 5)", uid)
    
    memory = await get_memory(uid); mood = await get_mood(uid); habits = await get_habits(uid); tasks_count = (await get_task_stats(uid))["pending"] or 0
    await save_memory(uid,"user",text); await update_emotion(uid,text)
    
    cmd = parse_ru_command(text)
    if cmd:
        if cmd=="show_menu": await msg.answer("📋 Меню:", reply_markup=main_menu_keyboard()); return
        elif cmd=="list_tasks": await cmd_tasks(msg); return
        elif cmd=="create_task": await cmd_task_start(msg, state); return
        elif cmd=="notes_list": await cb_notes(msg); return
        elif cmd=="note_create": await cmd_note_start(msg, state); return
        elif cmd=="calendar_list": await cb_calendar(msg); return
        elif cmd=="event_create": await cmd_event_start(msg, state); return
        elif cmd=="list_habits": await cb_habits(msg); return
        elif cmd=="ext_weather":
            city = profile.get("city") if profile and profile.get("city") else CITY_DEFAULT
            weather = await get_weather_data(city)
            if weather:
                await msg.answer(f"🌤 {city}: {weather['temp']}°, {weather['description']}")
                return
            await msg.answer(f"🌤 Погода в {city}:", reply_markup=external_link_keyboard(get_weather_link(city), f"Яндекс.Погода: {city}"))
            return
        elif cmd=="ext_currency":
            rates = await get_currency_data()
            if rates:
                await msg.answer(f"💱 1$ = {rates.get('USD', 0):.2f}₽ | 1€ = {rates.get('EUR', 0):.2f}₽")
                return
            await msg.answer("💱 Курс:", reply_markup=external_link_keyboard(get_currency_link(), "Открыть ЦБ"))
            return
        elif cmd=="ext_cinema":
            city = profile.get("city") if profile and profile.get("city") else CITY_DEFAULT
            await msg.answer(f"🎬 Афиша: {city}", reply_markup=external_link_keyboard(get_cinema_link(city), f"Афиша: {city}"))
            return
        elif cmd=="ext_news":
            news = await get_news_data()
            if news:
                await msg.answer(f"📰 {news[0]['title']}")
                return
            await msg.answer("📰 Новости:", reply_markup=external_link_keyboard(get_news_link(), "Яндекс.Новости"))
            return
        elif cmd=="profile_show": await cmd_profile(msg, state); return
        elif cmd=="help_show": await cmd_help(msg); return
    
    grok = await call_grok_analysis(text, memory, profile)
    if grok.get("external_link"):
        await msg.answer(f"{grok.get('external_link_label','Открыть')}:", reply_markup=external_link_keyboard(grok["external_link"], grok.get("external_link_label","Открыть"))); return
    if grok.get("is_task_creation") or any(w in text.lower() for w in ["задач","сделай","надо"]):
        await msg.answer("Создать задачу? Напиши /task или нажми кнопку 👇", reply_markup=main_menu_keyboard()); return
    
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO message_tags(user_id,message_id,tags,topic) VALUES ($1,$2,$3,$4)", uid, msg.message_id, grok.get("tags",[]), grok.get("topic"))
    
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
async def calendar_reminder_check():
    async with db_pool.acquire() as conn:
        events = await conn.fetch("SELECT user_id, title, event_date, reminder_before FROM calendar_events WHERE event_date <= NOW() + INTERVAL '1 hour' AND event_date > NOW() - INTERVAL '1 hour'")
    for e in events:
        try: await bot.send_message(e["user_id"], f"📅 Скоро: {e['title']} ({e['event_date'].strftime('%H:%M')})")
        except: pass
async def inactivity_check():
    async with db_pool.acquire() as conn: users = await conn.fetch("SELECT user_id FROM last_activity WHERE last_time < NOW() - INTERVAL '24 hours'")
    for u in users:
        try: await bot.send_message(u["user_id"], "Давно не виделись. Как дела?")
        except: pass

# ======================
#  🔥 HEALTH CHECK
# ======================
async def health_handler(request):
    return web.json_response({"status":"ok","bot":"AssistEmpat v3.2"}, headers={"Content-Type":"application/json"})
async def start_health_server():
    app = web.Application()
    app.router.add_get('/health', health_handler)
    app.router.add_get('/', health_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', HEALTH_PORT)
    await site.start()
    logging.info(f"🏥 Health server on port {HEALTH_PORT}")
    return runner

# ======================
#  🔥 ЗАПУСК
# ======================
async def main():
    logging.info(f"🚀 Starting AssistEmpat v3.2 (port={HEALTH_PORT})")
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    def handle_signal():
        logging.info("🛑 Signal received")
        stop_event.set()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, handle_signal)
    try:
        await init_db()
        logging.info("✅ DB initialized")
    except Exception as e:
        logging.error(f"❌ DB init failed: {e}")
        return
    health_runner = None
    try:
        health_runner = await start_health_server()
        await asyncio.sleep(1.0)
        logging.info("✅ Health server ready")
    except Exception as e:
        logging.warning(f"⚠️ Health server failed: {e}")
    if stop_event.is_set():
        await cleanup(health_runner)
        return
    scheduler.start()
    scheduler.add_job(morning_ping, "cron", hour=9)
    scheduler.add_job(habit_check, "interval", hours=6)
    scheduler.add_job(task_reminder_check, "interval", minutes=30)
    scheduler.add_job(calendar_reminder_check, "interval", minutes=30)
    scheduler.add_job(inactivity_check, "interval", hours=24)
    logging.info("✅ Scheduler started")
    await bot.delete_webhook(drop_pending_updates=True)
    if stop_event.is_set():
        await cleanup(health_runner)
        return
    logging.info("✅ AssistEmpat v3.2 ready — STARTING POLLING")
    polling_task = asyncio.create_task(dp.start_polling(bot))
    done, pending = await asyncio.wait([polling_task, asyncio.create_task(stop_event.wait())], return_when=asyncio.FIRST_COMPLETED)
    await cleanup(health_runner)
    for task in pending:
        task.cancel()
        try: await task
        except asyncio.CancelledError: pass

async def cleanup(health_runner=None):
    logging.info("👋 Cleaning up...")
    if db_pool:
        try: await db_pool.close()
        except: pass
    if bot.session:
        try: await bot.session.close()
        except: pass
    if health_runner:
        try: await health_runner.cleanup()
        except: pass
    try: scheduler.shutdown(wait=False)
    except: pass
    logging.info("✅ Cleanup complete")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("👋 Stopped by user")
    except Exception as e:
        logging.error(f"💥 Fatal error: {e}")
        raise