# =========================================================
#  ASSISTEMPAT BOT v4.6 (Psycho Mode + Adaptive Tone)
#  Новое:
#  1. 🧠 Режим психоанализа с адаптивным тоном
#  2. 🔥 Авто-детекция стиля: эмпатия/аналитика/жёсткий/сарказм
#  3. 📊 Изолированный контекст + авто-сброс
#  4. 👤 Профиль доступен через /profile или "мой профиль"
#  Часовой пояс: Москва (UTC+3)
# =========================================================

import asyncio
import logging
import os
import re
import signal
import json
import urllib.parse
import hashlib
import random
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
#  🔥 ЧАСОВОЙ ПОЯС: МОСКВА
# ======================
MOSCOW_TZ = timezone(timedelta(hours=3))
def now_moscow() -> datetime: return datetime.now(MOSCOW_TZ)

# ======================
#  🔥 ЦИТАТЫ И ФАКТЫ
# ======================
QUOTES_RU = [
    "«Путь в тысячу миль начинается с первого шага» — Лао-Цзы",
    "«Не откладывай на завтра то, что можно сделать сегодня» — Бенджамин Франклин",
    "«Успех — это способность идти от неудачи к неудаче, не теряя энтузиазма» — У. Черчилль",
    "«Лучшее время, чтобы посадить дерево, было 20 лет назад. Следующее лучшее время — сейчас» — Китайская пословица",
    "«Делай что можешь, с тем, что имеешь, там, где ты есть» — Теодор Рузвельт",
    "«Единственный способ делать великие дела — любить то, что делаешь» — Стив Джобс",
    "«Не бойся медлить, бойся остановиться» — Китайская мудрость",
    "«Сложнее всего начать действовать, все остальное зависит только от упорства» — Амелия Эрхарт",
    "«Ваше время ограничено, не тратьте его, живя чужой жизнью» — Стив Джобс",
    "«Если вы хотите достичь цели, нужно работать. А если хотите достичь великой цели, нужно работать ещё больше» — Опра Уинфри",
    "«Будь собой и иди своим путём» — Фридрих Ницше",
    "«Знание — сила» — Фрэнсис Бэкон",
    "«Жизнь — это то, что происходит, пока ты строишь другие планы» — Джон Леннон",
    "«Мечтай так, словно будешь жить вечно. Живи так, словно умрёшь сегодня» — Джеймс Дин",
    "«Единственный предел нашим достижениям завтра — это наши сомнения сегодня» — Франклин Рузвельт",
    "«Не жди. Время никогда не будет «подходящим»» — Наполеон Хилл",
    "«Успех — это сумма небольших усилий, повторяющихся изо дня в день» — Роберт Кольер",
    "«Ты становишься тем, о чём думаешь» — Ог Мандино",
    "«Всё, что ты можешь представить — реально» — Пабло Пикассо",
    "«Действуй так, словно то, что ты делаешь, имеет значение. Это так» — Уильям Джеймс",
]

FACTS_RU = [
    "🧠 Мозг человека использует ~20% всей энергии тела, хотя составляет лишь 2% массы.",
    "🌍 Самый короткий день в году — 21 декабря (зимнее солнцестояние).",
    "💧 Человек может прожить без воды около 3 дней, без еды — до 3 недель.",
    "🐝 Пчёлы могут распознавать человеческие лица и запоминать их.",
    "🌙 На Луне нет атмосферы, поэтому звук там не распространяется.",
    "👁️ Человеческий глаз может различать около 10 миллионов оттенков цвета.",
    "🌿 Растения «общаются» через грибные сети в почве (мицелий).",
    "🧬 У человека и банана около 50% общих генов.",
    "⚡ Молния нагревает воздух до 30 000 °C — в 5 раз горячее поверхности Солнца.",
    "🦋 Бабочки пробуют вкус ногами.",
    "🐙 У осьминога три сердца и голубая кровь.",
    "🌊 В океане больше золота, чем можно добыть на суше (но оно растворено в воде).",
    "⏰ Самая короткая война в истории длилась 38 минут (между Англией и Занзибаром в 1896).",
    "🍯 Мёд — единственный продукт, который не портится. Археологи находили мёд в гробницах фараонов.",
    "🎵 Коровы дают больше молока, когда слушают музыку.",
    "🌌 В нашей галактике больше звёзд, чем песчинок на всех пляжах Земли.",
    "👶 Дети рождаются без коленных чашечек — они появляются к 3 годам.",
    "🐢 Некоторые черепахи могут дышать через задний проход.",
    "💎 Алмазы — это просто углерод, сжатый под огромным давлением миллиарды лет.",
    "🎲 Если перемешать колоду карт, полученная комбинация никогда не существовала раньше.",
]

async def get_next_quote_for_user(uid: int) -> str:
    async with db_pool.acquire() as conn:
        row = await conn.fetchval("SELECT last_quote_index FROM profile WHERE user_id=$1", uid)
        last = row if row is not None else -1
        nxt = (last + 1) % len(QUOTES_RU)
        q = QUOTES_RU[nxt]
        await conn.execute("INSERT INTO profile(user_id, last_quote_index) VALUES ($1, $2) ON CONFLICT(user_id) DO UPDATE SET last_quote_index = $2", uid, nxt)
        return q

async def get_next_fact_for_user(uid: int) -> str:
    async with db_pool.acquire() as conn:
        row = await conn.fetchval("SELECT last_fact_index FROM profile WHERE user_id=$1", uid)
        last = row if row is not None else -1
        nxt = (last + 1) % len(FACTS_RU)
        f = FACTS_RU[nxt]
        await conn.execute("INSERT INTO profile(user_id, last_fact_index) VALUES ($1, $2) ON CONFLICT(user_id) DO UPDATE SET last_fact_index = $2", uid, nxt)
        return f

# ======================
#  КОНФИГУРАЦИЯ
# ======================
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
QWEN_API_KEY = os.getenv("QWEN_API_KEY")
CITY_DEFAULT = os.getenv("CITY_DEFAULT", "Москва")
ALLOWED_USERS = os.getenv("ALLOWED_USERS", "")
HEALTH_PORT = int(os.getenv("PORT", os.getenv("RAILWAY_PUBLIC_PORT", 8080)))
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
TMDB_API_KEY = os.getenv("TMDB_API_KEY")
EXCHANGERATE_API_KEY = os.getenv("EXCHANGERATE_API_KEY")
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
scheduler = AsyncIOScheduler(timezone=MOSCOW_TZ)
db_pool = None

# ======================
#  🔥 УМНОЕ ИСПРАВЛЕНИЕ РАСКЛАДКИ
# ======================
LAYOUT_MAP = {'q':'й','w':'ц','e':'у','r':'к','t':'е','y':'н','u':'г','i':'ш','o':'щ','p':'з','[':'х',']':'ъ','a':'ф','s':'ы','d':'в','f':'а','g':'п','h':'р','j':'о','k':'л','l':'д',';':'ж',"'":'э','z':'я','x':'ч','c':'с','v':'м','b':'и','n':'т','m':'ь',',':'б','.':'ю','/':'.'}
def fix_layout(text: str) -> str:
    if not text or len(text) < 4: return text
    safe = ['меню', 'инлайн', 'задача', 'привычк', 'напомн', 'погод', 'кино', 'новост', 'курс', 'профиль', 'помощь', 'статистик', 'заметк', 'календар', 'дашборд', 'сброс', 'reset', 'здоровье', 'психо']
    if any(s in text.lower() for s in safe): return text
    if text.isascii() and text.isalpha():
        c = ''.join(LAYOUT_MAP.get(ch.lower(), ch) for ch in text)
        if any('\u0400' <= ch <= '\u04FF' for ch in c): return c
    return text

# ======================
#  🔥 ДЕТЕКЦИЯ КРИЗИСОВ / СБРОСА
# ======================
CRISIS_KEYWORDS = ["суицид", "умер", "не хочу жить", "убить себя", "паник", "не могу дышать", "сердце", "давление"]
FRUSTRATION_KEYWORDS = ["скотина", "бесчувственный", "ты тупой", "опять", "достал", "хватит", "бесит"]
RESET_KEYWORDS = ["привет", "здравствуй", "отбой", "стоп", "новое", "другое", "пока"]
HEALTH_EXIT_TRIGGERS = ["спасибо", "благодарю", "пока", "до свидания", "выход", "назад", "выход из режима", "хватит здоровья"]
PSYCHO_EXIT_TRIGGERS = ["спасибо", "благодарю", "пока", "до свидания", "выход", "назад", "достаточно", "закончили", "хватит", "всё"]

def is_crisis(text: str) -> tuple[bool, str]:
    t = text.lower()
    if any(w in t for w in ["суицид", "умер", "не хочу жить", "убить себя"]): return True, "critical"
    if any(w in t for w in ["паник", "не могу дышать", "сердце", "давление"]): return True, "medical_emergency"
    return False, ""

def should_reset_context(text: str) -> bool:
    t = text.lower().strip()
    if any(k in t for k in RESET_KEYWORDS): return True
    if t.endswith("?") and len(t.split()) < 4: return True
    return False

