# =========================================================
#  ASSISTEMPAT BOT v4.9-FINAL
#  1. 🔐 Безопасные семьи (FSM + Инвайт-коды)
#  2. 🎭 Адаптивные ответы (Возраст/Пол/Тон)
#  3. 🧠 Связность режимов (Психоанализ → Задачи → Привычки)
#  4. 📊 Дашборд 3.0 (Личный/Семейный вид)
#  5. ✨ UI/UX Улучшения (Подтверждение сброса, Умное меню, NLP)
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
import string
from datetime import datetime, timedelta, timezone, date
from collections import defaultdict

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
def now_moscow() -> datetime:
    return datetime.now(MOSCOW_TZ)

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
        await conn.execute(
            "INSERT INTO profile(user_id, last_quote_index) VALUES ($1, $2) ON CONFLICT(user_id) DO UPDATE SET last_quote_index = $2",
            uid, nxt
        )
        return q

async def get_next_fact_for_user(uid: int) -> str:
    async with db_pool.acquire() as conn:
        row = await conn.fetchval("SELECT last_fact_index FROM profile WHERE user_id=$1", uid)
        last = row if row is not None else -1
        nxt = (last + 1) % len(FACTS_RU)
        f = FACTS_RU[nxt]
        await conn.execute(
            "INSERT INTO profile(user_id, last_fact_index) VALUES ($1, $2) ON CONFLICT(user_id) DO UPDATE SET last_fact_index = $2",
            uid, nxt
        )
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
#  🔑 АДМИНИСТРАТОР
# ======================
ADMIN_USER_ID = 1425899739  # Твой Telegram ID

def is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь админом"""
    return user_id == ADMIN_USER_ID
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
    safe = ['меню', 'инлайн', 'задача', 'привычк', 'напомн', 'погод', 'кино', 'новост', 'курс', 'профиль', 'помощь', 'статистик', 'заметк', 'календар', 'дашборд', 'сброс', 'reset', 'здоровье', 'психо', 'дерево', 'семья', 'семейный', 'инвайт', 'пригласить']
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
RESET_KEYWORDS = ["привет", "здравствуй", "отбой", "стоп", "новое", "другое", "меню", "пока"]
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
    t = text.lower()
    util_keywords = ["задача", "заметк", "календар", "погод", "курс", "кино", "новост", "дашборд", "меню", "дерево", "статистик", "семья", "профиль", "инвайт", "пригласить"]
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
        # Основные таблицы
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users(user_id BIGINT PRIMARY KEY, name TEXT, age INTEGER, gender TEXT, created_at TIMESTAMP DEFAULT NOW());
        CREATE TABLE IF NOT EXISTS memory(id SERIAL PRIMARY KEY, user_id BIGINT, role TEXT, content TEXT, created_at TIMESTAMP DEFAULT NOW());
        CREATE TABLE IF NOT EXISTS reminders(id SERIAL PRIMARY KEY, user_id BIGINT, text TEXT, remind_at TIMESTAMP);
        CREATE TABLE IF NOT EXISTS habits(id SERIAL PRIMARY KEY, user_id BIGINT, name TEXT, streak INTEGER DEFAULT 0, last_done DATE, frequency TEXT DEFAULT 'daily', target_per_week INTEGER DEFAULT 7, schedule_json JSONB DEFAULT '{}', created_at TIMESTAMP DEFAULT NOW());
        CREATE TABLE IF NOT EXISTS habit_logs(id SERIAL PRIMARY KEY, habit_id INTEGER REFERENCES habits(id) ON DELETE CASCADE, completed_at TIMESTAMP DEFAULT NOW(), note TEXT);
        CREATE TABLE IF NOT EXISTS emotions(id SERIAL PRIMARY KEY, user_id BIGINT, mood TEXT, created_at TIMESTAMP DEFAULT NOW());
        CREATE TABLE IF NOT EXISTS last_activity(user_id BIGINT PRIMARY KEY, last_time TIMESTAMP DEFAULT NOW());
        CREATE TABLE IF NOT EXISTS message_tags(id SERIAL PRIMARY KEY, user_id BIGINT, message_id BIGINT, tags TEXT[], topic TEXT, created_at TIMESTAMP DEFAULT NOW());
        CREATE TABLE IF NOT EXISTS response_log(id SERIAL PRIMARY KEY, user_id BIGINT, content_hash TEXT, created_at TIMESTAMP DEFAULT NOW());
        CREATE TABLE IF NOT EXISTS notes(id SERIAL PRIMARY KEY, user_id BIGINT, content TEXT, created_at TIMESTAMP DEFAULT NOW(), tags TEXT[], category TEXT DEFAULT 'general', parent_id INTEGER REFERENCES notes(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS calendar_events(id SERIAL PRIMARY KEY, user_id BIGINT, title TEXT, description TEXT, event_date TIMESTAMP, reminder_before INTERVAL, recurrence TEXT, category TEXT DEFAULT 'general', created_at TIMESTAMP DEFAULT NOW(), visibility TEXT DEFAULT 'private');
        """)
        # Задачи
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks(
            id SERIAL PRIMARY KEY, user_id BIGINT, title TEXT NOT NULL, description TEXT, status TEXT DEFAULT 'pending',
            priority TEXT DEFAULT 'medium', due_date TIMESTAMP, category TEXT DEFAULT 'general', tags TEXT[],
            parent_id INTEGER REFERENCES tasks(id) ON DELETE CASCADE, recurrence TEXT, attachments TEXT[],
            linked_note_ids INTEGER[] DEFAULT '{}', created_at TIMESTAMP DEFAULT NOW(), completed_at TIMESTAMP, checklist JSONB DEFAULT '[]',
            visibility TEXT DEFAULT 'private', assigned_to BIGINT REFERENCES users(user_id)
        );""")
        # Профиль
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS profile(
            user_id BIGINT PRIMARY KEY, name TEXT, age INTEGER, gender TEXT, city TEXT DEFAULT 'Москва',
            last_quote_index INTEGER DEFAULT 0, last_fact_index INTEGER DEFAULT 0, mode TEXT DEFAULT 'general',
            health_context TEXT DEFAULT '', psycho_context TEXT DEFAULT '', preferred_tone TEXT DEFAULT 'balanced',
            last_activity_patterns JSONB DEFAULT '{}', age_group TEXT DEFAULT 'adult', language TEXT DEFAULT 'ru',
            created_at TIMESTAMP DEFAULT NOW(), updated_at TIMESTAMP DEFAULT NOW()
        );""")
        # Долгосрочная память
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_insights(id SERIAL PRIMARY KEY, user_id BIGINT, key TEXT, value JSONB, updated_at TIMESTAMP DEFAULT NOW(), UNIQUE(user_id, key));
        """)
        # Семейные группы
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS family_groups(id SERIAL PRIMARY KEY, name TEXT, created_by BIGINT REFERENCES users(user_id), created_at TIMESTAMP DEFAULT NOW());
        """)
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS family_members(user_id BIGINT PRIMARY KEY REFERENCES users(user_id), group_id INTEGER REFERENCES family_groups(id) ON DELETE CASCADE, role TEXT DEFAULT 'member', nickname TEXT, joined_at TIMESTAMP DEFAULT NOW());
        """)
        # Инвайт-коды
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS family_invites(code TEXT PRIMARY KEY, group_id INTEGER REFERENCES family_groups(id) ON DELETE CASCADE, created_by BIGINT REFERENCES users(user_id), created_at TIMESTAMP DEFAULT NOW(), expires_at TIMESTAMP DEFAULT NOW() + INTERVAL '24 hours', used BOOLEAN DEFAULT FALSE);
        """)
        
        # Миграции
        migrations = [
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS name TEXT", "ALTER TABLE users ADD COLUMN IF NOT EXISTS age INTEGER",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS gender TEXT", "ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW()",
            "ALTER TABLE memory ADD COLUMN IF NOT EXISTS user_id BIGINT", "ALTER TABLE memory ADD COLUMN IF NOT EXISTS role TEXT",
            "ALTER TABLE memory ADD COLUMN IF NOT EXISTS content TEXT", "ALTER TABLE memory ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW()",
            "ALTER TABLE reminders ADD COLUMN IF NOT EXISTS user_id BIGINT", "ALTER TABLE reminders ADD COLUMN IF NOT EXISTS text TEXT",
            "ALTER TABLE reminders ADD COLUMN IF NOT EXISTS remind_at TIMESTAMP",
            "ALTER TABLE habits ADD COLUMN IF NOT EXISTS user_id BIGINT", "ALTER TABLE habits ADD COLUMN IF NOT EXISTS name TEXT",
            "ALTER TABLE habits ADD COLUMN IF NOT EXISTS streak INTEGER DEFAULT 0", "ALTER TABLE habits ADD COLUMN IF NOT EXISTS last_done DATE",
            "ALTER TABLE habits ADD COLUMN IF NOT EXISTS frequency TEXT DEFAULT 'daily'", "ALTER TABLE habits ADD COLUMN IF NOT EXISTS target_per_week INTEGER DEFAULT 7",
            "ALTER TABLE habits ADD COLUMN IF NOT EXISTS schedule_json JSONB DEFAULT '{}'", "ALTER TABLE habits ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW()",
            "ALTER TABLE habit_logs ADD COLUMN IF NOT EXISTS habit_id INTEGER", "ALTER TABLE habit_logs ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP DEFAULT NOW()",
            "ALTER TABLE habit_logs ADD COLUMN IF NOT EXISTS note TEXT",
            "ALTER TABLE emotions ADD COLUMN IF NOT EXISTS user_id BIGINT", "ALTER TABLE emotions ADD COLUMN IF NOT EXISTS mood TEXT",
            "ALTER TABLE emotions ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW()",
            "ALTER TABLE last_activity ADD COLUMN IF NOT EXISTS user_id BIGINT", "ALTER TABLE last_activity ADD COLUMN IF NOT EXISTS last_time TIMESTAMP DEFAULT NOW()",
            "ALTER TABLE message_tags ADD COLUMN IF NOT EXISTS user_id BIGINT", "ALTER TABLE message_tags ADD COLUMN IF NOT EXISTS message_id BIGINT",
            "ALTER TABLE message_tags ADD COLUMN IF NOT EXISTS tags TEXT[]", "ALTER TABLE message_tags ADD COLUMN IF NOT EXISTS topic TEXT",
            "ALTER TABLE message_tags ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW()",
            "ALTER TABLE response_log ADD COLUMN IF NOT EXISTS user_id BIGINT", "ALTER TABLE response_log ADD COLUMN IF NOT EXISTS content_hash TEXT",
            "ALTER TABLE response_log ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW()",
            "ALTER TABLE notes ADD COLUMN IF NOT EXISTS user_id BIGINT", "ALTER TABLE notes ADD COLUMN IF NOT EXISTS content TEXT",
            "ALTER TABLE notes ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW()", "ALTER TABLE notes ADD COLUMN IF NOT EXISTS tags TEXT[]",
            "ALTER TABLE notes ADD COLUMN IF NOT EXISTS category TEXT DEFAULT 'general'", "ALTER TABLE notes ADD COLUMN IF NOT EXISTS parent_id INTEGER",
            "ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS user_id BIGINT", "ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS title TEXT",
            "ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS description TEXT", "ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS event_date TIMESTAMP",
            "ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS reminder_before INTERVAL", "ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS recurrence TEXT",
            "ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS category TEXT DEFAULT 'general'", "ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW()",
            "ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS visibility TEXT DEFAULT 'private'",
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS user_id BIGINT", "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS title TEXT NOT NULL",
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS description TEXT", "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'pending'",
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS priority TEXT DEFAULT 'medium'", "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS due_date TIMESTAMP",
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS category TEXT DEFAULT 'general'", "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS tags TEXT[]",
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS parent_id INTEGER", "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS recurrence TEXT",
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS attachments TEXT[]", "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS linked_note_ids INTEGER[] DEFAULT '{}'",
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW()", "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP",
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS checklist JSONB DEFAULT '[]'", "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS visibility TEXT DEFAULT 'private'",
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS assigned_to BIGINT",
            "ALTER TABLE profile ADD COLUMN IF NOT EXISTS name TEXT", "ALTER TABLE profile ADD COLUMN IF NOT EXISTS age INTEGER",
            "ALTER TABLE profile ADD COLUMN IF NOT EXISTS gender TEXT", "ALTER TABLE profile ADD COLUMN IF NOT EXISTS city TEXT DEFAULT 'Москва'",
            "ALTER TABLE profile ADD COLUMN IF NOT EXISTS last_quote_index INTEGER DEFAULT 0", "ALTER TABLE profile ADD COLUMN IF NOT EXISTS last_fact_index INTEGER DEFAULT 0",
            "ALTER TABLE profile ADD COLUMN IF NOT EXISTS mode TEXT DEFAULT 'general'", "ALTER TABLE profile ADD COLUMN IF NOT EXISTS health_context TEXT DEFAULT ''",
            "ALTER TABLE profile ADD COLUMN IF NOT EXISTS psycho_context TEXT DEFAULT ''", "ALTER TABLE profile ADD COLUMN IF NOT EXISTS preferred_tone TEXT DEFAULT 'balanced'",
            "ALTER TABLE profile ADD COLUMN IF NOT EXISTS last_activity_patterns JSONB DEFAULT '{}'", "ALTER TABLE profile ADD COLUMN IF NOT EXISTS age_group TEXT DEFAULT 'adult'",
            "ALTER TABLE profile ADD COLUMN IF NOT EXISTS language TEXT DEFAULT 'ru'", "ALTER TABLE profile ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW()",
            "ALTER TABLE profile ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW()",
            "ALTER TABLE user_insights ADD COLUMN IF NOT EXISTS user_id BIGINT", "ALTER TABLE user_insights ADD COLUMN IF NOT EXISTS key TEXT",
            "ALTER TABLE user_insights ADD COLUMN IF NOT EXISTS value JSONB", "ALTER TABLE user_insights ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW()",
            "ALTER TABLE family_groups ADD COLUMN IF NOT EXISTS name TEXT", "ALTER TABLE family_groups ADD COLUMN IF NOT EXISTS created_by BIGINT",
            "ALTER TABLE family_groups ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW()",
            "ALTER TABLE family_members ADD COLUMN IF NOT EXISTS user_id BIGINT", "ALTER TABLE family_members ADD COLUMN IF NOT EXISTS group_id INTEGER",
            "ALTER TABLE family_members ADD COLUMN IF NOT EXISTS role TEXT DEFAULT 'member'", "ALTER TABLE family_members ADD COLUMN IF NOT EXISTS nickname TEXT",
            "ALTER TABLE family_members ADD COLUMN IF NOT EXISTS joined_at TIMESTAMP DEFAULT NOW()",
            "ALTER TABLE family_invites ADD COLUMN IF NOT EXISTS code TEXT", "ALTER TABLE family_invites ADD COLUMN IF NOT EXISTS group_id INTEGER",
            "ALTER TABLE family_invites ADD COLUMN IF NOT EXISTS created_by BIGINT", "ALTER TABLE family_invites ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW()",
            "ALTER TABLE family_invites ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP", "ALTER TABLE family_invites ADD COLUMN IF NOT EXISTS used BOOLEAN DEFAULT FALSE",
        ]
        for sql in migrations:
            try: await conn.execute(sql)
            except Exception as e: logging.warning(f"⚠️ Migration skipped: {sql[:80]}... — {e}")
            
        # Индексы
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_memory_user ON memory(user_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_habits_user ON habits(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_habit_logs_habit ON habit_logs(habit_id, completed_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_reminders_time ON reminders(remind_at)",
            "CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id, status)",
            "CREATE INDEX IF NOT EXISTS idx_tasks_category ON tasks(user_id, category)",
            "CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(user_id, parent_id)",
            "CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks(user_id, due_date) WHERE status='pending'",
            "CREATE INDEX IF NOT EXISTS idx_tasks_linked ON tasks(user_id) WHERE array_length(linked_note_ids, 1) > 0",
            "CREATE INDEX IF NOT EXISTS idx_tasks_assigned ON tasks(assigned_to) WHERE assigned_to IS NOT NULL",
            "CREATE INDEX IF NOT EXISTS idx_tasks_visibility ON tasks(visibility)",
            "CREATE INDEX IF NOT EXISTS idx_response_log ON response_log(user_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_notes_user ON notes(user_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_notes_parent ON notes(user_id, parent_id)",
            "CREATE INDEX IF NOT EXISTS idx_notes_category ON notes(user_id, category)",
            "CREATE INDEX IF NOT EXISTS idx_calendar_user ON calendar_events(user_id, event_date)",
            "CREATE INDEX IF NOT EXISTS idx_calendar_category ON calendar_events(user_id, category)",
            "CREATE INDEX IF NOT EXISTS idx_calendar_visibility ON calendar_events(visibility)",
            "CREATE INDEX IF NOT EXISTS idx_insights_user ON user_insights(user_id, key)",
            "CREATE INDEX IF NOT EXISTS idx_family_user ON family_members(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_family_group ON family_members(group_id)",
            "CREATE INDEX IF NOT EXISTS idx_invites_code ON family_invites(code) WHERE used=FALSE AND expires_at > NOW()",
        ]
        for sql in indexes:
            try: await conn.execute(sql)
            except Exception as e: logging.warning(f"⚠️ Index skipped: {sql[:80]}... — {e}")
        logging.info("✅ PostgreSQL initialized + v4.9 features (family-safe + connected)")

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
#  🔥 ДОЛГОСРОЧНАЯ ПАМЯТЬ (USER INSIGHTS)
# ======================
async def save_user_insight(uid: int, key: str, value):
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO user_insights(user_id, key, value) VALUES ($1, $2, $3) ON CONFLICT(user_id, key) DO UPDATE SET value = $3, updated_at = NOW()", uid, key, json.dumps(value) if not isinstance(value, str) else value)

async def get_user_insight(uid: int, key: str):
    async with db_pool.acquire() as conn:
        raw = await conn.fetchval("SELECT value FROM user_insights WHERE user_id=$1 AND key=$2", uid, key)
        if raw is None: return None
        try: return json.loads(raw)
        except: return raw

async def get_user_profile_context(uid: int) -> dict:
    profile = await get_profile(uid)
    if not profile: return {}
    insights = {}
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT key, value FROM user_insights WHERE user_id=$1", uid)
        for r in rows:
            try: insights[r["key"]] = json.loads(r["value"])
            except: insights[r["key"]] = r["value"]
    age = profile.get("age")
    if age and not profile.get("age_group"):
        if age < 12: age_group = "child"
        elif age < 18: age_group = "teen"
        elif age < 60: age_group = "adult"
        else: age_group = "senior"
    else: age_group = profile.get("age_group", "adult")
    return {
        "user_id": uid, "name": profile.get("name"), "age": age, "age_group": age_group,
        "gender": profile.get("gender"), "city": profile.get("city", CITY_DEFAULT),
        "preferred_tone": profile.get("preferred_tone", "balanced"),
        "language": profile.get("language", "ru"), "insights": insights
    }

# ======================
#  🔥 СЕМЕЙНЫЕ ГРУППЫ (БЕЗОПАСНАЯ ЛОГИКА)
# ======================
def generate_invite_code(length=6) -> str:
    return ''.join(random.choices(string.digits, k=length))

async def create_family_group(name: str, created_by: int) -> int:
    async with db_pool.acquire() as conn:
        group_id = await conn.fetchval("INSERT INTO family_groups(name, created_by) VALUES ($1, $2) RETURNING id", name, created_by)
        await conn.execute("INSERT INTO family_members(user_id, group_id, role, nickname) VALUES ($1, $2, 'admin', 'Я')", created_by, group_id)
        return group_id

async def create_family_invite(group_id: int, created_by: int) -> str:
    code = generate_invite_code()
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO family_invites(code, group_id, created_by) VALUES ($1, $2, $3)", code, group_id, created_by)
    return code

async def join_family_by_code(uid: int, code: str) -> bool:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT group_id, expires_at, used FROM family_invites WHERE code=$1", code)
        if not row or row["used"] or row["expires_at"] < now_moscow(): return False
        group_id = row["group_id"]
        existing = await conn.fetchval("SELECT group_id FROM family_members WHERE user_id=$1", uid)
        if existing: return False
        await conn.execute("INSERT INTO family_members(user_id, group_id, role, nickname) VALUES ($1, $2, 'member', $3)", uid, group_id, f"User{uid}")
        await conn.execute("UPDATE family_invites SET used=TRUE WHERE code=$1", code)
        return True

async def get_user_family(uid: int):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("""
        SELECT fm.group_id, fm.role, fm.nickname, fg.name as group_name
        FROM family_members fm
        JOIN family_groups fg ON fm.group_id = fg.id
        WHERE fm.user_id = $1
        """, uid)
        return dict(row) if row else None

async def get_family_members(group_id: int):
    async with db_pool.acquire() as conn:
        return await conn.fetch("""
        SELECT u.user_id, u.name, u.age, u.gender, fm.role, fm.nickname
        FROM family_members fm
        JOIN users u ON fm.user_id = u.user_id
        WHERE fm.group_id = $1
        """, group_id)

async def get_secure_tasks(uid: int, status="pending", with_linked_notes=False):
    async with db_pool.acquire() as conn:
        family = await get_user_family(uid)
        if family:
            query = """
            SELECT t.*, u.name as assigned_name
            FROM tasks t
            LEFT JOIN users u ON t.assigned_to = u.user_id
            WHERE t.status = $1
            AND (
                t.user_id = $2
                OR (
                    t.visibility = 'family'
                    AND t.user_id IN (
                        SELECT user_id FROM family_members WHERE group_id = $3
                    )
                )
            )
            ORDER BY t.due_date ASC NULLS LAST, t.created_at DESC
            LIMIT 20
            """
            params = [status, uid, family["group_id"]]
        else:
            query = """
            SELECT t.*, u.name as assigned_name
            FROM tasks t
            LEFT JOIN users u ON t.assigned_to = u.user_id
            WHERE t.user_id = $1 AND t.status = $2
            ORDER BY t.due_date ASC NULLS LAST, t.created_at DESC
            LIMIT 20
            """
            params = [uid, status]
        tasks = await conn.fetch(query, *params)
        if with_linked_notes and tasks:
            note_ids = [nid for t in tasks for nid in (t["linked_note_ids"] or [])]
            if note_ids:
                notes = await conn.fetch("SELECT id, content, category FROM notes WHERE id = ANY($1)", note_ids)
                notes_map = {n["id"]: n for n in notes}
                for t in tasks:
                    t["linked_notes"] = [notes_map[nid] for nid in (t["linked_note_ids"] or []) if nid in notes_map]
        return tasks

async def get_secure_calendar(uid: int, from_date=None, to_date=None):
    async with db_pool.acquire() as conn:
        family = await get_user_family(uid)
        if family:
            query = """
            SELECT * FROM calendar_events
            WHERE (user_id = $1 AND visibility = 'private')
            OR (
                visibility = 'family'
                AND user_id IN (
                    SELECT user_id FROM family_members WHERE group_id = $2
                )
            )
            """
            params = [uid, family["group_id"]]
        else:
            query = "SELECT * FROM calendar_events WHERE user_id = $1 AND visibility = 'private'"
            params = [uid]
        if from_date:
            query += " AND event_date >= $3"
            params.append(from_date)
        if to_date:
            query += " AND event_date <= $4" if from_date else " AND event_date <= $3"
            params.append(to_date if from_date else to_date)
        query += " ORDER BY event_date ASC LIMIT 20"
        return await conn.fetch(query, *params)

# ======================
#  🔥 АДАПТИВНЫЙ ТОН (AGE/GENDER/TONE AWARE)
# ======================
def get_age_appropriate_style(age_group: str, gender: str = None) -> dict:
    styles = {
        "child": {"max_tokens": 200, "temperature": 0.9, "emoji_level": "high", "complexity": "simple", "gamification": True, "prefix": "🌟 ", "suffix": " 💫", "tone_modifiers": ["будь как старший друг", "объясняй просто", "добавляй эмодзи", "хвали за усилия"]},
        "teen": {"max_tokens": 300, "temperature": 0.85, "emoji_level": "medium", "complexity": "moderate", "gamification": True, "prefix": "🔥 ", "suffix": " ✨", "tone_modifiers": ["будь на равных", "не поучай", "используй современный сленг умеренно", "поддерживай"]},
        "adult": {"max_tokens": 500, "temperature": 0.75, "emoji_level": "low", "complexity": "detailed", "gamification": False, "prefix": "", "suffix": "", "tone_modifiers": ["будь конкретным", "уважай время", "давай варианты, не навязывай"]},
        "senior": {"max_tokens": 400, "temperature": 0.7, "emoji_level": "low", "complexity": "clear", "gamification": False, "prefix": "🤝 ", "suffix": " 🙏", "tone_modifiers": ["будь терпеливым", "объясняй пошагово", "избегай сленга", "проявляй заботу"]}
    }
    base = styles.get(age_group, styles["adult"])
    if gender == "female" and age_group in ["teen", "adult"]: base["tone_modifiers"].append("будь эмпатичным, но не снисходительным")
    elif gender == "male" and age_group in ["teen", "adult"]: base["tone_modifiers"].append("будь прямым, но поддерживающим")
    return base

def format_response_for_user(text: str, user_ctx: dict) -> str:
    style = get_age_appropriate_style(user_ctx["age_group"], user_ctx["gender"])
    if style["emoji_level"] != "none": text = f"{style['prefix']}{text}{style['suffix']}"
    if user_ctx["age_group"] == "child" and style["gamification"]:
        if random.random() < 0.3: text += f"\n{random.choice(['Молодец! 🎉', 'Так держать! 🏆', 'Ты супер! ⭐', 'Горжусь тобой! 💪'])}"
    return text

# ======================
#  🔥 КОНТЕКСТНЫЙ БРИДЖ
# ======================
def suggest_mode_bridge(from_mode: str, to_mode: str, context: dict) -> str | None:
    bridges = {
        ("psycho", "tasks"): "Хочешь разбить это на конкретные шаги? Могу помочь создать задачу. 📋",
        ("psycho", "habits"): "Чтобы закрепить прогресс, можем добавить маленькую привычку. Что скажешь? 🔁",
        ("health", "habits"): "Это отлично сочетается с привычкой. Хочешь, добавим её в трекер? 🔁",
        ("health", "psycho"): "Если это вызывает тревогу, можем обсудить это в режиме психоанализа. 🧠",
        ("tasks", "calendar"): "Хочешь поставить напоминание в календарь? 📅",
        ("notes", "tasks"): "Эту идею можно превратить в задачу. Создать? 📋",
    }
    return bridges.get((from_mode, to_mode))

async def update_activity_pattern(uid: int, activity_type: str, timestamp: datetime):
    hour = timestamp.hour
    day_of_week = timestamp.weekday()
    patterns = await get_user_insight(uid, "activity_patterns") or {}
    hour_key = f"hour_{hour}"
    patterns[hour_key] = patterns.get(hour_key, 0) + 1
    day_key = f"day_{day_of_week}"
    patterns[day_key] = patterns.get(day_key, 0) + 1
    await save_user_insight(uid, "activity_patterns", patterns)

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
#  🔥 ЗАДАЧИ / ЗАМЕТКИ / КАЛЕНДАРЬ / ПРИВЫЧКИ / ПРОФИЛЬ
# ======================
async def create_task(uid, title, description=None, priority="medium", due_date=None, category="general", tags=None, parent_id=None, recurrence=None, attachments=None, checklist=None, linked_note_ids=None, visibility="private", assigned_to=None):
    async with db_pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO tasks(user_id, title, description, priority, due_date, category, tags, parent_id, recurrence, attachments, linked_note_ids, checklist, visibility, assigned_to) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14) RETURNING id",
            uid, title, description, priority, due_date, category, tags, parent_id, recurrence, attachments, linked_note_ids or [], json.dumps(checklist) if checklist else '[]', visibility, assigned_to
        )