def is_topic_change(text: str, current_mode: str) -> bool:
    """Определяет очевидную смену темы для выхода из спец-режимов"""
    t = text.lower()
    util_keywords = ["задача", "заметк", "календар", "погод", "курс", "кино", "новост", "дашборд", "меню"]
    if any(k in t for k in util_keywords): return True
    if current_mode == "psycho" and any(k in t for k in ["давление", "голова", "сон", "питание", "здоров"]): return True
    if current_mode == "health" and any(k in t for k in ["чувствую", "эмоц", "отношен", "мысль", "тревож"]): return True
    return False

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
        CREATE TABLE IF NOT EXISTS habits(id SERIAL PRIMARY KEY, user_id BIGINT, name TEXT, streak INTEGER DEFAULT 0, last_done DATE, frequency TEXT DEFAULT 'daily', target_per_week INTEGER DEFAULT 7);
        CREATE TABLE IF NOT EXISTS emotions(id SERIAL PRIMARY KEY, user_id BIGINT, mood TEXT, created_at TIMESTAMP DEFAULT NOW());
        CREATE TABLE IF NOT EXISTS last_activity(user_id BIGINT PRIMARY KEY, last_time TIMESTAMP DEFAULT NOW());
        CREATE TABLE IF NOT EXISTS message_tags(id SERIAL PRIMARY KEY, user_id BIGINT, message_id BIGINT, tags TEXT[], topic TEXT, created_at TIMESTAMP DEFAULT NOW());
        CREATE TABLE IF NOT EXISTS response_log(id SERIAL PRIMARY KEY, user_id BIGINT, content_hash TEXT, created_at TIMESTAMP DEFAULT NOW());
        CREATE TABLE IF NOT EXISTS notes(id SERIAL PRIMARY KEY, user_id BIGINT, content TEXT, created_at TIMESTAMP DEFAULT NOW(), tags TEXT[], category TEXT DEFAULT 'general');
        CREATE TABLE IF NOT EXISTS calendar_events(id SERIAL PRIMARY KEY, user_id BIGINT, title TEXT, description TEXT, event_date TIMESTAMP, reminder_before INTERVAL, recurrence TEXT, category TEXT DEFAULT 'general', created_at TIMESTAMP DEFAULT NOW());
        """)
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks(
            id SERIAL PRIMARY KEY, user_id BIGINT, title TEXT NOT NULL, description TEXT, status TEXT DEFAULT 'pending',
            priority TEXT DEFAULT 'medium', due_date TIMESTAMP, category TEXT DEFAULT 'general', tags TEXT[],
            parent_id INTEGER REFERENCES tasks(id) ON DELETE CASCADE, recurrence TEXT, attachments TEXT[],
            created_at TIMESTAMP DEFAULT NOW(), completed_at TIMESTAMP, checklist JSONB DEFAULT '[]'
        );""")
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS profile(
            user_id BIGINT PRIMARY KEY, name TEXT, age INTEGER, gender TEXT, city TEXT DEFAULT 'Москва',
            last_quote_index INTEGER DEFAULT 0, last_fact_index INTEGER DEFAULT 0, mode TEXT DEFAULT 'general',
            health_context TEXT DEFAULT '', psycho_context TEXT DEFAULT '', created_at TIMESTAMP DEFAULT NOW(), updated_at TIMESTAMP DEFAULT NOW()
        );""")
        
        migrations = [
            "ALTER TABLE reminders ADD COLUMN IF NOT EXISTS remind_at TIMESTAMP",
            "ALTER TABLE habits ADD COLUMN IF NOT EXISTS streak INTEGER DEFAULT 0",
            "ALTER TABLE habits ADD COLUMN IF NOT EXISTS last_done DATE",
            "ALTER TABLE habits ADD COLUMN IF NOT EXISTS frequency TEXT DEFAULT 'daily'",
            "ALTER TABLE habits ADD COLUMN IF NOT EXISTS target_per_week INTEGER DEFAULT 7",
            "ALTER TABLE notes ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW()",
            "ALTER TABLE notes ADD COLUMN IF NOT EXISTS tags TEXT[]",
            "ALTER TABLE notes ADD COLUMN IF NOT EXISTS category TEXT DEFAULT 'general'",
            "ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS reminder_before INTERVAL",
            "ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS recurrence TEXT",
            "ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS category TEXT DEFAULT 'general'",
            "ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW()",
            "ALTER TABLE response_log ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW()",
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS category TEXT DEFAULT 'general'",
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS tags TEXT[]",
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS parent_id INTEGER REFERENCES tasks(id) ON DELETE CASCADE",
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS recurrence TEXT",
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS attachments TEXT[]",
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP",
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS checklist JSONB DEFAULT '[]'",
            "ALTER TABLE profile ADD COLUMN IF NOT EXISTS city TEXT DEFAULT 'Москва'",
            "ALTER TABLE profile ADD COLUMN IF NOT EXISTS last_quote_index INTEGER DEFAULT 0",
            "ALTER TABLE profile ADD COLUMN IF NOT EXISTS last_fact_index INTEGER DEFAULT 0",
            "ALTER TABLE profile ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW()",
            "ALTER TABLE profile ADD COLUMN IF NOT EXISTS mode TEXT DEFAULT 'general'",
            "ALTER TABLE profile ADD COLUMN IF NOT EXISTS health_context TEXT DEFAULT ''",
            "ALTER TABLE profile ADD COLUMN IF NOT EXISTS psycho_context TEXT DEFAULT ''",
        ]
        for sql in migrations:
            try: await conn.execute(sql)
            except: pass
            
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_memory_user ON memory(user_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_habits_user ON habits(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_reminders_time ON reminders(remind_at)",
            "CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id, status)",
            "CREATE INDEX IF NOT EXISTS idx_tasks_category ON tasks(user_id, category)",
            "CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(user_id, parent_id)",
            "CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks(user_id, due_date) WHERE status='pending'",
            "CREATE INDEX IF NOT EXISTS idx_response_log ON response_log(user_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_notes_user ON notes(user_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_notes_category ON notes(user_id, category)",
            "CREATE INDEX IF NOT EXISTS idx_calendar_user ON calendar_events(user_id, event_date)",
            "CREATE INDEX IF NOT EXISTS idx_calendar_category ON calendar_events(user_id, category)",
        ]
        for sql in indexes:
            try: await conn.execute(sql)
            except: pass
    logging.info("✅ PostgreSQL initialized + v4.6 features")

# ======================
#  🔥 ОЧИСТКА КОНТЕКСТА
# ======================
async def clear_user_context(uid: int):
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM memory WHERE user_id=$1", uid)
        await conn.execute("DELETE FROM emotions WHERE user_id=$1", uid)
        await conn.execute("DELETE FROM response_log WHERE user_id=$1", uid)
    logging.info(f"🗑 Context cleared for user {uid}")

# ======================
#  🔥 УПРАВЛЕНИЕ РЕЖИМАМИ
# ======================
async def set_user_mode(uid: int, mode: str, health_ctx: str = "", psycho_ctx: str = ""):
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE profile SET mode=$1, health_context=$2, psycho_context=$3 WHERE user_id=$4", mode, health_ctx, psycho_ctx, uid)

async def get_health_context(uid: int) -> list:
    async with db_pool.acquire() as conn:
        raw = await conn.fetchval("SELECT health_context FROM profile WHERE user_id=$1", uid)
        return json.loads(raw) if raw else []

async def save_health_context(uid: int, ctx: list):
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE profile SET health_context=$1 WHERE user_id=$2", json.dumps(ctx[-5:]), uid)

async def get_psycho_context(uid: int) -> list:
    async with db_pool.acquire() as conn:
        raw = await conn.fetchval("SELECT psycho_context FROM profile WHERE user_id=$1", uid)
        return json.loads(raw) if raw else []

async def save_psycho_context(uid: int, ctx: list):
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE profile SET psycho_context=$1 WHERE user_id=$2", json.dumps(ctx[-8:]), uid)

# ======================
#  🔥 ANTI-LOOP
# ======================
async def is_duplicate_response(uid: int, new_text: str) -> bool:
    if not new_text or len(new_text.strip()) < 5: return False
    h = hashlib.md5(new_text.strip().lower().encode()).hexdigest()
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT content_hash FROM response_log WHERE user_id=$1 ORDER BY created_at DESC LIMIT 3", uid)
        if h in [r["content_hash"] for r in rows]: return True
        await conn.execute("INSERT INTO response_log(user_id, content_hash) VALUES ($1, $2)", uid, h)
        await conn.execute("DELETE FROM response_log WHERE user_id=$1 AND id NOT IN (SELECT id FROM response_log WHERE user_id=$1 ORDER BY created_at DESC LIMIT 20)", uid)
    return False

# ======================
#  🔥 ВНЕШНИЕ ДАННЫЕ
# ======================
async def get_weather_data(city: str) -> dict | None:
    if not OPENWEATHER_API_KEY: return None
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get("https://api.openweathermap.org/data/2.5/weather", params={"q": city, "appid": OPENWEATHER_API_KEY, "units": "metric", "lang": "ru"})
            r.raise_for_status()
            d = r.json()
            return {"temp": d["main"]["temp"], "feels_like": d["main"]["feels_like"], "description": d["weather"][0]["description"], "humidity": d["main"]["humidity"], "wind": d["wind"]["speed"]}
    except: return None
def get_weather_link(city: str) -> str: return f"https://yandex.ru/pogoda/{urllib.parse.quote(city)}"
async def get_currency_data(base="RUB") -> dict | None:
    if not EXCHANGERATE_API_KEY: return None
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"https://v6.exchangerate-api.com/v6/{EXCHANGERATE_API_KEY}/latest/{base}")
            r.raise_for_status()
            return r.json().get("conversion_rates", {})
    except: return None
def get_currency_link() -> str: return "https://www.cbr.ru/currency_base/daily/"
async def get_cinema_data(city: str) -> list | None:
    if not TMDB_API_KEY: return None
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get("https://api.themoviedb.org/3/movie/now_playing", params={"api_key": TMDB_API_KEY, "language": "ru-RU", "page": 1})
            r.raise_for_status()
            d = r.json()
            return [{"title": m["title"], "rating": m.get("vote_average", 0)} for m in d.get("results", [])[:5]]
    except: return None
def get_cinema_link(city: str = "Москва") -> str: return f"https://afisha.yandex.ru/{urllib.parse.quote(city)}/cinema/"
async def get_news_data() -> list | None:
    if not NEWSAPI_KEY: return None
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get("https://newsapi.org/v2/top-headlines", params={"apiKey": NEWSAPI_KEY, "country": "ru", "language": "ru", "pageSize": 5})
            r.raise_for_status()
            d = r.json()
            return [{"title": a["title"], "url": a["url"]} for a in d.get("articles", [])[:5]]
    except: return None
def get_news_link() -> str: return "https://news.yandex.ru/"

# ======================
#  🔥 ЗАДАЧИ / ЗАМЕТКИ / КАЛЕНДАРЬ / ПРИВЫЧКИ / ПРОФИЛЬ / ДАШБОРД
# ======================
async def create_task(uid, title, description=None, priority="medium", due_date=None, category="general", tags=None, parent_id=None, recurrence=None, attachments=None, checklist=None):
    async with db_pool.acquire() as conn:
        return await conn.fetchval("INSERT INTO tasks(user_id, title, description, priority, due_date, category, tags, parent_id, recurrence, attachments, checklist) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11) RETURNING id", uid, title, description, priority, due_date, category, tags, parent_id, recurrence, attachments, json.dumps(checklist) if checklist else '[]')

async def get_tasks(uid, status="pending", category=None, parent_id=None, due_date_range=None):
    async with db_pool.acquire() as conn:
        query = "SELECT id, title, description, priority, due_date, category, tags, parent_id, recurrence, attachments, checklist, created_at FROM tasks WHERE user_id=$1 AND status=$2"
        params = [uid, status]
        if category: query += " AND category=$3"; params.append(category)
        if parent_id is not None:
            query += " AND parent_id=$3" if not category else " AND parent_id=$4"; params.append(parent_id)
        if due_date_range:
            query += " AND due_date >= $3 AND due_date <= $4" if not category and parent_id is None else " AND due_date >= $4 AND due_date <= $5"
            params.extend(due_date_range)
        query += " ORDER BY due_date ASC NULLS LAST, created_at DESC"
        return await conn.fetch(query, *params)

async def complete_task(uid, task_id):
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE tasks SET status='completed', completed_at=NOW() WHERE id=$1 AND user_id=$2", task_id, uid)
async def delete_task(uid, task_id):
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM tasks WHERE id=$1 AND user_id=$2", task_id, uid)
async def get_task_stats(uid):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow("SELECT COUNT(*) FILTER (WHERE status='pending') as pending, COUNT(*) FILTER (WHERE status='completed') as completed, COUNT(*) FILTER (WHERE category='work') as work, COUNT(*) FILTER (WHERE category='personal') as personal, COUNT(*) FILTER (WHERE category='shopping') as shopping FROM tasks WHERE user_id=$1", uid)
async def get_subtasks(uid, parent_id):
    async with db_pool.acquire() as conn:
        return await conn.fetch("SELECT id, title, status, priority FROM tasks WHERE user_id=$1 AND parent_id=$2 ORDER BY created_at", uid, parent_id)

NOTE_TEMPLATES = {"shopping": "🛒 Список покупок:\n- \n- \n- ", "ideas": "💡 Идеи:\n• \n• \n• ", "contacts": "📞 Контакты:\nИмя: \nТелефон: \nEmail: ", "meeting": "🤝 Встреча:\nДата: \nУчастники: \nПовестка: ", "todo": "✅ To-Do:\n[ ] \n[ ] \n[ ] "}
async def create_note(uid, content, tags=None, category="general"):
    async with db_pool.acquire() as conn:
        return await conn.fetchval("INSERT INTO notes(user_id, content, tags, category) VALUES ($1, $2, $3, $4) RETURNING id", uid, content, tags, category)
async def get_notes(uid, limit=10, search=None, category=None):
    async with db_pool.acquire() as conn:
        query = "SELECT id, content, tags, category, created_at FROM notes WHERE user_id=$1"
        params = [uid]
        if search: query += " AND (content ILIKE $2 OR tags::text ILIKE $2)"; params.append(f"%{search}%")
        if category: query += " AND category=$2" if not search else " AND category=$3"; params.append(category)
        query += f" ORDER BY created_at DESC LIMIT ${len(params)+1}"; params.append(limit)
        return await conn.fetch(query, *params)
async def delete_note(uid, note_id):
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM notes WHERE id=$1 AND user_id=$2", note_id, uid)

async def create_calendar_event(uid, title, description, event_date, reminder_before=None, recurrence=None, category="general"):
    async with db_pool.acquire() as conn:
        return await conn.fetchval("INSERT INTO calendar_events(user_id, title, description, event_date, reminder_before, recurrence, category) VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING id", uid, title, description, event_date, reminder_before, recurrence, category)
async def get_calendar_events(uid, from_date=None, to_date=None, category=None, limit=10):
    async with db_pool.acquire() as conn:
        query = "SELECT id, title, description, event_date, reminder_before, recurrence, category FROM calendar_events WHERE user_id=$1"
        params = [uid]
        if from_date: query += " AND event_date >= $2"; params.append(from_date)
        if to_date: query += " AND event_date <= $3" if from_date else " AND event_date <= $2"; params.append(to_date if from_date else to_date)
        if category: query += f" AND category=${len(params)+1}"; params.append(category)
        query += f" ORDER BY event_date ASC LIMIT ${len(params)+1}"; params.append(limit)
        return await conn.fetch(query, *params)

async def create_habit(uid, name, frequency="daily", target_per_week=7):
    async with db_pool.acquire() as conn:
        if not await conn.fetchval("SELECT id FROM habits WHERE user_id=$1 AND name=$2", uid, name):
            return await conn.fetchval("INSERT INTO habits(user_id, name, frequency, target_per_week) VALUES ($1,$2,$3,$4) RETURNING id", uid, name, frequency, target_per_week)
        return None
async def get_habits(uid):
    async with db_pool.acquire() as conn:
        return await conn.fetch("SELECT id, name, streak, last_done, frequency, target_per_week FROM habits WHERE user_id=$1", uid)
async def complete_habit(uid, habit_id):
    async with db_pool.acquire() as conn:
        today = now_moscow().date()
        await conn.execute("UPDATE habits SET streak = CASE WHEN last_done = $2 THEN streak ELSE streak + 1 END, last_done = $2 WHERE id=$1 AND user_id=$3", habit_id, today, uid)
async def get_habits_progress(uid):
    async with db_pool.acquire() as conn:
        habits = await conn.fetch("SELECT id, name, frequency, target_per_week, last_done FROM habits WHERE user_id=$1", uid)
        week_start = now_moscow().date() - timedelta(days=now_moscow().weekday())
        result = []
        for h in habits:
            completed = 1 if h["last_done"] and h["last_done"] >= week_start else 0
            percent = min(100, int((1 if h["last_done"] and h["last_done"] >= week_start else 0) / max(1, h["target_per_week"]) * 100))
            result.append({"name": h["name"], "frequency": h["frequency"], "target": h["target_per_week"], "completed": completed, "percent": percent})
        return result

async def get_profile(uid):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT name, age, gender, city, mode FROM profile WHERE user_id=$1", uid)
        return dict(row) if row else None
async def save_profile(uid, name=None, age=None, gender=None, city=None):
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO profile(user_id, name, age, gender, city) VALUES ($1, $2, $3, $4, $5) ON CONFLICT(user_id) DO UPDATE SET name = COALESCE($2, profile.name), age = COALESCE($3, profile.age), gender = COALESCE($4, profile.gender), city = COALESCE($5, profile.city), updated_at = NOW()", uid, name, age, gender, city)

async def get_dashboard_data(uid: int, profile: dict) -> dict:
    city = profile.get("city", CITY_DEFAULT) if profile else CITY_DEFAULT
    now = now_moscow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    weather, tasks, events, habits_prog = await asyncio.gather(get_weather_data(city), get_tasks(uid, status="pending", due_date_range=(today_start, today_end)), get_calendar_events(uid, from_date=now, to_date=now+timedelta(hours=12)), get_habits_progress(uid), return_exceptions=True)
    return {"weather": weather if not isinstance(weather, Exception) else None, "city": city, "tasks_today": tasks if not isinstance(tasks, Exception) else [], "events_12h": events if not isinstance(events, Exception) else [], "habits_progress": habits_prog if not isinstance(habits_prog, Exception) else [], "stats": await get_task_stats(uid), "time": now.strftime("%H:%M")}

def format_dashboard(data: dict) -> str:
    lines = [f"📊 **Дашборд** • {data['time']}"]
    if data["weather"]:
        w = data["weather"]
        lines.append(f"\n🌤 **{data['city']}**: {w['temp']}°, {w['description']}\n💧 {w['humidity']}%  🌬 {w['wind']} м/с")
    if data["tasks_today"]:
        lines.append(f"\n📋 **Задачи на сегодня** ({len(data['tasks_today'])}):")
        for t in data["tasks_today"][:3]:
            due = f" ({t['due_date'].strftime('%H:%M')})" if t["due_date"] else ""
            lines.append(f"• {t['title']}{due}")
    if data["events_12h"]:
        lines.append(f"\n📅 **События**:")
        for e in data["events_12h"][:3]:
            lines.append(f"• {e['event_date'].strftime('%H:%M')} — {e['title']}")
    if data["habits_progress"]:
        lines.append(f"\n🔁 **Привычки**:")
        for h in data["habits_progress"][:3]:
            bar = "█" * (h["percent"]//10) + "░" * (10 - h["percent"]//10)
            lines.append(f"• {h['name']}: [{bar}] {h['percent']}%")
    return "\n".join(lines)

# ======================
#  INLINE КЛАВИАТУРЫ / FSM
# ======================
def main_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Задачи", callback_data="tasks_list"), InlineKeyboardButton(text="📝 Заметки", callback_data="notes_list")],
        [InlineKeyboardButton(text="🔁 Привычки", callback_data="habits_list"), InlineKeyboardButton(text="📅 Календарь", callback_data="calendar_list")],
        [InlineKeyboardButton(text="⏰ Напомнить", callback_data="reminders_list"), InlineKeyboardButton(text="📊 Дашборд", callback_data="dashboard_show")],
        [InlineKeyboardButton(text="🌤 Погода", callback_data="ext_weather"), InlineKeyboardButton(text="🧠 Психоанализ", callback_data="ext_psycho")],
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

def note_category_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Покупки", callback_data="note_cat_shopping"), InlineKeyboardButton(text="💡 Идеи", callback_data="note_cat_ideas")],
        [InlineKeyboardButton(text="📞 Контакты", callback_data="note_cat_contacts"), InlineKeyboardButton(text="🔧 Другое", callback_data="note_cat_general")]
    ])

def note_template_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Список покупок", callback_data="note_tpl_shopping"), InlineKeyboardButton(text="💡 Идеи", callback_data="note_tpl_ideas")],
        [InlineKeyboardButton(text="📞 Контакты", callback_data="note_tpl_contacts"), InlineKeyboardButton(text="✅ To-Do", callback_data="note_tpl_todo")],
        [InlineKeyboardButton(text="❌ Без шаблона", callback_data="note_tpl_none")]
    ])

def task_actions_keyboard(task_id, has_subtasks=False, has_checklist=False):
    buttons = [[InlineKeyboardButton(text="✅ Выполнить", callback_data=f"task_complete_{task_id}")]]
    if has_subtasks: buttons.append([InlineKeyboardButton(text="📝 Подзадачи", callback_data=f"task_subtasks_{task_id}")])
    if has_checklist: buttons.append([InlineKeyboardButton(text="📋 Чек-лист", callback_data=f"task_checklist_{task_id}")])
    buttons.append([InlineKeyboardButton(text="🗑 Удалить", callback_data=f"task_delete_{task_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def note_actions_keyboard(note_id):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🗑 Удалить заметку", callback_data=f"note_delete_{note_id}")]])

def external_link_keyboard(link: str, label: str = "Открыть"):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"🔗 {label}", url=link)]])

def dashboard_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="dashboard_refresh")],
        [InlineKeyboardButton(text="📋 Задачи", callback_data="tasks_list"), InlineKeyboardButton(text="📅 Календарь", callback_data="calendar_list")]
    ])

class TaskFSM(StatesGroup):
    title = State(); description = State(); priority = State(); due_date = State()
    category = State(); tags = State(); recurrence = State(); attachments = State()
class NoteFSM(StatesGroup): template = State(); category = State(); content = State(); tags = State()
class CalendarFSM(StatesGroup): title=State(); description=State(); event_date=State(); recurrence=State()
class ProfileEditFSM(StatesGroup): field=State(); value=State()

# ======================
#  🔥 AI: ОБЩИЙ ЧАТ
# ======================
async def call_openai_chat(user_text: str, profile: dict = None, mood: str = "нейтральное", memory: list = None):
    if not OPENROUTER_API_KEY: return await call_qwen_fallback(user_text, profile, mood, memory)
    user_name = profile.get("name") if profile else ""
    city = profile.get("city", CITY_DEFAULT) if profile else CITY_DEFAULT
    is_short = any(k in user_text.lower() for k in ["шутк", "анекдот", "прикол", "факт", "коротко", "в двух словах"])
    system_prompt = f"""Ты — AssistEmpat, личный помощник {user_name or 'пользователя'}. Город: {city}.