async def complete_task(uid, task_id):
    async with db_pool.acquire() as conn: await conn.execute("UPDATE tasks SET status='completed', completed_at=NOW() WHERE id=$1 AND user_id=$2", task_id, uid)

async def delete_task(uid, task_id):
    async with db_pool.acquire() as conn: await conn.execute("DELETE FROM tasks WHERE id=$1 AND user_id=$2", task_id, uid)

async def get_task_stats(uid):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT COUNT(*) FILTER (WHERE status='pending') as pending, COUNT(*) FILTER (WHERE status='completed') as completed, COUNT(*) FILTER (WHERE category='work') as work, COUNT(*) FILTER (WHERE category='personal') as personal, COUNT(*) FILTER (WHERE category='shopping') as shopping FROM tasks WHERE user_id=$1", uid
        )

async def get_subtasks(uid, parent_id):
    async with db_pool.acquire() as conn:
        return await conn.fetch("SELECT id, title, status, priority FROM tasks WHERE user_id=$1 AND parent_id=$2 ORDER BY created_at", uid, parent_id)

NOTE_TEMPLATES = {
    "shopping": "🛒 Список покупок:\n-\n-\n- ", "ideas": "💡 Идеи:\n•\n•\n• ",
    "contacts": "📞 Контакты:\nИмя:\nТелефон:\nEmail: ", "meeting": "🤝 Встреча:\nДата:\nУчастники:\nПовестка: ", "todo": "✅ To-Do:\n[ ]\n[ ]\n[ ] "
}

async def create_note(uid, content, tags=None, category="general", parent_id=None):
    async with db_pool.acquire() as conn:
        return await conn.fetchval("INSERT INTO notes(user_id, content, tags, category, parent_id) VALUES ($1, $2, $3, $4, $5) RETURNING id", uid, content, tags, category, parent_id)

async def get_notes(uid, limit=10, search=None, category=None, parent_id=None, recursive=False):
    async with db_pool.acquire() as conn:
        query = "SELECT id, content, tags, category, parent_id, created_at FROM notes WHERE user_id=$1"
        params = [uid]
        if search: query += " AND (content ILIKE $2 OR tags::text ILIKE $2)"; params.append(f"%{search}%")
        if category: query += " AND category=$2" if not search else " AND category=$3"; params.append(category)
        if parent_id is not None: query += " AND parent_id=$2" if not search and not category else f" AND parent_id=${len(params)+1}"; params.append(parent_id)
        elif not recursive: query += " AND parent_id IS NULL"
        query += f" ORDER BY created_at DESC LIMIT ${len(params)+1}"; params.append(limit)
        notes = await conn.fetch(query, *params)
        if recursive and notes:
            for note in notes:
                children = await conn.fetch("SELECT id, content, tags, category, parent_id, created_at FROM notes WHERE user_id=$1 AND parent_id=$2 ORDER BY created_at", uid, note["id"])
                note["children"] = children
        return notes

async def get_note_tree(uid, root_id=None):
    async with db_pool.acquire() as conn:
        if root_id:
            root = await conn.fetchrow("SELECT id, content, tags, category, parent_id, created_at FROM notes WHERE id=$1 AND user_id=$2", root_id, uid)
            if not root: return None
            children = await conn.fetch("SELECT id, content, tags, category, parent_id, created_at FROM notes WHERE user_id=$1 AND parent_id=$2 ORDER BY created_at", uid, root_id)
            root["children"] = children
            return root
        else:
            roots = await conn.fetch("SELECT id, content, tags, category, parent_id, created_at FROM notes WHERE user_id=$1 AND parent_id IS NULL ORDER BY created_at DESC LIMIT 20", uid)
            for root in roots: root["children"] = await conn.fetch("SELECT id, content, tags, category, parent_id, created_at FROM notes WHERE user_id=$1 AND parent_id=$2 ORDER BY created_at", uid, root["id"])
            return roots

async def delete_note(uid, note_id):
    async with db_pool.acquire() as conn: await conn.execute("DELETE FROM notes WHERE id=$1 AND user_id=$2", note_id, uid)

async def create_calendar_event(uid, title, description, event_date, reminder_before=None, recurrence=None, category="general", visibility="private"):
    async with db_pool.acquire() as conn:
        return await conn.fetchval("INSERT INTO calendar_events(user_id, title, description, event_date, reminder_before, recurrence, category, visibility) VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING id", uid, title, description, event_date, reminder_before, recurrence, category, visibility)

async def create_habit(uid, name, frequency="daily", target_per_week=7, schedule_json=None):
    async with db_pool.acquire() as conn:
        if not await conn.fetchval("SELECT id FROM habits WHERE user_id=$1 AND name=$2", uid, name):
            return await conn.fetchval("INSERT INTO habits(user_id, name, frequency, target_per_week, schedule_json) VALUES ($1,$2,$3,$4,$5) RETURNING id", uid, name, frequency, target_per_week, schedule_json or {})
        return None

async def get_habits(uid):
    async with db_pool.acquire() as conn: return await conn.fetch("SELECT id, name, streak, last_done, frequency, target_per_week, schedule_json, created_at FROM habits WHERE user_id=$1", uid)

async def complete_habit(uid, habit_id, note=None):
    async with db_pool.acquire() as conn:
        today = now_moscow().date()
        await conn.execute("UPDATE habits SET streak = CASE WHEN last_done = $2 THEN streak ELSE streak + 1 END, last_done = $2 WHERE id=$1 AND user_id=$3", habit_id, today, uid)
        await conn.execute("INSERT INTO habit_logs(habit_id, note) VALUES ($1, $2)", habit_id, note)
        await update_activity_pattern(uid, "habit_complete", now_moscow())