ВОЗМОЖНОСТИ: задачи, заметки, календарь, погода, кино, новости, дашборд.
ПРАВИЛА: 1. Если "привет"/"новая тема"/"забудь" — начинай заново. 2. Развёрнуто (3-5 предл.), но кратко если просят шутку/факт. 3. Дружелюбно, эмодзи умеренно. 4. Не навязывай помощь с "проблемами" при болтовне. Настроение: {mood}"""
    fm, seen = [], set()
    for m in reversed(memory[-5:] if memory else []):
        c = m["content"].strip()
        if c and len(c)>3 and c not in seen: fm.insert(0,m); seen.add(c)
    ctx = "\n".join([f"{m['role']}: {m['content']}" for m in fm])
    try:
        async with httpx.AsyncClient(timeout=15) as cl:
            r = await cl.post("https://openrouter.ai/api/v1/chat/completions", headers={"Authorization":f"Bearer {OPENROUTER_API_KEY}","Content-Type":"application/json"}, json={"model":"openai/gpt-4o-mini","messages":[{"role":"system","content":system_prompt},{"role":"user","content":f"{ctx}\n\n{user_text}" if ctx else user_text}], "temperature":0.9 if is_short else 0.7, "max_tokens":150 if is_short else 500})
            r.raise_for_status()
            ans = r.json()["choices"][0]["message"]["content"].strip()
            if await is_duplicate_response(profile.get("user_id") if profile else 0, ans): return get_fallback_response(user_text, mood)
            return ans
    except Exception as e:
        logging.error(f"OpenAI error: {e}")
        return await call_qwen_fallback(user_text, profile, mood, memory)

# ======================
#  🔥 AI: РЕЖИМ ЗДОРОВЬЯ
# ======================
async def call_health_ai(user_text: str, profile: dict, health_mem: list):
    if not OPENROUTER_API_KEY: return await call_qwen_fallback(user_text, profile, "нейтральное", health_mem)
    system_prompt = """Ты — ассистент по здоровому образу жизни.
ПРАВИЛА: 1. Только ЗОЖ: режим, питание, гидратация, отдых, активность, гигиена, стресс-менеджмент. 2. НИКОГДА не называй препараты/БАДы/дозы. 3. При боли/температуре — рекомендуй врача. 4. Кратко, по делу, поддерживающе. 5. Дисклеймер: "Рекомендации не заменяют консультацию специалиста." Настроение учитывай, фокус на пользе."""
    ctx = "\n".join([f"{m['role']}: {m['content']}" for m in health_mem[-4:]])
    try:
        async with httpx.AsyncClient(timeout=15) as cl:
            r = await cl.post("https://openrouter.ai/api/v1/chat/completions", headers={"Authorization":f"Bearer {OPENROUTER_API_KEY}","Content-Type":"application/json"}, json={"model":"openai/gpt-4o-mini","messages":[{"role":"system","content":system_prompt},{"role":"user","content":f"{ctx}\n\n{user_text}" if ctx else user_text}], "temperature":0.5, "max_tokens":400})
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
    except:
        return "🩺 Я не могу дать медицинский совет. Рекомендую обратиться к врачу."

# ======================
#  🔥 AI: РЕЖИМ ПСИХОАНАЛИЗА (АДАПТИВНЫЙ ТОН)
# ======================
def detect_psycho_style(text: str, mood: str) -> tuple[str, float]:
    """Определяет стиль ответа и температуру для психоанализа"""
    t = text.lower()
    # 🔥 Жёсткий тон: когда нужно "встряхнуть"
    if any(k in t for k in ["пинка", "встряхни", "достал себя жалеть", "хватит ныть", "что делать", "застрял", "не могу решиться", "дай совет", "как быть"]):
        return "tough", 0.4
    # 😏 Сарказм/ирония: когда пользователь в ресурсе
    if mood == "радость" or any(k in t for k in ["посмеяться", "ирония", "сарказм", "по-доброму", "подколи", "шутк"]):
        return "sarcastic", 0.95
    # 🤍 Эмпатия: грусть, тревога, усталость
    if mood in ["грусть", "тревога", "усталость"]:
        return "empathetic", 0.6
    # 🧠 Аналитика: нейтральный запрос
    return "analytical", 0.75

async def call_psycho_ai(user_text: str, profile: dict, psycho_mem: list, mood: str):
    """Адаптивный психоанализ: эмпатия, аналитика, жёсткий тон или сарказм"""
    if not OPENROUTER_API_KEY:
        return await call_qwen_fallback(user_text, profile, mood, psycho_mem)
    
    style, temperature = detect_psycho_style(user_text, mood)
    
    style_prompts = {
        "empathetic": f"""Ты — эмпатичный психоаналитик. Твоя задача — выслушать, отразить чувства, помочь пользователю разобраться в себе.
ПРАВИЛА: 1. Начинай с отражения эмоций ("Я слышу, что ты чувствуешь..."). 2. Задавай мягкие уточняющие вопросы. 3. Не давай готовых решений — помогай найти свои. 4. Будь тёплым, человечным, без клише. 5. Дисклеймер в конце сеанса: "Я не заменяю профессионального психолога." Настроение: {mood}""",
        
        "analytical": f"""Ты — аналитичный психоаналитик. Твоя задача — помочь пользователю структурировать мысли и увидеть ситуацию под разными углами.
ПРАВИЛА: 1. Разложи ситуацию на факты/чувства/возможности. 2. Задавай логичные уточняющие вопросы. 3. Предлагай варианты, но не навязывай. 4. Будь объективным, но поддерживающим. 5. Дисклеймер: "Я не заменяю профессионального психолога." Настроение: {mood}""",
        
        "tough": f"""Ты — прямой психоаналитик "жёсткой любви". Твоя задача — помочь пользователю выйти из застоя, взяв ответственность.