async def get_habits_progress(uid, period="week"):
    days = 7 if period == "week" else 30
    async with db_pool.acquire() as conn:
        habits = await conn.fetch("SELECT id, name, frequency, target_per_week, schedule_json, last_done FROM habits WHERE user_id=$1", uid)
        result = []
        for h in habits:
            logs = await conn.fetch(f"SELECT completed_at::date as day FROM habit_logs WHERE habit_id=$1 AND completed_at >= NOW() - INTERVAL '{days} days'", h["id"])
            completed_count = len(logs)
            target = h["target_per_week"] if period == "week" else h["target_per_week"] * (30//7)
            percent = min(100, int(completed_count / max(1, target) * 100))
            result.append({"name": h["name"], "frequency": h["frequency"], "target": target, "completed": completed_count, "percent": percent, "history": [{"date": log["day"], "completed": True} for log in logs]})
        return result

async def get_profile(uid):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT name, age, gender, city, mode, preferred_tone, age_group, language FROM profile WHERE user_id=$1", uid)
        return dict(row) if row else None

async def save_profile(uid, name=None, age=None, gender=None, city=None, preferred_tone=None, age_group=None, language=None):
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO profile(user_id, name, age, gender, city, preferred_tone, age_group, language) VALUES ($1, $2, $3, $4, $5, $6, $7, $8) ON CONFLICT(user_id) DO UPDATE SET name = COALESCE($2, profile.name), age = COALESCE($3, profile.age), gender = COALESCE($4, profile.gender), city = COALESCE($5, profile.city), preferred_tone = COALESCE($6, profile.preferred_tone), age_group = COALESCE($7, profile.age_group), language = COALESCE($8, profile.language), updated_at = NOW()", uid, name, age, gender, city, preferred_tone, age_group, language)

# ======================
#  🔥 ДАШБОРД 3.0
# ======================
async def get_dashboard_data(uid: int, profile_ctx: dict, view_mode: str = "personal") -> dict:
    city = profile_ctx.get("city", CITY_DEFAULT)
    now = now_moscow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    weather, tasks, events, habits_prog = await asyncio.gather(
        get_weather_data(city), get_secure_tasks(uid, status="pending", with_linked_notes=True),
        get_secure_calendar(uid, from_date=now, to_date=now+timedelta(hours=12)),
        get_habits_progress(uid, period="week"), return_exceptions=True
    )
    task_notes = {}
    if tasks and not isinstance(tasks, Exception):
        note_ids = [nid for t in tasks for nid in (t.get("linked_note_ids") or [])]
        if note_ids:
            async with db_pool.acquire() as conn:
                notes = await conn.fetch("SELECT id, content, category FROM notes WHERE id = ANY($1)", note_ids)
                task_notes = {n["id"]: n for n in notes}
    insights = {}
    if view_mode == "personal":
        insights["mood_trend"] = await get_user_insight(uid, "mood_trend")
        insights["productivity_hours"] = await get_user_insight(uid, "productivity_hours")
    return {
        "weather": weather if not isinstance(weather, Exception) else None, "city": city,
        "tasks_today": tasks if not isinstance(tasks, Exception) else [], "task_notes": task_notes,
        "events_12h": events if not isinstance(events, Exception) else [],
        "habits_progress": habits_prog if not isinstance(habits_prog, Exception) else [],
        "stats": await get_task_stats(uid) if not isinstance(tasks, Exception) else None,
        "time": now.strftime("%H:%M"), "view_mode": view_mode, "insights": insights, "user_ctx": profile_ctx
    }

def format_dashboard(data: dict) -> str:
    user_ctx = data.get("user_ctx", {})
    style = get_age_appropriate_style(user_ctx.get("age_group", "adult"), user_ctx.get("gender"))
    lines = [f"{style['prefix']}📊 **Дашборд** • {data['time']}{style['suffix']}"]
    if data["weather"]:
        w = data["weather"]
        lines.append(f"\n🌤 **{data['city']}**: {w['temp']}°, {w['description']}\n💧 {w['humidity']}%  🌬 {w['wind']} м/с")
    if data["tasks_today"]:
        view_label = " (семейные)" if data.get("view_mode") == "family" else ""
        lines.append(f"\n📋 **Задачи на сегодня**{view_label} ({len(data['tasks_today'])}):")
        for t in data["tasks_today"][:3]:
            icon = {"high":"🔴","medium":"🟡","low":"🟢"}.get(t["priority"],"⚪")
            due = f" ({t['due_date'].strftime('%H:%M')})" if t["due_date"] else ""
            assigned = f" 👤 {t['assigned_name']}" if t.get("assigned_name") and t["assigned_to"] != data.get("user_ctx", {}).get("user_id") else ""
            lines.append(f"{icon} {t['title']}{due}{assigned}")
            if t.get("linked_notes") and data["task_notes"]:
                for nid in t["linked_note_ids"] or []:
                    note = data["task_notes"].get(nid)
                    if note: lines.append(f"   📎 [{note['category']}] {note['content'][:40]}...")
    if data["events_12h"]:
        lines.append(f"\n📅 **События**:")
        for e in data["events_12h"][:3]:
            vis = "👥 " if e["visibility"] == "family" else ""
            lines.append(f"• {vis}{e['event_date'].strftime('%H:%M')} — {e['title']}")
    if data["habits_progress"]:
        lines.append(f"\n🔁 **Привычки** (неделя):")
        for h in data["habits_progress"][:3]:
            bar = "█" * (h["percent"]//10) + "░" * (10 - h["percent"]//10)
            lines.append(f"• {h['name']}: [{bar}] {h['completed']}/{h['target']} ({h['percent']}%)")
    if data.get("insights") and data.get("view_mode") == "personal":
        if data["insights"].get("productivity_hours"):
            peak = data["insights"]["productivity_hours"]
            lines.append(f"\n💡 **Инсайт**: Ты наиболее продуктивен в {peak}:00–{peak+2}:00")
    return "\n".join(lines)

# ======================
#  🔥 УМНЫЕ НАПОМИНАНИЯ
# ======================
async def get_optimal_reminder_time(uid: int, activity_type: str) -> str | None:
    patterns = await get_user_insight(uid, "activity_patterns")
    if not patterns: return None
    hour_counts = {k.replace("hour_", ""): v for k, v in patterns.items() if k.startswith("hour_")}
    if hour_counts:
        best_hour = max(hour_counts, key=hour_counts.get)
        return f"{int(best_hour):02d}:00"
    return None

# ======================
#  INLINE КЛАВИАТУРЫ
# ======================
def main_menu_keyboard(has_family: bool = False):
    family_btn = InlineKeyboardButton(text="👨‍👩‍👦 Моя семья", callback_data="family") if has_family else InlineKeyboardButton(text="➕ Создать семью", callback_data="family_create")
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Задачи", callback_data="tasks_list"), InlineKeyboardButton(text="📝 Заметки", callback_data="notes_list")],
        [InlineKeyboardButton(text="🌳 Дерево", callback_data="notes_tree"), InlineKeyboardButton(text="📅 Календарь", callback_data="calendar_list")],
        [InlineKeyboardButton(text="🔁 Привычки", callback_data="habits_list"), InlineKeyboardButton(text="📊 Дашборд", callback_data="dashboard_show")],
        [InlineKeyboardButton(text="🌤 Погода", callback_data="ext_weather"), InlineKeyboardButton(text="🧠 Психоанализ", callback_data="ext_psycho")],
        [InlineKeyboardButton(text="🎬 Афиша", callback_data="ext_cinema"), InlineKeyboardButton(text="📰 Новости", callback_data="ext_news")],
        [family_btn, InlineKeyboardButton(text="❓ Помощь", callback_data="help_show")],
    ])

def family_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Участники", callback_data="family_members"), InlineKeyboardButton(text="🔗 Код приглашения", callback_data="family_invite")],
        [InlineKeyboardButton(text="🔄 Личный режим", callback_data="family_personal")],
    ])

def note_tree_keyboard(parent_id=None):
    buttons = []
    if parent_id: buttons.append([InlineKeyboardButton(text="↩️ Назад к корню", callback_data=f"note_tree_root")])
    return InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None

def profile_edit_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Имя", callback_data="profile_edit_name"), InlineKeyboardButton(text="✏️ Возраст", callback_data="profile_edit_age")],
        [InlineKeyboardButton(text="✏️ Город", callback_data="profile_edit_city"), InlineKeyboardButton(text="✏️ Пол", callback_data="profile_edit_gender")],
        [InlineKeyboardButton(text="✏️ Группа", callback_data="profile_edit_agegroup"), InlineKeyboardButton(text="✅ Готово", callback_data="profile_done")]
    ])

def task_category_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💼 Работа", callback_data="cat_work"), InlineKeyboardButton(text="🏠 Личное", callback_data="cat_personal"), InlineKeyboardButton(text="🛒 Покупки", callback_data="cat_shopping")],
        [InlineKeyboardButton(text="👨‍‍👦 Семейное", callback_data="cat_family"), InlineKeyboardButton(text="🔧 Другое", callback_data="cat_general")]
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

def task_visibility_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔒 Личная", callback_data="vis_private"), InlineKeyboardButton(text="👨‍👩‍‍👦 Семейная", callback_data="vis_family")]
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