ПРАВИЛА: 1. Говори чётко, без воды. 2. Задавай прямые вопросы о действиях СЕГОДНЯ. 3. Не позволяй уходить в самокопание без вывода. 4. Поддерживай, но требуй конкретики. 5. Дисклеймер: "Я не заменяю профессионального психолога." Настроение: {mood}""",
        
        "sarcastic": f"""Ты — психоаналитик с лёгкой иронией. Твоя задача — помочь пользователю увидеть ситуацию с юмором и снять напряжение.
ПРАВИЛА: 1. Используй добрый сарказм, не обижая. 2. Помогай увидеть абсурдность застоя через юмор. 3. После иронии — мягкий переход к действиям. 4. Следи, чтобы пользователь был в ресурсе для такого тона. 5. Дисклеймер: "Я не заменяю профессионального психолога." Настроение: {mood}"""
    }
    
    system_prompt = style_prompts.get(style, style_prompts["analytical"])
    ctx = "\n".join([f"{m['role']}: {m['content']}" for m in psycho_mem[-6:]])
    
    try:
        async with httpx.AsyncClient(timeout=20) as cl:
            r = await cl.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "openai/gpt-4o-mini",
                    "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": f"{ctx}\n\n{user_text}" if ctx else user_text}],
                    "temperature": temperature,
                    "max_tokens": 1500
                }
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
    except:
        return "🧠 Я здесь, чтобы выслушать. Расскажи, что у тебя на душе?"

# ======================
#  🔥 FALLBACKS
# ======================
def get_fallback_response(user_text: str, mood: str) -> str:
    if mood == "грусть": return "Понимаю. Расскажи, что случилось? 🤍"
    if mood == "тревога": return "Всё будет хорошо. Что беспокоит?"
    if mood == "усталость": return "Отдохни. Я тут, если что. 🫂"
    return "Понял. 👍"

async def call_qwen_fallback(user_text, profile, mood, memory):
    if not QWEN_API_KEY: return get_fallback_response(user_text, mood)
    user_name = profile.get("name") if profile else ""
    sys = f"Ты — {user_name or 'помощник'}. Отвечай кратко."
    ctx = "\n".join([f"{m['role']}: {m['content']}" for m in (memory or [])[-2:]])
    try:
        async with httpx.AsyncClient(timeout=10) as cl:
            r = await cl.post("https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/text-generation/generation", headers={"Authorization":f"Bearer {QWEN_API_KEY}"}, json={"model":"qwen-max","messages":[{"role":"system","content":sys},{"role":"user","content":f"{ctx}\n\n{user_text}" if ctx else user_text}], "temperature":0.7})
            r.raise_for_status()
            return r.json()["output"]["text"].strip()
    except: return get_fallback_response(user_text, mood)

# ======================
#  ВСПОМОГАТЕЛЬНЫЕ
# ======================
async def save_memory(uid, role, content):
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO memory(user_id,role,content) VALUES ($1,$2,$3)", uid, role, content)
        await conn.execute("DELETE FROM memory WHERE user_id=$1 AND id NOT IN (SELECT id FROM memory WHERE user_id=$1 ORDER BY created_at DESC LIMIT 20)", uid)
async def get_memory(uid):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT role,content FROM memory WHERE user_id=$1 ORDER BY created_at DESC LIMIT 6", uid)
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
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
    text = text.lower(); now = now_moscow()
    if "вечером" in text: dt = now.replace(hour=19,minute=0); return dt if dt>now else dt+timedelta(days=1)
    if "после работы" in text: dt = now.replace(hour=18,minute=30); return dt if dt>now else dt+timedelta(days=1)
    if "завтра" in text: return (now+timedelta(days=1)).replace(hour=9,minute=0)
    m = re.search(r'через (\d+)\s*минут?', text); h = re.search(r'через (\d+)\s*час', text)
    if m: return now+timedelta(minutes=int(m.group(1)))
    if h: return now+timedelta(hours=int(h.group(1)))
    return None

# ======================
#  ПАРСЕР КОМАНД
# ======================
RU_COMMANDS = {
    "меню":"show_menu", "задачи":"list_tasks", "заметк":"notes_list", "календар":"calendar_list",
    "привычк":"habits_list", "погод":"ext_weather", "курс":"ext_currency", "здоровье":"ext_health",
    "психо":"ext_psycho", "кино":"ext_cinema", "новост":"ext_news", "профиль":"profile_show", "мой профиль":"profile_show",
    "помощь":"help_show", "дашборд":"dashboard_show", "сброс":"reset_context", "reset":"reset_context", "забудь":"reset_context",
    "очисти память":"reset_context", "новая тема":"reset_context"
}
def parse_ru_command(text:str) -> str|None:
    text_lower = text.lower().strip()
    for keyword,cmd in RU_COMMANDS.items():
        if keyword in text_lower: return cmd
    return None

# ======================
#  ХЕНДЛЕРЫ: КОМАНДЫ
# ======================
@dp.message(Command("start"))
async def cmd_start(msg:Message, state:FSMContext):
    await state.clear()
    await clear_user_context(msg.from_user.id)
    profile = await get_profile(msg.from_user.id)
    name = profile["name"] if profile and profile["name"] else ""
    await msg.answer(f"Привет, {name}." if name else "Привет. Как тебя зовут?", reply_markup=main_menu_keyboard())

@dp.message(Command("reset", "clear"))
async def cmd_reset(msg:Message):
    await clear_user_context(msg.from_user.id)
    await msg.answer("✅ Контекст очищен. Начинаем с чистого листа!")

@dp.message(Command("help"))
async def cmd_help(msg:Message):
    await msg.answer("""📋 **Команды:**