def task_actions_keyboard(task_id, has_subtasks=False, has_checklist=False, has_linked_notes=False, is_family_task=False):
    buttons = [[InlineKeyboardButton(text="✅ Выполнить", callback_data=f"task_complete_{task_id}")]]
    if has_subtasks: buttons.append([InlineKeyboardButton(text="📝 Подзадачи", callback_data=f"task_subtasks_{task_id}")])
    if has_checklist: buttons.append([InlineKeyboardButton(text="📋 Чек-лист", callback_data=f"task_checklist_{task_id}")])
    if has_linked_notes: buttons.append([InlineKeyboardButton(text="📎 Заметки", callback_data=f"task_notes_{task_id}")])
    if is_family_task: buttons.append([InlineKeyboardButton(text="👥 Назначить", callback_data=f"task_assign_{task_id}")])
    buttons.append([InlineKeyboardButton(text="🗑 Удалить", callback_data=f"task_delete_{task_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def note_actions_keyboard(note_id, has_children=False):
    buttons = [[InlineKeyboardButton(text="🗑 Удалить заметку", callback_data=f"note_delete_{note_id}")]]
    if has_children: buttons.append([InlineKeyboardButton(text="📂 Подзаметки", callback_data=f"note_children_{note_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def external_link_keyboard(link: str, label: str = "Открыть"):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"🔗 {label}", url=link)]])

def dashboard_keyboard(view_mode: str = "personal"):
    buttons = [[InlineKeyboardButton(text="🔄 Обновить", callback_data="dashboard_refresh")]]
    if view_mode == "personal": buttons.append([InlineKeyboardButton(text="👨‍👩‍👦 Семейный вид", callback_data="dashboard_family")])
    else: buttons.append([InlineKeyboardButton(text="👤 Личный вид", callback_data="dashboard_personal")])
    buttons.append([InlineKeyboardButton(text="📋 Задачи", callback_data="tasks_list"), InlineKeyboardButton(text="📅 Календарь", callback_data="calendar_list")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ======================
#  FSM
# ======================
class TaskFSM(StatesGroup):
    title = State(); description = State(); priority = State(); due_date = State()
    category = State(); tags = State(); recurrence = State(); attachments = State()
    linked_notes = State(); visibility = State(); assign = State()

class NoteFSM(StatesGroup):
    template = State(); category = State(); content = State(); tags = State(); parent = State()

class CalendarFSM(StatesGroup):
    title = State(); description = State(); event_date = State(); recurrence = State(); visibility = State()

class ProfileEditFSM(StatesGroup):
    field = State(); value = State()

class FamilyFSM(StatesGroup):
    creating = State()  # FSM для создания семьи
    action = State()
    target = State()

# ✅ NEW FSM: Подтверждение сброса
class ResetFSM(StatesGroup):
    waiting_confirmation = State()

# ======================
#  🔥 AI: ОБЩИЙ ЧАТ
# ======================
async def call_openai_chat(user_text: str, profile_ctx: dict, mood: str = "нейтральное", memory: list = None):
    if not OPENROUTER_API_KEY: return await call_qwen_fallback(user_text, profile_ctx, mood, memory)
    user_name = profile_ctx.get("name") or "пользователь"
    city = profile_ctx.get("city", CITY_DEFAULT)
    is_short = any(k in user_text.lower() for k in ["шутк", "анекдот", "прикол", "факт", "коротко", "в двух словах"])
    style = get_age_appropriate_style(profile_ctx["age_group"], profile_ctx["gender"])
    system_prompt = f"""Ты — AssistEmpat, личный помощник {user_name}. Город: {city}.
ВОЗМОЖНОСТИ: задачи (с заметками), заметки (дерево), календарь, погода, кино, новости, дашборд, семейный режим.
ПРАВИЛА:
1. Если "привет"/"новая тема"/"забудь" — начинай заново.
2. Отвечай {'кратко и просто' if style['complexity']=='simple' else 'развёрнуто' } ({'2-3' if style['complexity']=='simple' else '3-5'} предл.), но кратко если просят шутку/факт.
3. {'Используй эмодзи умеренно' if style['emoji_level']=='low' else 'Добавляй эмодзи для живости' if style['emoji_level']=='high' else 'Используй эмодзи'}.
4. Не навязывай помощь с "проблемами" при болтовне.
5. {'Говори просто, как старший друг' if profile_ctx['age_group']=='child' else 'Будь на равных' if profile_ctx['age_group']=='teen' else 'Будь уважителен и конкретен' if profile_ctx['age_group']=='adult' else 'Объясняй пошагово, с заботой'}.
6. Учитывай предпочтения: {', '.join(style['tone_modifiers'])}.
Настроение: {mood}"""
    fm, seen = [], set()
    for m in reversed(memory[-5:] if memory else []):
        c = m["content"].strip()
        if c and len(c)>3 and c not in seen: fm.insert(0,m); seen.add(c)
    ctx = "\n".join([f"{m['role']}: {m['content']}" for m in fm])
    try:
        async with httpx.AsyncClient(timeout=15) as cl:
            r = await cl.post("https://openrouter.ai/api/v1/chat/completions", headers={"Authorization":f"Bearer {OPENROUTER_API_KEY}","Content-Type":"application/json"},
                json={"model":"openai/gpt-4o-mini","messages":[{"role":"system","content":system_prompt},{"role":"user","content":f"{ctx}\n{user_text}" if ctx else user_text}],
                "temperature":style["temperature"] if not is_short else 0.9, "max_tokens":style["max_tokens"] if not is_short else 150})
            r.raise_for_status()
            ans = r.json()["choices"][0]["message"]["content"].strip()
            if await is_duplicate_response(profile_ctx.get("user_id"), ans): return get_fallback_response(user_text, mood, profile_ctx)
            return format_response_for_user(ans, profile_ctx)
    except Exception as e:
        logging.error(f"OpenAI error: {e}")
        return await call_qwen_fallback(user_text, profile_ctx, mood, memory)

# ======================
#  🔥 AI: РЕЖИМ ЗДОРОВЬЯ
# ======================
async def call_health_ai(user_text: str, profile_ctx: dict, health_mem: list):
    if not OPENROUTER_API_KEY: return await call_qwen_fallback(user_text, profile_ctx, "нейтральное", health_mem)
    style = get_age_appropriate_style(profile_ctx["age_group"], profile_ctx["gender"])
    system_prompt = f"""Ты — ассистент по здоровому образу жизни для {'ребёнка' if profile_ctx['age_group']=='child' else 'подростка' if profile_ctx['age_group']=='teen' else 'взрослого' if profile_ctx['age_group']=='adult' else 'пожилого человека'}.
ПРАВИЛА: 1. Только ЗОЖ: режим, питание, гидратация, отдых, активность, гигиена, стресс-менеджмент. 2. НИКОГДА не называй препараты/БАДы/дозы. 3. При боли/температуре — рекомендуй врача. 4. {'Объясняй просто, с примерами' if profile_ctx['age_group']=='child' else 'Говори на равных' if profile_ctx['age_group']=='teen' else 'Будь конкретен' if profile_ctx['age_group']=='adult' else 'Объясняй пошагово, с заботой'}. 5. Дисклеймер: "Рекомендации не заменяют консультацию специалиста." Настроение учитывай, фокус на пользе."""
    ctx = "\n".join([f"{m['role']}: {m['content']}" for m in health_mem[-4:]])
    try:
        async with httpx.AsyncClient(timeout=15) as cl:
            r = await cl.post("https://openrouter.ai/api/v1/chat/completions", headers={"Authorization":f"Bearer {OPENROUTER_API_KEY}","Content-Type":"application/json"},
                json={"model":"openai/gpt-4o-mini","messages":[{"role":"system","content":system_prompt},{"role":"user","content":f"{ctx}\n{user_text}" if ctx else user_text}], "temperature":0.5, "max_tokens":style["max_tokens"]})
            r.raise_for_status()
            return format_response_for_user(r.json()["choices"][0]["message"]["content"].strip(), profile_ctx)
    except: return "🩺 Я не могу дать медицинский совет. Рекомендую обратиться к врачу."

# ======================
#  🔥 AI: РЕЖИМ ПСИХОАНАЛИЗА
# ======================
def detect_psycho_style(text: str, mood: str, age_group: str) -> tuple[str, float]:
    t = text.lower()
    if any(k in t for k in ["пинка", "встряхни", "достал себя жалеть", "хватит ныть", "что делать", "застрял", "не могу решиться", "дай совет", "как быть"]): return "tough", 0.4 if age_group != "child" else 0.6
    if mood == "радость" or any(k in t for k in ["посмеяться", "ирония", "сарказм", "по-доброму", "подколи", "шутк"]): return "sarcastic", 0.95 if age_group in ["teen", "adult"] else 0.7
    if mood in ["грусть", "тревога", "усталость"]: return "empathetic", 0.6
    return "analytical", 0.75

async def call_psycho_ai(user_text: str, profile_ctx: dict, psycho_mem: list, mood: str):
    if not OPENROUTER_API_KEY: return await call_qwen_fallback(user_text, profile_ctx, mood, psycho_mem)
    style_name, temperature = detect_psycho_style(user_text, mood, profile_ctx["age_group"])
    style = get_age_appropriate_style(profile_ctx["age_group"], profile_ctx["gender"])
    style_prompts = {
        "empathetic": f"""Ты — эмпатичный психоаналитик для {'ребёнка' if profile_ctx['age_group']=='child' else 'подростка' if profile_ctx['age_group']=='teen' else 'взрослого'}. Твоя задача — выслушать, отразить чувства, помочь разобраться в себе.
ПРАВИЛА: 1. Начинай с отражения эмоций ("Я слышу, что ты чувствуешь..."). 2. Задавай {'простые' if profile_ctx['age_group']=='child' else 'мягкие'} уточняющие вопросы. 3. Не давай готовых решений — помогай найти свои. 4. {'Используй простые слова, эмодзи, хвали' if profile_ctx['age_group']=='child' else 'Будь тёплым, человечным, без клише'}. 5. Дисклеймер в конце сеанса: "Я не заменяю профессионального психолога." Настроение: {mood}""",
        "analytical": f"""Ты — аналитичный психоаналитик для {'подростка' if profile_ctx['age_group']=='teen' else 'взрослого'}. Твоя задача — помочь структурировать мысли и увидеть ситуацию под разными углами.
ПРАВИЛА: 1. Разложи ситуацию на факты/чувства/возможности. 2. Задавай логичные уточняющие вопросы. 3. Предлагай варианты, но не навязывай. 4. Будь объективным, но поддерживающим. 5. Дисклеймер: "Я не заменяю профессионального психолога." Настроение: {mood}""",
        "tough": f"""Ты — прямой психоаналитик "жёсткой любви" для {'подростка' if profile_ctx['age_group']=='teen' else 'взрослого'}. Твоя задача — помочь выйти из застоя, взяв ответственность.
ПРАВИЛА: 1. Говори чётко, без воды. 2. Задавай прямые вопросы о действиях СЕГОДНЯ. 3. Не позволяй уходить в самокопание без вывода. 4. Поддерживай, но требуй конкретики. 5. Дисклеймер: "Я не заменяю профессионального психолога." Настроение: {mood}""",
        "sarcastic": f"""Ты — психоаналитик с лёгкой иронией для {'подростка' if profile_ctx['age_group']=='teen' else 'взрослого'}. Твоя задача — помочь увидеть ситуацию с юмором и снять напряжение.
ПРАВИЛА: 1. Используй добрый сарказм, не обижая. 2. Помогай увидеть абсурдность застоя через юмор. 3. После иронии — мягкий переход к действиям. 4. Следи, чтобы пользователь был в ресурсе для такого тона. 5. Дисклеймер: "Я не заменяю профессионального психолога." Настроение: {mood}"""
    }
    system_prompt = style_prompts.get(style_name, style_prompts["analytical"])
    ctx = "\n".join([f"{m['role']}: {m['content']}" for m in psycho_mem[-6:]])
    try:
        async with httpx.AsyncClient(timeout=20) as cl:
            r = await cl.post("https://openrouter.ai/api/v1/chat/completions", headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
                json={"model":"openai/gpt-4o-mini","messages":[{"role":"system","content":system_prompt},{"role":"user","content":f"{ctx}\n{user_text}" if ctx else user_text}], "temperature":temperature, "max_tokens":style["max_tokens"]})
            r.raise_for_status()
            return format_response_for_user(r.json()["choices"][0]["message"]["content"].strip(), profile_ctx)
    except: return "🧠 Я здесь, чтобы выслушать. Расскажи, что у тебя на душе?"

# ======================
#  🔥 FALLBACKS
# ======================
def get_fallback_response(user_text: str, mood: str, profile_ctx: dict) -> str:
    style = get_age_appropriate_style(profile_ctx["age_group"], profile_ctx["gender"])
    if mood == "грусть": return format_response_for_user("Понимаю. Расскажи, что случилось? 🤍", profile_ctx)
    if mood == "тревога": return format_response_for_user("Всё будет хорошо. Что беспокоит?", profile_ctx)
    if mood == "усталость": return format_response_for_user("Отдохни. Я тут, если что. 🫂", profile_ctx)
    return format_response_for_user("Понял. 👍", profile_ctx)

async def call_qwen_fallback(user_text, profile_ctx, mood, memory):
    if not QWEN_API_KEY: return get_fallback_response(user_text, mood, profile_ctx)
    user_name = profile_ctx.get("name") or "помощник"
    sys = f"Ты — {user_name}. Отвечай {'кратко и просто' if profile_ctx['age_group']=='child' else 'кратко'}."
    ctx = "\n".join([f"{m['role']}: {m['content']}" for m in (memory or [])[-2:]])
    try:
        async with httpx.AsyncClient(timeout=10) as cl:
            r = await cl.post("https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/text-generation/generation", headers={"Authorization":f"Bearer {QWEN_API_KEY}"},
                json={"model":"qwen-max","messages":[{"role":"system","content":sys},{"role":"user","content":f"{ctx}\n{user_text}" if ctx else user_text}], "temperature":0.7})
            r.raise_for_status()
            return format_response_for_user(r.json()["output"]["text"].strip(), profile_ctx)
    except: return get_fallback_response(user_text, mood, profile_ctx)

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
    "очисти память":"reset_context", "новая тема":"reset_context", "дерево":"notes_tree",
    "семья":"family_view", "семейный":"family_view", "пригласить":"family_invite", "инвайт":"family_invite",
    "создать семью": "family_create"
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
    family = await get_user_family(msg.from_user.id)
    # Используем Smart Menu
    await msg.answer(f"Привет, {name}." if name else "Привет. Как тебя зовут?", reply_markup=main_menu_keyboard(bool(family)))

@dp.message(Command("help"))
async def cmd_help(msg:Message):
    await msg.answer("""📋 **Команды:**
📊 /dashboard — сводка дня | /dashboard family — семейный вид
📝 /note — заметки | /note_tree — дерево заметок
📅 /event — события
📋 /task — задачи (можно привязывать заметки, делать семейными)
🔁 /habit — привычки | /habit_stats — статистика
🔄 /reset — сбросить контекст
👨‍👩‍‍👦 /family — управление семьёй | /join <код> — войти в семью
⏰ "напомни [что] [когда]"
🌤 /weather, 💱 /currency, 🩺 /health, 🧠 /psycho, 🎬 /cinema, 📰 /news
👤 /profile — мой профиль
Или нажми кнопку 👇""", parse_mode="Markdown", reply_markup=main_menu_keyboard(False))
@dp.message(Command("admin"))
async def cmd_admin(msg: Message):
    """Полный список команд и функций для администратора"""
    if not is_admin(msg.from_user.id):
        await msg.answer("🚫 Доступ запрещён. Эта команда доступна только создателю бота.")
        return
    
    admin_menu = """👑 **Панель Администратора**
*ID:* `{}` | *Роль:* Owner

📜 **Доступные команды:**
`/start` ` /help` ` /profile` ` /profile edit`
`/task` ` /tasks` ` /note` ` /notes` ` /note_tree`
`/event` ` /calendar` ` /habit` ` /habit_stats`
`/dashboard` ` /weather` ` /currency` ` /cinema` ` /news`
`/family` ` /join <код>` ` /reset` ` /switch`

⚙️ **Активные модули:**
🧠 **AI-режимы:** Здоровье, Психоанализ (адаптивный тон по возрасту/полу)
👨‍👩‍👧‍👦 **Семейный режим:** создание групп, инвайт-коды, общие задачи/события
📊 **Дашборд:** сводка дня, трекинг привычек, инсайты продуктивности
🔍 **NLP-парсер:** создание задач/заметок обычным текстом (без слешей)
🛡 **Безопасность:** изоляция данных, подтверждение `/reset`, FSM-защита

🛠 **Управление ботом:**
• Все настройки хранятся в `.env` (Railway Variables)
• База данных: Neon PostgreSQL (автоподключение)
• Логи: доступны в панели Railway → Logs
• Перезапуск: `git push` или кнопка Restart в Railway

💡 *Для системных действий (ключи, лимиты, логи) используй панель Railway.*
""".format(msg.from_user.id)
    
    await msg.answer(admin_menu, parse_mode="Markdown")
@dp.message(Command("profile"))
async def cmd_profile(msg:Message, state:FSMContext):
    p = await get_profile(msg.from_user.id)
    if not p: await msg.answer("Нет данных. Напиши: 'меня зовут...', 'город: СПб'"); return
    family = await get_user_family(msg.from_user.id)
    family_info = f"\n👨‍👩‍👦 Семья: {family['group_name']} ({family['role']})" if family else ""
    text = f"👤 **Профиль**\nИмя: {p['name'] or '—'}\nВозраст: {p['age'] or '—'} ({p.get('age_group','adult')})\nГород: {p['city'] or CITY_DEFAULT} 🌍\nСтиль: {p.get('preferred_tone','balanced')}{family_info}\n✏️ /profile edit"
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
    if news:
        text = "📰 **Новости**:\n" + "\n".join([f"• {n['title']}" for n in news])
        await msg.answer(text, reply_markup=external_link_keyboard(get_news_link(), "Все новости"))
    else: await msg.answer("📰 Новости:", reply_markup=external_link_keyboard(get_news_link(), "Яндекс.Новости"))

# ✅ NEW: Подтверждение сброса
@dp.message(Command("reset", "clear"))
async def cmd_reset(msg:Message, state:FSMContext):
    await state.set_state(ResetFSM.waiting_confirmation)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, очистить", callback_data="reset_yes")],
        [InlineKeyboardButton(text="❌ Нет", callback_data="reset_no")]
    ])
    await msg.answer("⚠️ **Внимание!**\nЭто действие полностью удалит историю диалога и контекст бота. Вы уверены?", reply_markup=kb)

@dp.callback_query(F.data == "reset_yes")
async def cb_reset_yes(call:CallbackQuery, state:FSMContext):
    await clear_user_context(call.from_user.id)
    await call.message.edit_text("✅ Контекст очищен. Начинаем с чистого листа! 😊")
    await state.clear()
    await call.answer()

@dp.callback_query(F.data == "reset_no")
async def cb_reset_no(call:CallbackQuery, state:FSMContext):
    await call.message.edit_text("❌ Отмена. Ничего не удалено.")
    await state.clear()
    await call.answer()

# ======================
#  🔥 СЕМЕЙНЫЙ РЕЖИМ
# ======================
@dp.message(Command("family"))
async def cmd_family(msg:Message):
    family = await get_user_family(msg.from_user.id)
    if not family:
        await msg.answer("👨‍👩‍👦 **Создать семью**\nНапиши: 'создать семью: [название]'\nИли нажми кнопку 👇", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➕ Создать семью", callback_data="family_create")]]))
        return
    members = await get_family_members(family["group_id"])
    text = f"👨‍👩‍👦 **{family['group_name']}**\nТвоя роль: {family['role']}\nУчастники:\n" + "\n".join([f"• {m['nickname'] or m['name']} ({m['role']})" for m in members])
    await msg.answer(text, reply_markup=family_keyboard())

@dp.message(Command("join"))
async def cmd_family_join(msg: Message):
    uid = msg.from_user.id
    parts = msg.text.split()
    if len(parts) < 2: await msg.answer("❌ Напиши: `/join <код>`"); return
    code = parts[1]
    success = await join_family_by_code(uid, code)
    if success:
        family = await get_user_family(uid)
        await msg.answer(f"✅ **Ты в семье \"{family['group_name']}\"!**\nТеперь ты видишь общие задачи и события.")
    else: await msg.answer("❌ Код неверный, истёк или уже использован.")

@dp.message(Command("switch"))
async def cmd_switch(msg:Message):
    await msg.answer("🔄 Переключение профиля: в разработке")

# ======================
#  🔥 ДАШБОРД
# ======================
@dp.message(Command("dashboard"))
async def cmd_dashboard(msg:Message):
    profile_ctx = await get_user_profile_context(msg.from_user.id)
    view_mode = "family" if "family" in msg.text.lower() else "personal"
    data = await get_dashboard_data(msg.from_user.id, profile_ctx, view_mode)
    await msg.answer(format_dashboard(data), parse_mode="Markdown", reply_markup=dashboard_keyboard(view_mode))

@dp.callback_query(F.data=="dashboard_show")
async def cb_dashboard(call:CallbackQuery):
    profile_ctx = await get_user_profile_context(call.from_user.id)
    family = await get_user_family(call.from_user.id)
    view_mode = "family" if family else "personal"
    data = await get_dashboard_data(call.from_user.id, profile_ctx, view_mode)
    await call.message.edit_text(format_dashboard(data), parse_mode="Markdown", reply_markup=dashboard_keyboard(view_mode))
    await call.answer()

@dp.callback_query(F.data=="dashboard_refresh")
async def cb_dashboard_refresh(call:CallbackQuery):
    await cb_dashboard(call)

@dp.callback_query(F.data=="dashboard_family")
async def cb_dashboard_family(call:CallbackQuery):
    profile_ctx = await get_user_profile_context(call.from_user.id)
    data = await get_dashboard_data(call.from_user.id, profile_ctx, "family")
    await call.message.edit_text(format_dashboard(data), parse_mode="Markdown", reply_markup=dashboard_keyboard("family"))
    await call.answer()

@dp.callback_query(F.data=="dashboard_personal")
async def cb_dashboard_personal(call:CallbackQuery):
    profile_ctx = await get_user_profile_context(call.from_user.id)
    data = await get_dashboard_data(call.from_user.id, profile_ctx, "personal")
    await call.message.edit_text(format_dashboard(data), parse_mode="Markdown", reply_markup=dashboard_keyboard("personal"))
    await call.answer()

# ======================
#  🔥 ПРОФИЛЬ: РЕДАКТИРОВАНИЕ
# ======================
@dp.callback_query(F.data.startswith("profile_edit_"))
async def profile_edit_cb(call:CallbackQuery, state:FSMContext):
    field = call.data.split("_")[-1]
    await state.update_data(field=field)
    await state.set_state(ProfileEditFSM.value)
    prompts = {"name": "✏️ Новое имя:", "age": "✏️ Возраст (число):", "gender": "✏️ Пол (муж/жен/другое):", "city": "✏️ Город:", "agegroup": "✏️ Возрастная группа (child/teen/adult/senior):"}
    await call.message.answer(prompts.get(field, "✏️ Введите:"))
    await call.answer()

@dp.message(ProfileEditFSM.value)
async def profile_save_value(msg:Message, state:FSMContext):
    data = await state.get_data()
    field, value = data.get("field"), msg.text.strip()
    if field == "age":
        try: value = int(value)
        except: await msg.answer("❌ Возраст — число"); return
    if field == "agegroup" and value not in ["child","teen","adult","senior"]:
        await msg.answer("❌ Допустимые значения: child, teen, adult, senior"); return
    await save_profile(msg.from_user.id, **{field: value})
    await msg.answer(f"✅ {field}: {value}")
    await state.clear()
    p = await get_profile(msg.from_user.id)
    await msg.answer(f"👤 {p['name'] or '—'} • {p['city'] or CITY_DEFAULT} 🌍", reply_markup=profile_edit_keyboard())

@dp.callback_query(F.data=="profile_done")
async def profile_done_cb(call:CallbackQuery, state:FSMContext):
    await state.clear()
    await call.answer("✅ Сохранено", show_alert=True)

# ======================
#  🔥 ЗАМЕТКИ
# ======================
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
    await state.set_state(NoteFSM.parent)
    await call.message.answer("🔗 Родительская заметка? (ID или /skip для корня):")
    await call.answer()

@dp.message(NoteFSM.parent, F.text=="/skip")
async def note_parent_skip(msg:Message, state:FSMContext):
    await state.update_data(parent_id=None)
    await state.set_state(NoteFSM.content)
    tpl = (await state.get_data()).get("template")
    content = NOTE_TEMPLATES.get(tpl, "") if tpl else ""
    await msg.answer(f"📝 Текст:\n{content}\n(/skip — отмена)")

@dp.message(NoteFSM.parent)
async def note_parent(msg:Message, state:FSMContext):
    try:
        parent_id = int(msg.text.strip())
        await state.update_data(parent_id=parent_id)
    except:
        await msg.answer("❌ Введите числовой ID заметки или /skip")
        return
    await state.set_state(NoteFSM.content)
    tpl = (await state.get_data()).get("template")
    content = NOTE_TEMPLATES.get(tpl, "") if tpl else ""
    await msg.answer(f"📝 Текст:\n{content}\n(/skip — отмена)")

@dp.message(NoteFSM.content, F.text=="/skip")
async def note_skip(msg:Message, state:FSMContext):
    await state.clear()
    await msg.answer("❌ Отменено")

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
    note_id = await create_note(msg.from_user.id, data["content"], None, data.get("category","general"), data.get("parent_id"))
    await msg.answer(f"✅ #{note_id}", reply_markup=note_actions_keyboard(note_id))
    await state.clear()

@dp.message(NoteFSM.tags)
async def note_tags(msg:Message, state:FSMContext):
    tags = [t.strip() for t in msg.text.split(",") if t.strip()]
    data = await state.get_data()
    note_id = await create_note(msg.from_user.id, data["content"], tags, data.get("category","general"), data.get("parent_id"))
    await msg.answer(f"✅ #{note_id}", reply_markup=note_actions_keyboard(note_id))
    await state.clear()

@dp.message(Command("notes"))
async def cmd_notes(msg:Message):
    notes = await get_notes(msg.from_user.id)
    if not notes: await msg.answer("📝 Нет заметок. /note", reply_markup=main_menu_keyboard(False)); return
    text = "📝 **Заметки**:\n" + "\n".join([f"#{n['id']} [{n['category']}] {n['content'][:60]}..." for n in notes[:5]])
    await msg.answer(text, reply_markup=main_menu_keyboard(False))

@dp.message(Command("note_tree"))
async def cmd_note_tree(msg:Message):
    tree = await get_note_tree(msg.from_user.id)
    if not tree: await msg.answer("🌳 Нет заметок. /note", reply_markup=main_menu_keyboard(False)); return
    def format_tree(notes, level=0):
        lines = []
        for n in notes:
            indent = "  " * level
            preview = n["content"][:50] + "..." if len(n["content"]) > 50 else n["content"]
            lines.append(f"{indent}📄 #{n['id']} [{n['category']}] {preview}")
            if n.get("children"): lines.extend(format_tree(n["children"], level+1))
        return lines
    text = "🌳 **Дерево заметок**:\n" + "\n".join(format_tree(tree if isinstance(tree, list) else [tree]))
    await msg.answer(text, reply_markup=main_menu_keyboard(False))

# ======================
#  🔥 КАЛЕНДАРЬ
# ======================
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
    await state.set_state(CalendarFSM.visibility)
    await msg.answer("👁️ Видимость:", reply_markup=task_visibility_keyboard())

@dp.callback_query(F.data.startswith("vis_"))
async def event_visibility_cb(call:CallbackQuery, state:FSMContext):
    visibility = call.data.split("_")[1]
    await state.update_data(visibility=visibility)
    await state.set_state(CalendarFSM.recurrence)
    await call.message.answer("🔄 Повтор:", reply_markup=task_recurrence_keyboard())
    await call.answer()

@dp.callback_query(F.data.startswith("rec_"))
async def event_recurrence_cb(call:CallbackQuery, state:FSMContext):
    recurrence = call.data.split("_")[1] if call.data != "rec_none" else None
    await state.update_data(recurrence=recurrence)
    data = await state.get_data()
    event_id = await create_calendar_event(call.from_user.id, data["title"], data.get("description"), data["event_date"], recurrence=recurrence, visibility=data.get("visibility","private"))
    await call.message.answer(f"✅ #{event_id}: {data['title']}\n🗓 {data['event_date'].astimezone(MOSCOW_TZ).strftime('%d.%m %H:%M')}")
    await state.clear()
    await call.answer()

@dp.message(Command("calendar"))
async def cmd_calendar(msg:Message):
    events = await get_secure_calendar(msg.from_user.id)
    if not events: await msg.answer("📅 Нет событий. /event", reply_markup=main_menu_keyboard(False)); return
    text = "📅 **События**:\n" + "\n".join([f"• {e['title']}\n🗓 {e['event_date'].astimezone(MOSCOW_TZ).strftime('%d.%m %H:%M')}" for e in events[:5]])
    await msg.answer(text, reply_markup=main_menu_keyboard(False))

# ======================
#  🔥 ЗАДАЧИ
# ======================
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
    await state.set_state(TaskFSM.visibility)
    await call.message.answer("👁️ Видимость:", reply_markup=task_visibility_keyboard())
    await call.answer()

@dp.callback_query(F.data.startswith("vis_"))
async def task_visibility_cb(call:CallbackQuery, state:FSMContext):
    visibility = call.data.split("_")[1]
    await state.update_data(visibility=visibility)
    await state.set_state(TaskFSM.linked_notes)
    await call.message.answer("📎 Привязать заметки? (через запятую ID или /skip):")
    await call.answer()

@dp.message(TaskFSM.linked_notes, F.text=="/skip")
async def task_skip_linked_notes(msg:Message, state:FSMContext):
    await state.update_data(linked_note_ids=None)
    await state.set_state(TaskFSM.tags)
    await msg.answer("🏷 Теги (/skip):")

@dp.message(TaskFSM.linked_notes)
async def task_linked_notes(msg:Message, state:FSMContext):
    try:
        linked = [int(x.strip()) for x in msg.text.split(",") if x.strip().isdigit()]
        await state.update_data(linked_note_ids=linked)
    except:
        await msg.answer("❌ Введите числа через запятую или /skip")
        return
    await state.set_state(TaskFSM.tags)
    await msg.answer("🏷 Теги (/skip):")

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
async def task_skip_attachments(msg:Message, state:FSMContext):
    await _finish_task_creation(msg, state, None)

@dp.message(TaskFSM.attachments)
async def task_attachments(msg:Message, state:FSMContext):
    await _finish_task_creation(msg, state, [a.strip() for a in msg.text.split(",") if a.strip()])

async def _finish_task_creation(msg:Message, state:FSMContext, attachments):
    data = await state.get_data()
    task_id = await create_task(
        uid=msg.from_user.id, title=data["title"], description=data.get("description"),
        priority=data.get("priority","medium"), due_date=data.get("due_date"), category=data.get("category","general"),
        tags=data.get("tags"), parent_id=None, recurrence=data.get("recurrence"), attachments=attachments,
        linked_note_ids=data.get("linked_note_ids"), visibility=data.get("visibility","private")
    )
    has_linked = bool(data.get("linked_note_ids"))
    is_family = data.get("visibility") == "family"
    await msg.answer(f"✅ #{task_id}: {data['title']}", reply_markup=task_actions_keyboard(task_id, has_linked_notes=has_linked, is_family_task=is_family))
    await state.clear()

@dp.message(Command("tasks"))
async def cmd_tasks(msg:Message):
    tasks = await get_secure_tasks(msg.from_user.id, with_linked_notes=True)
    if not tasks: await msg.answer("📋 Нет задач. /task", reply_markup=main_menu_keyboard(False)); return
    lines = ["📋 **Задачи**:"]
    for t in tasks[:5]:
        due = f" ({t['due_date'].astimezone(MOSCOW_TZ).strftime('%H:%M')})" if t['due_date'] else ""
        vis = "👥 " if t["visibility"] == "family" else ""
        assigned = f" 👤 {t['assigned_name']}" if t.get("assigned_name") else ""
        lines.append(f"• {vis}{t['title']}{due}{assigned}")
        if t.get("linked_notes"):
            for n in t["linked_notes"]:
                preview = n["content"][:40] + "..." if len(n["content"]) > 40 else n["content"]
                lines.append(f"  📎 [{n['category']}] {preview}")
    await msg.answer("\n".join(lines), reply_markup=main_menu_keyboard(False))

# ======================
#  🔥 ПРИВЫЧКИ
# ======================
@dp.message(Command("habit"))
async def cmd_habit_start(msg:Message):
    await msg.answer("🔁 **Создание привычки**\nНапиши: 'привычка: [название], [частота], [цель]'\nПримеры:\n• привычка: Медитация, ежедневно, 1 раз/день\n• привычка: Чтение, 3 раза в неделю, 30 минут")

@dp.message(Command("habit_stats"))
async def cmd_habit_stats(msg:Message):
    progress = await get_habits_progress(msg.from_user.id, period="week")
    if not progress: await msg.answer("📊 Нет данных по привычкам. Создай через /habit"); return
    lines = ["📈 **Прогресс привычек** (неделя):"]
    for h in progress:
        bar = "█" * (h["percent"]//10) + "░" * (10 - h["percent"]//10)
        lines.append(f"• {h['name']}: [{bar}] {h['completed']}/{h['target']} ({h['percent']}%)")
    await msg.answer("\n".join(lines))

# ======================
#  CALLBACKS
# ======================
@dp.callback_query(F.data=="tasks_list")
async def cb_tasks(call:CallbackQuery):
    tasks = await get_secure_tasks(call.from_user.id, with_linked_notes=True)
    if not tasks:
        await call.message.edit_text("📋 Задачи:\nНет задач", reply_markup=main_menu_keyboard(False))
    else:
        lines = ["📋 Задачи:"]
        for t in tasks[:5]:
            due = f" ({t['due_date'].astimezone(MOSCOW_TZ).strftime('%H:%M')})" if t['due_date'] else ""
            vis = "👥 " if t["visibility"] == "family" else ""
            assigned = f" 👤 {t['assigned_name']}" if t.get("assigned_name") else ""
            lines.append(f"• {vis}{t['title']}{due}{assigned}")
            if t.get("linked_notes"):
                for n in t["linked_notes"]:
                    preview = n["content"][:30] + "..." if len(n["content"]) > 30 else n["content"]
                    lines.append(f"  📎 {preview}")
        await call.message.edit_text("\n".join(lines), reply_markup=main_menu_keyboard(False))
    await call.answer()

@dp.callback_query(F.data.startswith("task_complete_"))
async def cb_task_done(call:CallbackQuery):
    await complete_task(call.from_user.id, int(call.data.split("_")[-1]))
    await call.answer("✅")
    await call.message.delete()

@dp.callback_query(F.data.startswith("task_delete_"))
async def cb_task_del(call:CallbackQuery):
    await delete_task(call.from_user.id, int(call.data.split("_")[-1]))
    await call.answer("🗑")
    await call.message.delete()

@dp.callback_query(F.data.startswith("task_subtasks_"))
async def cb_task_subtasks(call:CallbackQuery):
    subtasks = await get_subtasks(call.from_user.id, int(call.data.split("_")[-1]))
    await call.message.answer("📋 Подзадачи:\n" + "\n".join([f"• {st['title']}" for st in subtasks]) if subtasks else "Нет подзадач")

@dp.callback_query(F.data.startswith("task_notes_"))
async def cb_task_notes(call:CallbackQuery):
    task_id = int(call.data.split("_")[-1])
    await call.message.answer("📎 Привязанные заметки:\n(функционал в разработке)")

@dp.callback_query(F.data=="notes_list")
async def cb_notes(call:CallbackQuery):
    notes = await get_notes(call.from_user.id)
    if not notes:
        await call.message.edit_text("📝 Заметки:\nНет заметок", reply_markup=main_menu_keyboard(False))
    else:
        lines = ["📝 Заметки:"]
        for n in notes[:5]:
            preview = n["content"][:40] + "..." if len(n["content"]) > 40 else n["content"]
            lines.append(f"#{n['id']} [{n['category']}] {preview}")
        await call.message.edit_text("\n".join(lines), reply_markup=main_menu_keyboard(False))
    await call.answer()

@dp.callback_query(F.data=="notes_tree")
async def cb_notes_tree(call:CallbackQuery):
    tree = await get_note_tree(call.from_user.id)
    if not tree:
        await call.message.edit_text("🌳 Дерево заметок:\nНет заметок", reply_markup=main_menu_keyboard(False))
    else:
        def format_tree(notes, level=0):
            lines = []
            for n in notes:
                indent = "  " * level
                preview = n["content"][:40] + "..." if len(n["content"]) > 40 else n["content"]
                lines.append(f"{indent}📄 #{n['id']} [{n['category']}] {preview}")
                if n.get("children"): lines.extend(format_tree(n["children"], level+1))
            return lines
        text = "🌳 **Дерево заметок**:\n" + "\n".join(format_tree(tree if isinstance(tree, list) else [tree]))
        await call.message.edit_text(text, reply_markup=main_menu_keyboard(False))
    await call.answer()

@dp.callback_query(F.data=="calendar_list")
async def cb_calendar(call:CallbackQuery):
    events = await get_secure_calendar(call.from_user.id)
    if not events:
        await call.message.edit_text("📅 События:\nНет событий", reply_markup=main_menu_keyboard(False))
    else:
        lines = ["📅 События:"]
        for e in events[:5]:
            vis = "👥 " if e["visibility"] == "family" else ""
            lines.append(f"• {vis}{e['event_date'].astimezone(MOSCOW_TZ).strftime('%d.%m %H:%M')} — {e['title']}")
        await call.message.edit_text("\n".join(lines), reply_markup=main_menu_keyboard(False))
    await call.answer()

@dp.callback_query(F.data=="habits_list")
async def cb_habits(call:CallbackQuery):
    habits = await get_habits(call.from_user.id)
    if not habits:
        await call.message.edit_text("🔁 Привычки:\nНет привычек. /habit", reply_markup=main_menu_keyboard(False))
    else:
        lines = ["🔁 Привычки:"]
        for h in habits:
            lines.append(f"• {h['name']}: {h['streak']} дн. ({h['frequency']}, цель: {h['target_per_week']}/нед)")
        await call.message.edit_text("\n".join(lines), reply_markup=main_menu_keyboard(False))
    await call.answer()

@dp.callback_query(F.data=="reminders_list")
async def cb_reminders(call:CallbackQuery):
    await call.message.answer("⏰ Напиши: 'напомни [что] [когда]'")
    await call.answer()

@dp.callback_query(F.data=="profile_show")
async def cb_profile(call:CallbackQuery):
    p = await get_profile(call.from_user.id)
    family = await get_user_family(call.from_user.id)
    family_info = f" • {family['group_name']}" if family else ""
    await call.answer(f"👤 {p['name'] or '—'} • {p['city'] or CITY_DEFAULT}{family_info}", show_alert=True)

@dp.callback_query(F.data=="help_show")
async def cb_help(call:CallbackQuery):
    await call.answer("/help — список команд", show_alert=True)

@dp.callback_query(F.data.startswith("note_delete_"))
async def cb_note_del(call:CallbackQuery):
    await delete_note(call.from_user.id, int(call.data.split("_")[-1]))
    await call.answer("🗑")
    await call.message.delete()

@dp.callback_query(F.data.startswith("note_children_"))
async def cb_note_children(call:CallbackQuery):
    note_id = int(call.data.split("_")[-1])
    children = await get_notes(call.from_user.id, parent_id=note_id)
    if not children: await call.message.answer("📂 Нет подзаметок")
    else:
        lines = ["📂 Подзаметки:"]
        for c in children:
            preview = c["content"][:40] + "..." if len(c["content"]) > 40 else c["content"]
            lines.append(f"#{c['id']} {preview}")
        await call.message.answer("\n".join(lines))

# ======================
#  🔥 СЕМЕЙНЫЕ CALLBACKS
# ======================
@dp.callback_query(F.data=="family_view")
async def cb_family_view(call:CallbackQuery):
    family = await get_user_family(call.from_user.id)
    if not family: await call.answer("❌ Сначала создай или вступи в семью", show_alert=True); return
    await call.message.answer(f"👨‍👩‍‍👦 **{family['group_name']}**\nТвоя роль: {family['role']}", reply_markup=family_keyboard())
    await call.answer()

@dp.callback_query(F.data=="family_create")
async def cb_family_create(call:CallbackQuery, state:FSMContext):
    await state.set_state(FamilyFSM.creating)
    await call.message.answer("👨‍‍‍ **Введите название семьи**: (напиши одним сообщением)")
    await call.answer()

@dp.message(FamilyFSM.creating)
async def family_name_input(msg: Message, state: FSMContext):
    family_name = msg.text.strip()
    if len(family_name) < 2:
        await msg.answer("❌ Название слишком короткое. Попробуй ещё раз.")
        return
    try:
        group_id = await create_family_group(family_name, msg.from_user.id)
        code = await create_family_invite(group_id, msg.from_user.id)
        await msg.answer(f"✅ **Семья \"{family_name}\" создана!**\n🔗 **Твой код приглашения**: `{code}`\n⏰ Код действует 24 часа.\nСкинь код участникам, чтобы они ввели: `/join {code}`")
        await state.clear()
    except Exception as e:
        logging.error(f"Family creation error: {e}")
        await msg.answer("❌ Не удалось создать семью. Попробуй позже.")
        await state.clear()

@dp.callback_query(F.data=="family_members")
async def cb_family_members(call:CallbackQuery):
    family = await get_user_family(call.from_user.id)
    if not family: await call.answer("❌ Ты не в семье", show_alert=True); return
    members = await get_family_members(family["group_id"])
    text = "👥 **Участники**:\n" + "\n".join([f"• {m['nickname'] or m['name']} ({m['role']})" for m in members])
    await call.message.answer(text)
    await call.answer()

@dp.callback_query(F.data=="family_invite")
async def cb_family_invite(call:CallbackQuery):
    family = await get_user_family(call.from_user.id)
    if not family or family["role"] != "admin": await call.answer("❌ Только админ может приглашать", show_alert=True); return
    code = await create_family_invite(family["group_id"], call.from_user.id)
    await call.message.answer(f"🔗 **Твой код приглашения**: `{code}`\nСкинь его тому, кого хочешь добавить. Код действует 24 часа.")
    await call.answer()

@dp.callback_query(F.data=="family_personal")
async def cb_family_personal(call:CallbackQuery):
    await call.message.answer("🔄 Переключено на личный режим")
    await call.answer()

# ======================
#  🔥 ВНЕШНИЕ ДАННЫЕ: CALLBACKS
# ======================
@dp.callback_query(F.data=="ext_weather")
async def cb_ext_weather(call:CallbackQuery):
    profile_ctx = await get_user_profile_context(call.from_user.id)
    city = profile_ctx.get("city") or CITY_DEFAULT
    weather = await get_weather_data(city)
    if weather: await call.message.answer(f"🌤 {city}: {weather['temp']}°, {weather['description']}")
    else: await call.message.answer(f"🌤 {city}:", reply_markup=external_link_keyboard(get_weather_link(city), "Яндекс.Погода"))
    await call.answer()

@dp.callback_query(F.data=="ext_health")
async def cb_ext_health(call:CallbackQuery):
    profile_ctx = await get_user_profile_context(call.from_user.id)
    await set_user_mode(call.from_user.id, "health", "[]")
    await call.message.answer("🩺 **Режим здоровья активирован**\nЯ помогу с рекомендациями по ЗОЖ, сну, питанию и отдыху.\n⚠️ Я не врач и не назначаю препараты. Опиши, что беспокоит или что хочешь улучшить?")
    await call.answer()

@dp.callback_query(F.data=="ext_psycho")
async def cb_ext_psycho(call:CallbackQuery):
    profile_ctx = await get_user_profile_context(call.from_user.id)
    await set_user_mode(call.from_user.id, "psycho", "", "[]")
    await call.message.answer("🧠 **Режим психоанализа активирован**\nРасскажи, что у тебя на душе? Я здесь, чтобы выслушать и помочь разобраться. 🤍\n⚠️ Я не заменяю профессионального психолога. При острых состояниях обращайся к специалисту.")
    await call.answer()

@dp.callback_query(F.data=="ext_cinema")
async def cb_ext_cinema(call:CallbackQuery):
    profile_ctx = await get_user_profile_context(call.from_user.id)
    city = profile_ctx.get("city") or CITY_DEFAULT
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
#  🔥 🔥  ОСНОВНОЙ ЧАТ (v4.9) 🔥 🔥
# ======================
@dp.message()
async def chat(msg:Message, state:FSMContext):
    if not msg.text or await state.get_state(): return
    uid = msg.from_user.id
    text = fix_layout(msg.text.strip())
    text_lower = text.lower()

    # 🔥 ПРЯМАЯ ПРОВЕРКА НА МЕНЮ (Smart Menu)
    if "меню" in text_lower or text_lower == "menu":
        family = await get_user_family(uid)
        await msg.answer("📋 **Меню**:", reply_markup=main_menu_keyboard(bool(family)))
        return

    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO users(user_id,name) VALUES ($1,$2) ON CONFLICT DO NOTHING", uid, msg.from_user.first_name)
    await update_last_activity(uid)
    profile_ctx = await get_user_profile_context(uid)
    
    # Сохранение профиля
    if not profile_ctx.get("name"):
        name,age,gender,city = extract_profile(text)
        if name or city:
            await save_profile(uid, name=name, age=age, gender=gender, city=city)
            profile_ctx = await get_user_profile_context(uid)
            await msg.answer(f"Запомнил: {name or city}")
            return

    current_mode = profile_ctx.get("mode", "general")

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
        answer = await call_health_ai(text, profile_ctx, h_ctx)
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
            bridge = suggest_mode_bridge("psycho", "tasks", {})
            if bridge: await msg.answer(bridge)
            return
        p_ctx = await get_psycho_context(uid)
        p_ctx.append({"role": "user", "content": text})
        await save_psycho_context(uid, p_ctx)
        answer = await call_psycho_ai(text, profile_ctx, p_ctx, await get_mood(uid))
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
    await update_activity_pattern(uid, "message", now_moscow())
    
    cmd = parse_ru_command(text)
    if cmd:
        if cmd == "reset_context":
            await clear_user_context(uid)
            await msg.answer("✅ Контекст очищен! Начинаем с чистого листа. 😊")
            return
        elif cmd == "show_menu":
            family = await get_user_family(uid)
            await msg.answer("📋 **Меню**:", reply_markup=main_menu_keyboard(bool(family)))
            return
        elif cmd == "list_tasks": await cmd_tasks(msg); return
        elif cmd == "notes_list": await cmd_notes(msg); return
        elif cmd == "notes_tree": await cmd_note_tree(msg); return
        elif cmd == "calendar_list": await cmd_calendar(msg); return
        elif cmd == "habits_list": await cb_habits(msg); return
        elif cmd == "dashboard_show": await cmd_dashboard(msg); return
        elif cmd == "ext_weather":
            city = profile_ctx.get("city") or CITY_DEFAULT
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
            await msg.answer("🩺 **Режим здоровья активирован**\nЯ помогу с рекомендациями по ЗОЖ, сну, питанию и отдыху.\n⚠️ Я не врач и не назначаю препараты. Опиши, что беспокоит или что хочешь улучшить?")
            return
        elif cmd == "ext_psycho":
            await set_user_mode(uid, "psycho", "", "[]")
            await msg.answer("🧠 **Режим психоанализа активирован**\nРасскажи, что у тебя на душе? Я здесь, чтобы выслушать и помочь разобраться. 🤍\n️ Я не заменяю профессионального психолога. При острых состояниях обращайся к специалисту.")
            return
        elif cmd == "ext_cinema":
            city = profile_ctx.get("city") or CITY_DEFAULT
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
        elif cmd == "family_view": await cmd_family(msg); return

    # ✅ NLP: Распознавание команд в тексте (Задачи/Заметки)
    if any(kw in text_lower for kw in ["создай задачу", "добавь задачу", "новая задача", "задача:"]):
        tt = text
        for kw in ["создай задачу", "добавь задачу", "новая задача", "задача:"]:
            if kw in tt: tt = tt.split(kw)[-1].strip(); break
        if tt and len(tt) > 3:
            tid = await create_task(uid, title=tt, category="general", priority="medium")
            await msg.answer(f"✅ Задача #{tid} создана: {tt}\nИспользуй /tasks чтобы посмотреть все задачи", reply_markup=task_actions_keyboard(tid))
            return

    if any(kw in text_lower for kw in ["запиши заметку", "создай заметку", "добавь заметку", "заметка:", "запиши"]):
        nc = text
        for kw in ["запиши заметку", "создай заметку", "добавь заметку", "заметка:", "запиши"]:
            if kw in nc: nc = nc.split(kw)[-1].strip(); break
        if nc and len(nc) > 3:
            nid = await create_note(uid, content=nc, category="general")
            await msg.answer(f"✅ Заметка #{nid} сохранена!\nИспользуй /notes чтобы посмотреть все заметки", reply_markup=note_actions_keyboard(nid))
            return

    if any(kw in text_lower for kw in ["добавь событие", "создай событие", "встреча:", "план:"]):
        await msg.answer("📅 Для создания события используй команду /event — так будет надёжнее!")
        return

    # Отправка в AI
    answer = await call_openai_chat(text, profile_ctx, mood, memory)
    await msg.answer(answer)

# ======================
#  🔥 ПЛАНИРОВЩИК
# ======================
async def morning_quote():
    async with db_pool.acquire() as conn: users = await conn.fetch("SELECT user_id FROM users")
    for u in users:
        try: await bot.send_message(u["user_id"], f"☀️ **Доброе утро!**\n{await get_next_quote_for_user(u['user_id'])}")
        except: pass

async def afternoon_fact():
    async with db_pool.acquire() as conn: users = await conn.fetch("SELECT user_id FROM users")
    for u in users:
        try: await bot.send_message(u["user_id"], f"🧠 **Факт дня**:\n{await get_next_fact_for_user(u['user_id'])}")
        except: pass

async def morning_ping():
    async with db_pool.acquire() as conn: users = await conn.fetch("SELECT user_id FROM users")
    for u in users:
        try:
            profile_ctx = await get_user_profile_context(u["user_id"])
            data = await get_dashboard_data(u["user_id"], profile_ctx)
            await bot.send_message(u["user_id"], f"☀️ **План на день**\n" + format_dashboard(data), parse_mode="Markdown")
        except: pass

async def evening_report():
    async with db_pool.acquire() as conn: users = await conn.fetch("SELECT user_id FROM users")
    for u in users:
        try:
            comp = await conn.fetchval("SELECT COUNT(*) FROM tasks WHERE user_id=$1 AND status='completed' AND completed_at::date = CURRENT_DATE", u["user_id"])
            pend = await conn.fetchval("SELECT COUNT(*) FROM tasks WHERE user_id=$1 AND status='pending' AND due_date::date = CURRENT_DATE", u["user_id"])
            await bot.send_message(u["user_id"], f"🌙 **Итоги дня**\n✅ Выполнено: {comp}\n⏳ На завтра: {pend}\nОтличная работа! 💪")
        except: pass

async def habit_check():
    async with db_pool.acquire() as conn: habits = await conn.fetch("SELECT id,user_id,name,last_done,frequency,schedule_json FROM habits")
    now = now_moscow().date()
    for h in habits:
        schedule = h.get("schedule_json") or {}
        days_mask = schedule.get("days", list(range(7)) if h["frequency"]=="daily" else [])
        if now.weekday() in days_mask and h["last_done"] and h["last_done"] < now - timedelta(days=1):
            try: await bot.send_message(h["user_id"], f"🔁 '{h['name']}' — не забудь сегодня!")
            except: pass

async def task_reminder_check():
    async with db_pool.acquire() as conn:
        tasks = await conn.fetch("SELECT user_id,title,due_date FROM tasks WHERE status='pending' AND due_date IS NOT NULL AND due_date <= NOW() + INTERVAL '1 hour' AND due_date > NOW()")
    for t in tasks:
        try: await bot.send_message(t["user_id"], f"⏰ Скоро: {t['title']} ({t['due_date'].astimezone(MOSCOW_TZ).strftime('%H:%M')})")
        except: pass

async def calendar_reminder_check():
    async with db_pool.acquire() as conn:
        events = await conn.fetch("SELECT user_id, title, event_date FROM calendar_events WHERE event_date <= NOW() + INTERVAL '1 hour' AND event_date > NOW() - INTERVAL '1 hour'")
    for e in events:
        try: await bot.send_message(e["user_id"], f"📅 Скоро: {e['title']} ({e['event_date'].astimezone(MOSCOW_TZ).strftime('%H:%M')})")
        except: pass

# ======================
#  🔥 HEALTH CHECK / ЗАПУСК
# ======================
async def health_handler(request):
    status = {"status": "ok" if db_pool and bot.session else "starting", "bot": "AssistEmpat v4.9", "db": "connected" if db_pool else "connecting", "polling": "running" if dp and hasattr(dp, '_running') else "stopped", "timestamp": now_moscow().isoformat()}
    status_code = 200 if status["status"] == "ok" else 503
    return web.json_response(status, status=status_code, headers={"Content-Type": "application/json"})

async def start_health_server():
    app = web.Application()
    app.router.add_get('/health', health_handler)
    app.router.add_get('/', health_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    for attempt in range(3):
        try:
            site = web.TCPSite(runner, '0.0.0.0', HEALTH_PORT)
            await site.start()
            logging.info(f"🏥 Health server started on port {HEALTH_PORT}")
            return runner
        except OSError as e:
            if "Address already in use" in str(e): logging.warning(f"⚠️ Port {HEALTH_PORT} busy, retry {attempt+1}/3..."); await asyncio.sleep(1)
            else: raise
    raise RuntimeError(f"❌ Could not bind to port {HEALTH_PORT} after 3 attempts")

async def main():
    logging.info(f"🚀 Starting AssistEmpat v4.9 (port={HEALTH_PORT}, TZ=Moscow)")
    required_vars = ["BOT_TOKEN", "DATABASE_URL"]
    missing = [v for v in required_vars if not os.getenv(v)]
    if missing:
        logging.error(f"❌ Missing required env vars: {missing}")
        return
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    def handle_signal(): logging.info("🛑 Signal received"); stop_event.set()
    for sig in (signal.SIGTERM, signal.SIGINT): loop.add_signal_handler(sig, handle_signal)
    health_runner = None
    try: health_runner = await start_health_server()
    except Exception as e: logging.error(f"❌ Health server failed: {e}"); return
    try:
        await init_db()
        logging.info("✅ DB initialized")
    except Exception as e:
        logging.error(f"❌ DB init failed: {e}")
        await cleanup(health_runner)
        return
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
    logging.info("✅ AssistEmpat v4.9 ready — STARTING POLLING")
    polling_task = asyncio.create_task(dp.start_polling(bot))
    done, pending = await asyncio.wait([polling_task, asyncio.create_task(stop_event.wait())], return_when=asyncio.FIRST_COMPLETED)
    await cleanup(health_runner)
    for task in pending:
        task.cancel()
        try: await task
        except asyncio.CancelledError: pass

async def cleanup(health_runner=None):
    logging.info("👋 Cleaning up...")
    if scheduler.running:
        try: scheduler.shutdown(wait=False)
        except: pass
    if db_pool:
        try: await db_pool.close()
        except: pass
    if bot.session:
        try: await bot.session.close()
        except: pass
    if health_runner:
        try: await health_runner.cleanup()
        except: pass
    logging.info("✅ Cleanup complete")

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: logging.info("👋 Stopped by user")
    except Exception as e: logging.error(f"💥 Fatal error: {e}")