📊 /dashboard — сводка дня
📝 /note — заметки
📅 /event — события
📋 /task — задачи
🔁 /habit — привычки
🔄 /reset — сбросить контекст
⏰ "напомни [что] [когда]"
🌤 /weather, 💱 /currency, 🩺 /health, 🧠 /psycho, 🎬 /cinema, 📰 /news
👤 /profile — мой профиль
Или нажми кнопку 👇""", parse_mode="Markdown", reply_markup=main_menu_keyboard())

@dp.message(Command("profile"))
async def cmd_profile(msg:Message, state:FSMContext):
    p = await get_profile(msg.from_user.id)
    if not p: await msg.answer("Нет данных. Напиши: 'меня зовут...', 'город: СПб'"); return
    text = f"👤 **Профиль**\nИмя: {p['name'] or '—'}\nГород: {p['city'] or CITY_DEFAULT} 🌍\n\n✏️ /profile edit"
    await msg.answer(text, parse_mode="Markdown", reply_markup=profile_edit_keyboard())

@dp.message(Command("profile", "edit"))
async def cmd_profile_edit(msg:Message, state:FSMContext):
    await state.set_state(ProfileEditFSM.field)
    await msg.answer("✏️ Что изменить?", reply_markup=profile_edit_keyboard())

@dp.message(Command("stats"))
async def cmd_stats(msg:Message):
    s = await get_task_stats(msg.from_user.id)
    await msg.answer(f"📊 Задачи: {s['pending'] or 0} активных, {s['completed'] or 0} выполнено")

@dp.message(Command("news"))
async def cmd_news(msg:Message):
    news = await get_news_data()
    if news: text = "📰 **Новости**:\n" + "\n".join([f"• {n['title']}" for n in news]); await msg.answer(text, reply_markup=external_link_keyboard(get_news_link(), "Все новости"))
    else: await msg.answer("📰 Новости:", reply_markup=external_link_keyboard(get_news_link(), "Яндекс.Новости"))

# ======================
#  🔥 ДАШБОРД / ПРОФИЛЬ / ЗАМЕТКИ / КАЛЕНДАРЬ / ЗАДАЧИ
# ======================
@dp.message(Command("dashboard"))
async def cmd_dashboard(msg:Message):
    profile = await get_profile(msg.from_user.id)
    data = await get_dashboard_data(msg.from_user.id, profile)
    await msg.answer(format_dashboard(data), parse_mode="Markdown", reply_markup=dashboard_keyboard())

@dp.callback_query(F.data=="dashboard_show")
async def cb_dashboard(call:CallbackQuery):
    profile = await get_profile(call.from_user.id)
    data = await get_dashboard_data(call.from_user.id, profile)
    await call.message.edit_text(format_dashboard(data), parse_mode="Markdown", reply_markup=dashboard_keyboard())
    await call.answer()

@dp.callback_query(F.data=="dashboard_refresh")
async def cb_dashboard_refresh(call:CallbackQuery): await cb_dashboard(call)

@dp.callback_query(F.data.startswith("profile_edit_"))
async def profile_edit_cb(call:CallbackQuery, state:FSMContext):
    field = call.data.split("_")[-1]
    await state.update_data(field=field)
    await state.set_state(ProfileEditFSM.value)
    prompts = {"name": "✏️ Новое имя:", "age": "✏️ Возраст (число):", "gender": "✏️ Пол (муж/жен):", "city": "✏️ Город:"}
    await call.message.answer(prompts.get(field, "✏️ Введите:"))
    await call.answer()

@dp.message(ProfileEditFSM.value)
async def profile_save_value(msg:Message, state:FSMContext):
    data = await state.get_data()
    field, value = data.get("field"), msg.text.strip()
    if field == "age":
        try: value = int(value)
        except: await msg.answer("❌ Возраст — число"); return
    await save_profile(msg.from_user.id, **{field: value})
    await msg.answer(f"✅ {field}: {value}")
    await state.clear()
    p = await get_profile(msg.from_user.id)
    await msg.answer(f"👤 {p['name'] or '—'} • {p['city'] or CITY_DEFAULT} 🌍", reply_markup=profile_edit_keyboard())

@dp.callback_query(F.data=="profile_done")
async def profile_done_cb(call:CallbackQuery, state:FSMContext):
    await state.clear()
    await call.answer("✅ Сохранено", show_alert=True)

@dp.message(Command("note"))
async def cmd_note_start(msg:Message, state:FSMContext):
    await state.set_state(NoteFSM.template)
    await msg.answer("📝 Шаблон:", reply_markup=note_template_keyboard())

@dp.callback_query(F.data.startswith("note_tpl_"))
async def note_template_cb(call:CallbackQuery, state:FSMContext):
    tpl = call.data.split("_")[-1]
    await state.update_data(template=tpl if tpl != "none" else None)
    await state.set_state(NoteFSM.category)
    await call.message.edit_text("📂 Категория:", reply_markup=note_category_keyboard())
    await call.answer()

@dp.callback_query(F.data.startswith("note_cat_"))
async def note_category_cb(call:CallbackQuery, state:FSMContext):
    cat = call.data.split("_")[-1]
    await state.update_data(category=cat)
    await state.set_state(NoteFSM.content)
    tpl = (await state.get_data()).get("template")
    content = NOTE_TEMPLATES.get(tpl, "") if tpl else ""
    await call.message.edit_text(f"📝 Текст:\n{content}\n(/skip — отмена)")
    await call.answer()

@dp.message(NoteFSM.content, F.text=="/skip")
async def note_skip(msg:Message, state:FSMContext): await state.clear(); await msg.answer("❌ Отменено")
@dp.message(NoteFSM.content)
async def note_content(msg:Message, state:FSMContext):
    data = await state.get_data()
    content = (data.get("template") and NOTE_TEMPLATES.get(data["template"]) or "") + msg.text
    await state.update_data(content=content)
    await state.set_state(NoteFSM.tags)
    await msg.answer("🏷 Теги (через запятую, /skip — пропустить):")
@dp.message(NoteFSM.tags, F.text=="/skip")
async def note_tags_skip(msg:Message, state:FSMContext):
    data = await state.get_data()
    note_id = await create_note(msg.from_user.id, data["content"], None, data.get("category","general"))
    await msg.answer(f"✅ #{note_id}", reply_markup=note_actions_keyboard(note_id))
    await state.clear()
@dp.message(NoteFSM.tags)
async def note_tags(msg:Message, state:FSMContext):
    tags = [t.strip() for t in msg.text.split(",") if t.strip()]
    data = await state.get_data()
    note_id = await create_note(msg.from_user.id, data["content"], tags, data.get("category","general"))
    await msg.answer(f"✅ #{note_id}", reply_markup=note_actions_keyboard(note_id))
    await state.clear()
@dp.message(Command("notes"))
async def cmd_notes(msg:Message):
    notes = await get_notes(msg.from_user.id)
    if not notes: await msg.answer("📝 Нет заметок. /note", reply_markup=main_menu_keyboard()); return
    text = "📝 **Заметки**:\n" + "\n".join([f"#{n['id']} [{n['category']}] {n['content'][:60]}..." for n in notes[:5]])
    await msg.answer(text, reply_markup=main_menu_keyboard())

@dp.message(Command("event"))
async def cmd_event_start(msg:Message, state:FSMContext):
    await state.set_state(CalendarFSM.title)
    await msg.answer("📅 Название:")
@dp.message(CalendarFSM.title)
async def event_title(msg:Message, state:FSMContext):
    await state.update_data(title=msg.text)
    await state.set_state(CalendarFSM.description)
    await msg.answer("📄 Описание (/skip):")
@dp.message(CalendarFSM.description, F.text=="/skip")
async def event_desc_skip(msg:Message, state:FSMContext):
    await state.update_data(description=None)
    await state.set_state(CalendarFSM.event_date)
    await msg.answer("🗓 Когда? ('завтра в 18:00'):")
@dp.message(CalendarFSM.description)
async def event_description(msg:Message, state:FSMContext):
    await state.update_data(description=msg.text)
    await state.set_state(CalendarFSM.event_date)
    await msg.answer("🗓 Когда? ('завтра в 18:00'):")
@dp.message(CalendarFSM.event_date)
async def event_date(msg:Message, state:FSMContext):
    event_date = parse_time(msg.text)
    if not event_date: await msg.answer("❌ Не понял дату"); return
    await state.update_data(event_date=event_date)
    await state.set_state(CalendarFSM.recurrence)
    await msg.answer("🔄 Повтор:", reply_markup=task_recurrence_keyboard())
@dp.callback_query(F.data.startswith("rec_"))
async def event_recurrence_cb(call:CallbackQuery, state:FSMContext):
    recurrence = call.data.split("_")[1] if call.data != "rec_none" else None
    await state.update_data(recurrence=recurrence)
    data = await state.get_data()
    event_id = await create_calendar_event(call.from_user.id, data["title"], data.get("description"), data["event_date"], recurrence=recurrence)
    await call.message.answer(f"✅ #{event_id}: {data['title']}\n🗓 {data['event_date'].astimezone(MOSCOW_TZ).strftime('%d.%m %H:%M')}")
    await state.clear()
    await call.answer()
@dp.message(Command("calendar"))
async def cmd_calendar(msg:Message):
    events = await get_calendar_events(msg.from_user.id)
    if not events: await msg.answer("📅 Нет событий. /event", reply_markup=main_menu_keyboard()); return
    text = "📅 **События**:\n" + "\n".join([f"• {e['title']}\n🗓 {e['event_date'].astimezone(MOSCOW_TZ).strftime('%d.%m %H:%M')}" for e in events[:5]])
    await msg.answer(text, reply_markup=main_menu_keyboard())

@dp.message(Command("task"))
async def cmd_task_start(msg:Message, state:FSMContext):
    await state.set_state(TaskFSM.title)
    await msg.answer("📝 Название:")
@dp.message(TaskFSM.title)
async def task_title(msg:Message, state:FSMContext):
    await state.update_data(title=msg.text)
    await state.set_state(TaskFSM.description)
    await msg.answer("📄 Описание (/skip):")
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
    await call.message.edit_text(f"✅ {priority}")
    await state.set_state(TaskFSM.due_date)
    await call.message.answer("📅 Срок (/skip):")
@dp.message(TaskFSM.due_date, F.text=="/skip")
async def task_skip_due(msg:Message, state:FSMContext):
    await state.update_data(due_date=None)
    await state.set_state(TaskFSM.category)
    await msg.answer("📂 Категория:", reply_markup=task_category_keyboard())
@dp.message(TaskFSM.due_date)
async def task_due_date(msg:Message, state:FSMContext):
    await state.update_data(due_date=parse_time(msg.text))
    await state.set_state(TaskFSM.category)
    await msg.answer("📂 Категория:", reply_markup=task_category_keyboard())
@dp.callback_query(F.data.startswith("cat_"))
async def task_category_cb(call:CallbackQuery, state:FSMContext):
    await state.update_data(category=call.data.split("_")[1])
    await call.message.edit_text("✅ Категория")
    await state.set_state(TaskFSM.tags)
    await call.message.answer("🏷 Теги (/skip):")
@dp.message(TaskFSM.tags, F.text=="/skip")
async def task_skip_tags(msg:Message, state:FSMContext):
    await state.update_data(tags=None)
    await state.set_state(TaskFSM.recurrence)
    await msg.answer("🔄 Повтор:", reply_markup=task_recurrence_keyboard())
@dp.message(TaskFSM.tags)
async def task_tags(msg:Message, state:FSMContext):
    await state.update_data(tags=[t.strip() for t in msg.text.split(",") if t.strip()])
    await state.set_state(TaskFSM.recurrence)
    await msg.answer("🔄 Повтор:", reply_markup=task_recurrence_keyboard())
@dp.callback_query(F.data.startswith("rec_"))
async def task_recurrence_cb(call:CallbackQuery, state:FSMContext):
    await state.update_data(recurrence=call.data.split("_")[1] if call.data != "rec_none" else None)
    await state.set_state(TaskFSM.attachments)
    await call.message.answer("📎 Вложения (/skip):")
    await call.answer()
@dp.message(TaskFSM.attachments, F.text=="/skip")
async def task_skip_attachments(msg:Message, state:FSMContext): await _finish_task_creation(msg, state, None)
@dp.message(TaskFSM.attachments)
async def task_attachments(msg:Message, state:FSMContext): await _finish_task_creation(msg, state, [a.strip() for a in msg.text.split(",") if a.strip()])
async def _finish_task_creation(msg:Message, state:FSMContext, attachments):
    data = await state.get_data()
    task_id = await create_task(uid=msg.from_user.id, title=data["title"], description=data.get("description"), priority=data.get("priority","medium"), due_date=data.get("due_date"), category=data.get("category","general"), tags=data.get("tags"), parent_id=None, recurrence=data.get("recurrence"), attachments=attachments)
    await msg.answer(f"✅ #{task_id}: {data['title']}", reply_markup=task_actions_keyboard(task_id))
    await state.clear()
@dp.message(Command("tasks"))
async def cmd_tasks(msg:Message):
    tasks = await get_tasks(msg.from_user.id)
    if not tasks: await msg.answer("📋 Нет задач. /task", reply_markup=main_menu_keyboard()); return
    text = "📋 **Задачи**:\n" + "\n".join([f"• {t['title']}" + (f" ({t['due_date'].astimezone(MOSCOW_TZ).strftime('%H:%M')})" if t['due_date'] else "") for t in tasks[:5]])
    await msg.answer(text, reply_markup=main_menu_keyboard())

# ======================
#  CALLBACKS
# ======================
@dp.callback_query(F.data=="tasks_list")
async def cb_tasks(call:CallbackQuery):
    tasks = await get_tasks(call.from_user.id)
    await call.message.edit_text("📋 Задачи:\n" + "\n".join([f"• {t['title']}" for t in tasks[:5]]) if tasks else "Нет задач", reply_markup=main_menu_keyboard())
@dp.callback_query(F.data.startswith("task_complete_"))
async def cb_task_done(call:CallbackQuery):
    await complete_task(call.from_user.id, int(call.data.split("_")[-1]))
    await call.answer("✅"); await call.message.delete()
@dp.callback_query(F.data.startswith("task_delete_"))
async def cb_task_del(call:CallbackQuery):
    await delete_task(call.from_user.id, int(call.data.split("_")[-1]))
    await call.answer("🗑"); await call.message.delete()
@dp.callback_query(F.data.startswith("task_subtasks_"))
async def cb_task_subtasks(call:CallbackQuery):
    subtasks = await get_subtasks(call.from_user.id, int(call.data.split("_")[-1]))
    await call.message.answer("📋 Подзадачи:\n" + "\n".join([f"• {st['title']}" for st in subtasks]) if subtasks else "Нет подзадач")
@dp.callback_query(F.data=="notes_list")
async def cb_notes(call:CallbackQuery):
    notes = await get_notes(call.from_user.id)
    await call.message.edit_text("📝 Заметки:\n" + "\n".join([f"#{n['id']} {n['content'][:40]}..." for n in notes[:5]]) if notes else "Нет заметок", reply_markup=main_menu_keyboard())
@dp.callback_query(F.data=="calendar_list")
async def cb_calendar(call:CallbackQuery):
    events = await get_calendar_events(call.from_user.id)
    await call.message.edit_text("📅 События:\n" + "\n".join([f"• {e['title']}" for e in events[:5]]) if events else "Нет событий", reply_markup=main_menu_keyboard())
@dp.callback_query(F.data=="habits_list")
async def cb_habits(call:CallbackQuery):
    habits = await get_habits(call.from_user.id)
    await call.message.edit_text("🔁 Привычки:\n" + "\n".join([f"• {h['name']}: {h['streak']} дн." for h in habits]) if habits else "Нет привычек", reply_markup=main_menu_keyboard())
@dp.callback_query(F.data=="reminders_list")
async def cb_reminders(call:CallbackQuery):
    await call.message.answer("⏰ Напиши: 'напомни [что] [когда]'"); await call.answer()
@dp.callback_query(F.data=="profile_show")
async def cb_profile(call:CallbackQuery):
    p = await get_profile(call.from_user.id)
    await call.answer(f"👤 {p['name'] or '—'} • {p['city'] or CITY_DEFAULT}", show_alert=True)
@dp.callback_query(F.data=="help_show")
async def cb_help(call:CallbackQuery): await call.answer("/help — список команд", show_alert=True)
@dp.callback_query(F.data.startswith("note_delete_"))
async def cb_note_del(call:CallbackQuery):
    await delete_note(call.from_user.id, int(call.data.split("_")[-1]))
    await call.answer("🗑"); await call.message.delete()

# ======================
#  🔥 ВНЕШНИЕ ДАННЫЕ: CALLBACKS
# ======================
@dp.callback_query(F.data=="ext_weather")
async def cb_ext_weather(call:CallbackQuery):
    profile = await get_profile(call.from_user.id)
    city = profile.get("city") if profile and profile.get("city") else CITY_DEFAULT
    weather = await get_weather_data(city)
    if weather: await call.message.answer(f"🌤 {city}: {weather['temp']}°, {weather['description']}")
    else: await call.message.answer(f"🌤 {city}:", reply_markup=external_link_keyboard(get_weather_link(city), "Яндекс.Погода"))
    await call.answer()

@dp.callback_query(F.data=="ext_health")
async def cb_ext_health(call:CallbackQuery):
    await set_user_mode(call.from_user.id, "health", "[]")
    await call.message.answer("🩺 **Режим здоровья активирован**\n\nЯ помогу с рекомендациями по ЗОЖ, сну, питанию и отдыху.\n⚠️ Я не врач и не назначаю препараты. Опиши, что беспокоит или что хочешь улучшить?")
    await call.answer()

@dp.callback_query(F.data=="ext_psycho")
async def cb_ext_psycho(call:CallbackQuery):
    await set_user_mode(call.from_user.id, "psycho", "", "[]")
    await call.message.answer(
        "🧠 **Режим психоанализа активирован**\n\n"
        "Расскажи, что у тебя на душе? Я здесь, чтобы выслушать и помочь разобраться. 🤍\n"
        "⚠️ Я не заменяю профессионального психолога. При острых состояниях обращайся к специалисту."
    )
    await call.answer()

@dp.callback_query(F.data=="ext_cinema")
async def cb_ext_cinema(call:CallbackQuery):
    profile = await get_profile(call.from_user.id)
    city = profile.get("city") if profile and profile.get("city") else CITY_DEFAULT
    movies = await get_cinema_data(city)
    if movies:
        text = "🎬 В прокате:\n" + "\n".join([f"• {m['title']} ⭐{m['rating']:.1f}" for m in movies])
        await call.message.answer(text, reply_markup=external_link_keyboard(get_cinema_link(city), f"Афиша: {city}"))
    else: await call.message.answer(f"🎬 {city}:", reply_markup=external_link_keyboard(get_cinema_link(city), "Афиша"))
    await call.answer()

@dp.callback_query(F.data=="ext_news")
async def cb_ext_news(call:CallbackQuery):
    news = await get_news_data()
    if news: await call.message.answer("📰 " + news[0]['title'], reply_markup=external_link_keyboard(get_news_link(), "Все"))
    else: await call.message.answer("📰 Новости:", reply_markup=external_link_keyboard(get_news_link(), "Яндекс"))
    await call.answer()

# ======================
#  🔥 🔥  ОСНОВНОЙ ЧАТ (v4.6) 🔥 🔥 
# ======================
@dp.message()
async def chat(msg:Message, state:FSMContext):
    if not msg.text or await state.get_state(): return
    
    uid = msg.from_user.id
    text = fix_layout(msg.text.strip())
    text_lower = text.lower()
    
    # 🔥 ПРЯМАЯ ПРОВЕРКА НА МЕНЮ (работает в ЛЮБОМ режиме!)
    if "меню" in text_lower or text_lower == "menu":
        await msg.answer("📋 **Меню**:", reply_markup=main_menu_keyboard())
        return
    
    async with db_pool.acquire() as conn: 
        await conn.execute("INSERT INTO users(user_id,name) VALUES ($1,$2) ON CONFLICT DO NOTHING", uid, msg.from_user.first_name)
    await update_last_activity(uid)
    
    profile = await get_profile(uid)
    if not profile or not profile["name"]:
        name,age,gender,city = extract_profile(text)
        if name or city:
            await save_profile(uid, name=name, city=city)
            profile = await get_profile(uid)
            await msg.answer(f"Запомнил: {name or city}")
            return
    
    current_mode = profile.get("mode", "general")
    
    # 🔥 РЕЖИМ ЗДОРОВЬЯ
    if current_mode == "health":
        if any(k in text_lower for k in HEALTH_EXIT_TRIGGERS) or should_reset_context(text) or is_topic_change(text, "health"):
            await set_user_mode(uid, "general")
            await save_health_context(uid, [])
            await msg.answer("✅ Режим здоровья завершён. Чем ещё могу помочь?")
            return
        h_ctx = await get_health_context(uid)
        h_ctx.append({"role": "user", "content": text})
        await save_health_context(uid, h_ctx)
        answer = await call_health_ai(text, profile, h_ctx)
        h_ctx.append({"role": "assistant", "content": answer})
        await save_health_context(uid, h_ctx)
        await msg.answer(answer)
        return
    
    # 🔥 РЕЖИМ ПСИХОАНАЛИЗА
    if current_mode == "psycho":
        if any(k in text_lower for k in PSYCHO_EXIT_TRIGGERS) or should_reset_context(text) or is_topic_change(text, "psycho"):
            await set_user_mode(uid, "general")
            await save_psycho_context(uid, [])
            await msg.answer("✅ Сеанс завершён. Я всегда на связи. 🤍")
            return
        p_ctx = await get_psycho_context(uid)
        p_ctx.append({"role": "user", "content": text})
        await save_psycho_context(uid, p_ctx)
        answer = await call_psycho_ai(text, profile, p_ctx, await get_mood(uid))
        p_ctx.append({"role": "assistant", "content": answer})
        await save_psycho_context(uid, p_ctx)
        await msg.answer(answer)
        return

    # 🔥 ОБЩИЙ РЕЖИМ
    if should_reset_context(text) or any(kw in text_lower for kw in FRUSTRATION_KEYWORDS):
        await clear_user_context(uid)
    
    memory = await get_memory(uid)
    mood = await get_mood(uid)
    await save_memory(uid, "user", text)
    await update_emotion(uid, text)
    
    cmd = parse_ru_command(text)
    if cmd:
        if cmd == "reset_context":
            await clear_user_context(uid)
            await msg.answer("✅ Контекст очищен! Начинаем с чистого листа. 😊")
            return
        elif cmd == "show_menu": await msg.answer("📋 **Меню**:", reply_markup=main_menu_keyboard()); return
        elif cmd == "list_tasks": await cmd_tasks(msg); return
        elif cmd == "notes_list": await cmd_notes(msg); return
        elif cmd == "calendar_list": await cmd_calendar(msg); return
        elif cmd == "habits_list": await cb_habits(msg); return
        elif cmd == "dashboard_show": await cmd_dashboard(msg); return
        elif cmd == "ext_weather":
            city = profile.get("city") if profile and profile.get("city") else CITY_DEFAULT
            weather = await get_weather_data(city)
            if weather: await msg.answer(f"🌤 {city}: {weather['temp']}°, {weather['description']}")
            else: await msg.answer(f"🌤 {city}:", reply_markup=external_link_keyboard(get_weather_link(city), "Яндекс.Погода"))
            return
        elif cmd == "ext_currency":
            rates = await get_currency_data()
            if rates: await msg.answer(f"💱 1$ = {rates.get('USD',0):.2f}₽ | 1€ = {rates.get('EUR',0):.2f}₽")
            else: await msg.answer("💱 Курс:", reply_markup=external_link_keyboard(get_currency_link(), "ЦБ"))
            return
        elif cmd == "ext_health":
            await set_user_mode(uid, "health", "[]")
            await msg.answer("🩺 **Режим здоровья активирован**\n\nЯ помогу с рекомендациями по ЗОЖ, сну, питанию и отдыху.\n⚠️ Я не врач и не назначаю препараты. Опиши, что беспокоит или что хочешь улучшить?")
            return
        elif cmd == "ext_psycho":
            await set_user_mode(uid, "psycho", "", "[]")
            await msg.answer("🧠 **Режим психоанализа активирован**\n\nРасскажи, что у тебя на душе? Я здесь, чтобы выслушать и помочь разобраться. 🤍\n⚠️ Я не заменяю профессионального психолога. При острых состояниях обращайся к специалисту.")
            return
        elif cmd == "ext_cinema":
            city = profile.get("city") if profile and profile.get("city") else CITY_DEFAULT
            movies = await get_cinema_data(city)
            if movies:
                text_msg = "🎬 В прокате:\n" + "\n".join([f"• {m['title']} ⭐{m['rating']:.1f}" for m in movies])
                await msg.answer(text_msg, reply_markup=external_link_keyboard(get_cinema_link(city), f"Афиша: {city}"))
            else: await msg.answer(f"🎬 {city}:", reply_markup=external_link_keyboard(get_cinema_link(city), "Афиша"))
            return
        elif cmd == "ext_news":
            news = await get_news_data()
            if news: await msg.answer("📰 " + news[0]['title'], reply_markup=external_link_keyboard(get_news_link(), "Все"))
            else: await msg.answer("📰 Новости:", reply_markup=external_link_keyboard(get_news_link(), "Яндекс"))
            return
        elif cmd == "profile_show": await cmd_profile(msg, state); return
        elif cmd == "help_show": await cmd_help(msg); return
    
    # Создание задач/заметок текстом
    if any(kw in text_lower for kw in ["создай задачу", "добавь задачу", "новая задача", "задача:"]):
        tt = text
        for kw in ["создай задачу", "добавь задачу", "новая задача", "задача:"]:
            if kw in tt: tt = tt.split(kw)[-1].strip(); break
        if tt and len(tt) > 3:
            tid = await create_task(uid, title=tt, category="general", priority="medium")
            await msg.answer(f"✅ Задача #{tid} создана: {tt}\n\nИспользуй /tasks чтобы посмотреть все задачи", reply_markup=task_actions_keyboard(tid))
            return
    
    if any(kw in text_lower for kw in ["запиши заметку", "создай заметку", "добавь заметку", "заметка:", "запиши"]):
        nc = text
        for kw in ["запиши заметку", "создай заметку", "добавь заметку", "заметка:", "запиши"]:
            if kw in nc: nc = nc.split(kw)[-1].strip(); break
        if nc and len(nc) > 3:
            nid = await create_note(uid, content=nc, category="general")
            await msg.answer(f"✅ Заметка #{nid} сохранена!\n\nИспользуй /notes чтобы посмотреть все заметки", reply_markup=note_actions_keyboard(nid))
            return
    
    if any(kw in text_lower for kw in ["добавь событие", "создай событие", "встреча:", "план:"]):
        await msg.answer("📅 Для создания события используй команду /event — так будет надёжнее!")
        return
    
    answer = await call_openai_chat(text, profile, mood, memory)
    await msg.answer(answer)

# ======================
#  🔥 ПЛАНИРОВЩИК
# ======================
async def morning_quote():
    async with db_pool.acquire() as conn: users = await conn.fetch("SELECT user_id FROM users")
    for u in users:
        try: await bot.send_message(u["user_id"], f"☀️ **Доброе утро!**\n\n{await get_next_quote_for_user(u['user_id'])}")
        except: pass
async def afternoon_fact():
    async with db_pool.acquire() as conn: users = await conn.fetch("SELECT user_id FROM users")
    for u in users:
        try: await bot.send_message(u["user_id"], f"🧠 **Факт дня**:\n\n{await get_next_fact_for_user(u['user_id'])}")
        except: pass
async def morning_ping():
    async with db_pool.acquire() as conn: users = await conn.fetch("SELECT user_id FROM users")
    for u in users:
        try: 
            profile = await get_profile(u["user_id"])
            data = await get_dashboard_data(u["user_id"], profile)
            await bot.send_message(u["user_id"], f"☀️ **План на день**\n\n" + format_dashboard(data), parse_mode="Markdown")
        except: pass
async def evening_report():
    async with db_pool.acquire() as conn: users = await conn.fetch("SELECT user_id FROM users")
    for u in users:
        try:
            comp = await conn.fetchval("SELECT COUNT(*) FROM tasks WHERE user_id=$1 AND status='completed' AND completed_at::date = CURRENT_DATE", u["user_id"])
            pend = await conn.fetchval("SELECT COUNT(*) FROM tasks WHERE user_id=$1 AND status='pending' AND due_date::date = CURRENT_DATE", u["user_id"])
            await bot.send_message(u["user_id"], f"🌙 **Итоги дня**\n✅ Выполнено: {comp}\n⏳ На завтра: {pend}\n\nОтличная работа! 💪")
        except: pass
async def habit_check():
    async with db_pool.acquire() as conn: habits = await conn.fetch("SELECT id,user_id,name,last_done,frequency FROM habits")
    now = now_moscow().date()
    for h in habits:
        if h["frequency"]=="daily" and h["last_done"] and h["last_done"] < now - timedelta(days=1):
            try: await bot.send_message(h["user_id"], f"🔁 '{h['name']}' — не забудь сегодня!")
            except: pass
async def task_reminder_check():
    async with db_pool.acquire() as conn: tasks = await conn.fetch("SELECT user_id,title,due_date FROM tasks WHERE status='pending' AND due_date IS NOT NULL AND due_date <= NOW() + INTERVAL '1 hour' AND due_date > NOW()")
    for t in tasks:
        try: await bot.send_message(t["user_id"], f"⏰ Скоро: {t['title']} ({t['due_date'].astimezone(MOSCOW_TZ).strftime('%H:%M')})")
        except: pass
async def calendar_reminder_check():
    async with db_pool.acquire() as conn: events = await conn.fetch("SELECT user_id, title, event_date FROM calendar_events WHERE event_date <= NOW() + INTERVAL '1 hour' AND event_date > NOW() - INTERVAL '1 hour'")
    for e in events:
        try: await bot.send_message(e["user_id"], f"📅 Скоро: {e['title']} ({e['event_date'].astimezone(MOSCOW_TZ).strftime('%H:%M')})")
        except: pass

# ======================
#  🔥 HEALTH CHECK / ЗАПУСК
# ======================
async def health_handler(request): return web.json_response({"status":"ok","bot":"AssistEmpat v4.6"}, headers={"Content-Type":"application/json"})
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

async def main():
    logging.info(f"🚀 Starting AssistEmpat v4.6 (port={HEALTH_PORT}, TZ=Moscow)")
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    def handle_signal(): logging.info("🛑 Signal received"); stop_event.set()
    for sig in (signal.SIGTERM, signal.SIGINT): loop.add_signal_handler(sig, handle_signal)
    try: await init_db(); logging.info("✅ DB initialized")
    except Exception as e: logging.error(f"❌ DB init failed: {e}"); return
    health_runner = None
    try: health_runner = await start_health_server(); await asyncio.sleep(1.0); logging.info("✅ Health server ready")
    except Exception as e: logging.warning(f"⚠️ Health server failed: {e}")
    if stop_event.is_set(): await cleanup(health_runner); return
    scheduler.start()
    scheduler.add_job(morning_quote, "cron", hour=8, minute=0)
    scheduler.add_job(afternoon_fact, "cron", hour=13, minute=0)
    scheduler.add_job(morning_ping, "cron", hour=9, minute=0)
    scheduler.add_job(evening_report, "cron", hour=21, minute=0)
    scheduler.add_job(habit_check, "interval", hours=6)
    scheduler.add_job(task_reminder_check, "interval", minutes=30)
    scheduler.add_job(calendar_reminder_check, "interval", minutes=30)
    logging.info("✅ Scheduler started (Moscow TZ)")
    await bot.delete_webhook(drop_pending_updates=True)
    if stop_event.is_set(): await cleanup(health_runner); return
    logging.info("✅ AssistEmpat v4.6 ready — STARTING POLLING")
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
    try: asyncio.run(main())
    except KeyboardInterrupt: logging.info("👋 Stopped by user")
    except Exception as e: logging.error(f"💥 Fatal error: {e}")