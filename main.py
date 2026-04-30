import os
import asyncio
import logging
import re
from datetime import datetime, timedelta

from aiohttp import web
import requests
import asyncpg

from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart

# ================= CONFIG =================

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

ADMIN_ID = 8590402564

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

db = None

# ================= KEYBOARD =================

def delete_kb(item_id, item_type):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"del:{item_type}:{item_id}")]
    ])

# ================= LAYOUT FIX =================

def fix_layout(text):
    layout = dict(zip(
        "qwertyuiop[]asdfghjkl;'zxcvbnm,.",
        "йцукенгшщзхъфывапролджэячсмитьбю"
    ))

    fixed = "".join(layout.get(c, c) for c in text.lower())
    return fixed

# ================= TIME =================

def parse_time(text):
    text = text.lower()

    try:
        if "через" in text:
            num = int(re.findall(r"\d+", text)[0])

            if "минут" in text:
                return datetime.now() + timedelta(minutes=num)

            if "час" in text:
                return datetime.now() + timedelta(hours=num)

        if "завтра" in text:
            return datetime.now() + timedelta(days=1)

    except:
        return None

    return None

# ================= DB =================

async def init_db():
    global db
    db = await asyncpg.create_pool(DATABASE_URL)

    async with db.acquire() as conn:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            text TEXT,
            category TEXT
        );
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            text TEXT,
            remind_time TIMESTAMP
        );
        """)

# ================= REMINDER =================

async def reminder_worker(user_id, text, remind_time):
    wait = (remind_time - datetime.now()).total_seconds()

    if wait > 0:
        await asyncio.sleep(wait)

    await bot.send_message(user_id, f"⏰ Напоминание: {text}")

# ================= AI =================

def ask_openrouter(message):
    try:
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_KEY}"},
            json={
                "model": "mistralai/mixtral-8x7b-instruct",
                "messages": [{"role": "user", "content": message}]
            },
            timeout=15
        )
        return r.json()["choices"][0]["message"]["content"]
    except:
        return None

# ================= HANDLER =================

@dp.message()
async def handle(message: types.Message):
    text = message.text or ""
    user_id = message.from_user.id

    text = fix_layout(text)
    lower = text.lower()

    # ================= НАПОМИНАНИЯ =================

    if "напомни" in lower:
        t = parse_time(text)

        if not t:
            await message.answer("Когда напомнить?")
            return

        async with db.acquire() as conn:
            rec = await conn.fetchrow(
                "INSERT INTO reminders(user_id,text,remind_time) VALUES($1,$2,$3) RETURNING id",
                user_id, text, t
            )

        asyncio.create_task(reminder_worker(user_id, text, t))

        await message.answer("✅ Напоминание создано", reply_markup=delete_kb(rec["id"], "reminder"))
        return

    if "покажи напомин" in lower:
        async with db.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM reminders WHERE user_id=$1", user_id)

        if not rows:
            await message.answer("📭 Нет напоминаний")
            return

        for r in rows:
            await message.answer(
                f"{r['text']} — {r['remind_time']}",
                reply_markup=delete_kb(r["id"], "reminder")
            )
        return

    # ================= ЗАМЕТКИ =================

    if "запомни" in lower or "запиши" in lower:

        category = "обычное"
        if "куп" in lower:
            category = "покупки"
        if "наблюд" in lower:
            category = "наблюдения"

        async with db.acquire() as conn:
            rec = await conn.fetchrow(
                "INSERT INTO notes(user_id,text,category) VALUES($1,$2,$3) RETURNING id",
                user_id, text, category
            )

        await message.answer(f"📝 Сохранил ({category})", reply_markup=delete_kb(rec["id"], "note"))
        return

    if "покажи заметки" in lower:
        async with db.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM notes WHERE user_id=$1", user_id)

        if not rows:
            await message.answer("📭 Нет заметок")
            return

        for r in rows:
            await message.answer(
                f"[{r['category']}] {r['text']}",
                reply_markup=delete_kb(r["id"], "note")
            )
        return

    # ================= AI =================

    reply = ask_openrouter(text) or "Не совсем понял, уточни 🙏"
    await message.answer(reply)

# ================= CALLBACK =================

@dp.callback_query(F.data.startswith("del:"))
async def delete_item(callback: types.CallbackQuery):
    _, typ, item_id = callback.data.split(":")
    item_id = int(item_id)

    async with db.acquire() as conn:
        if typ == "note":
            await conn.execute("DELETE FROM notes WHERE id=$1", item_id)
        if typ == "reminder":
            await conn.execute("DELETE FROM reminders WHERE id=$1", item_id)

    await callback.message.edit_text("🗑 Удалено")
    await callback.answer()

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
    print("🚀 БОТ ЗАПУЩЕН")

    run_uid = os.getenv("RAILWAY_RUN_UID")
    deploy_id = os.getenv("RAILWAY_DEPLOYMENT_ID")

    if run_uid and deploy_id and run_uid != deploy_id:
        return

    await init_db()
    await start_health()

    await bot.delete_webhook(drop_pending_updates=True)
    await asyncio.sleep(2)

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())import os
import asyncio
import logging
import re
from datetime import datetime, timedelta

from aiohttp import web
import requests
import asyncpg

from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart

# ================= CONFIG =================

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

ADMIN_ID = 8590402564

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

db = None

# ================= KEYBOARD =================

def delete_kb(item_id, item_type):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"del:{item_type}:{item_id}")]
    ])

# ================= LAYOUT FIX =================

def fix_layout(text):
    layout = dict(zip(
        "qwertyuiop[]asdfghjkl;'zxcvbnm,.",
        "йцукенгшщзхъфывапролджэячсмитьбю"
    ))

    fixed = "".join(layout.get(c, c) for c in text.lower())
    return fixed

# ================= TIME =================

def parse_time(text):
    text = text.lower()

    try:
        if "через" in text:
            num = int(re.findall(r"\d+", text)[0])

            if "минут" in text:
                return datetime.now() + timedelta(minutes=num)

            if "час" in text:
                return datetime.now() + timedelta(hours=num)

        if "завтра" in text:
            return datetime.now() + timedelta(days=1)

    except:
        return None

    return None

# ================= DB =================

async def init_db():
    global db
    db = await asyncpg.create_pool(DATABASE_URL)

    async with db.acquire() as conn:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            text TEXT,
            category TEXT
        );
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            text TEXT,
            remind_time TIMESTAMP
        );
        """)

# ================= REMINDER =================

async def reminder_worker(user_id, text, remind_time):
    wait = (remind_time - datetime.now()).total_seconds()

    if wait > 0:
        await asyncio.sleep(wait)

    await bot.send_message(user_id, f"⏰ Напоминание: {text}")

# ================= AI =================

def ask_openrouter(message):
    try:
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_KEY}"},
            json={
                "model": "mistralai/mixtral-8x7b-instruct",
                "messages": [{"role": "user", "content": message}]
            },
            timeout=15
        )
        return r.json()["choices"][0]["message"]["content"]
    except:
        return None

# ================= HANDLER =================

@dp.message()
async def handle(message: types.Message):
    text = message.text or ""
    user_id = message.from_user.id

    text = fix_layout(text)
    lower = text.lower()

    # ================= НАПОМИНАНИЯ =================

    if "напомни" in lower:
        t = parse_time(text)

        if not t:
            await message.answer("Когда напомнить?")
            return

        async with db.acquire() as conn:
            rec = await conn.fetchrow(
                "INSERT INTO reminders(user_id,text,remind_time) VALUES($1,$2,$3) RETURNING id",
                user_id, text, t
            )

        asyncio.create_task(reminder_worker(user_id, text, t))

        await message.answer("✅ Напоминание создано", reply_markup=delete_kb(rec["id"], "reminder"))
        return

    if "покажи напомин" in lower:
        async with db.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM reminders WHERE user_id=$1", user_id)

        if not rows:
            await message.answer("📭 Нет напоминаний")
            return

        for r in rows:
            await message.answer(
                f"{r['text']} — {r['remind_time']}",
                reply_markup=delete_kb(r["id"], "reminder")
            )
        return

    # ================= ЗАМЕТКИ =================

    if "запомни" in lower or "запиши" in lower:

        category = "обычное"
        if "куп" in lower:
            category = "покупки"
        if "наблюд" in lower:
            category = "наблюдения"

        async with db.acquire() as conn:
            rec = await conn.fetchrow(
                "INSERT INTO notes(user_id,text,category) VALUES($1,$2,$3) RETURNING id",
                user_id, text, category
            )

        await message.answer(f"📝 Сохранил ({category})", reply_markup=delete_kb(rec["id"], "note"))
        return

    if "покажи заметки" in lower:
        async with db.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM notes WHERE user_id=$1", user_id)

        if not rows:
            await message.answer("📭 Нет заметок")
            return

        for r in rows:
            await message.answer(
                f"[{r['category']}] {r['text']}",
                reply_markup=delete_kb(r["id"], "note")
            )
        return

    # ================= AI =================

    reply = ask_openrouter(text) or "Не совсем понял, уточни 🙏"
    await message.answer(reply)

# ================= CALLBACK =================

@dp.callback_query(F.data.startswith("del:"))
async def delete_item(callback: types.CallbackQuery):
    _, typ, item_id = callback.data.split(":")
    item_id = int(item_id)

    async with db.acquire() as conn:
        if typ == "note":
            await conn.execute("DELETE FROM notes WHERE id=$1", item_id)
        if typ == "reminder":
            await conn.execute("DELETE FROM reminders WHERE id=$1", item_id)

    await callback.message.edit_text("🗑 Удалено")
    await callback.answer()

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
    print("🚀 БОТ ЗАПУЩЕН")

    run_uid = os.getenv("RAILWAY_RUN_UID")
    deploy_id = os.getenv("RAILWAY_DEPLOYMENT_ID")

    if run_uid and deploy_id and run_uid != deploy_id:
        return

    await init_db()
    await start_health()

    await bot.delete_webhook(drop_pending_updates=True)
    await asyncio.sleep(2)

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())import os
import asyncio
import logging
import re
from datetime import datetime, timedelta

from aiohttp import web
import requests
import asyncpg

from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart

# ================= CONFIG =================

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

ADMIN_ID = 8590402564

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

db = None

# ================= KEYBOARD =================

def delete_kb(item_id, item_type):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"del:{item_type}:{item_id}")]
    ])

# ================= LAYOUT FIX =================

def fix_layout(text):
    layout = dict(zip(
        "qwertyuiop[]asdfghjkl;'zxcvbnm,.",
        "йцукенгшщзхъфывапролджэячсмитьбю"
    ))

    fixed = "".join(layout.get(c, c) for c in text.lower())
    return fixed

# ================= TIME =================

def parse_time(text):
    text = text.lower()

    try:
        if "через" in text:
            num = int(re.findall(r"\d+", text)[0])

            if "минут" in text:
                return datetime.now() + timedelta(minutes=num)

            if "час" in text:
                return datetime.now() + timedelta(hours=num)

        if "завтра" in text:
            return datetime.now() + timedelta(days=1)

    except:
        return None

    return None

# ================= DB =================

async def init_db():
    global db
    db = await asyncpg.create_pool(DATABASE_URL)

    async with db.acquire() as conn:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            text TEXT,
            category TEXT
        );
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            text TEXT,
            remind_time TIMESTAMP
        );
        """)

# ================= REMINDER =================

async def reminder_worker(user_id, text, remind_time):
    wait = (remind_time - datetime.now()).total_seconds()

    if wait > 0:
        await asyncio.sleep(wait)

    await bot.send_message(user_id, f"⏰ Напоминание: {text}")

# ================= AI =================

def ask_openrouter(message):
    try:
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_KEY}"},
            json={
                "model": "mistralai/mixtral-8x7b-instruct",
                "messages": [{"role": "user", "content": message}]
            },
            timeout=15
        )
        return r.json()["choices"][0]["message"]["content"]
    except:
        return None

# ================= HANDLER =================

@dp.message()
async def handle(message: types.Message):
    text = message.text or ""
    user_id = message.from_user.id

    text = fix_layout(text)
    lower = text.lower()

    # ================= НАПОМИНАНИЯ =================

    if "напомни" in lower:
        t = parse_time(text)

        if not t:
            await message.answer("Когда напомнить?")
            return

        async with db.acquire() as conn:
            rec = await conn.fetchrow(
                "INSERT INTO reminders(user_id,text,remind_time) VALUES($1,$2,$3) RETURNING id",
                user_id, text, t
            )

        asyncio.create_task(reminder_worker(user_id, text, t))

        await message.answer("✅ Напоминание создано", reply_markup=delete_kb(rec["id"], "reminder"))
        return

    if "покажи напомин" in lower:
        async with db.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM reminders WHERE user_id=$1", user_id)

        if not rows:
            await message.answer("📭 Нет напоминаний")
            return

        for r in rows:
            await message.answer(
                f"{r['text']} — {r['remind_time']}",
                reply_markup=delete_kb(r["id"], "reminder")
            )
        return

    # ================= ЗАМЕТКИ =================

    if "запомни" in lower or "запиши" in lower:

        category = "обычное"
        if "куп" in lower:
            category = "покупки"
        if "наблюд" in lower:
            category = "наблюдения"

        async with db.acquire() as conn:
            rec = await conn.fetchrow(
                "INSERT INTO notes(user_id,text,category) VALUES($1,$2,$3) RETURNING id",
                user_id, text, category
            )

        await message.answer(f"📝 Сохранил ({category})", reply_markup=delete_kb(rec["id"], "note"))
        return

    if "покажи заметки" in lower:
        async with db.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM notes WHERE user_id=$1", user_id)

        if not rows:
            await message.answer("📭 Нет заметок")
            return

        for r in rows:
            await message.answer(
                f"[{r['category']}] {r['text']}",
                reply_markup=delete_kb(r["id"], "note")
            )
        return

    # ================= AI =================

    reply = ask_openrouter(text) or "Не совсем понял, уточни 🙏"
    await message.answer(reply)

# ================= CALLBACK =================

@dp.callback_query(F.data.startswith("del:"))
async def delete_item(callback: types.CallbackQuery):
    _, typ, item_id = callback.data.split(":")
    item_id = int(item_id)

    async with db.acquire() as conn:
        if typ == "note":
            await conn.execute("DELETE FROM notes WHERE id=$1", item_id)
        if typ == "reminder":
            await conn.execute("DELETE FROM reminders WHERE id=$1", item_id)

    await callback.message.edit_text("🗑 Удалено")
    await callback.answer()

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
    print("🚀 БОТ ЗАПУЩЕН")

    run_uid = os.getenv("RAILWAY_RUN_UID")
    deploy_id = os.getenv("RAILWAY_DEPLOYMENT_ID")

    if run_uid and deploy_id and run_uid != deploy_id:
        return

    await init_db()
    await start_health()

    await bot.delete_webhook(drop_pending_updates=True)
    await asyncio.sleep(2)

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
import os
import asyncio
import logging
import re
from datetime import datetime, timedelta

from aiohttp import web
import requests
import asyncpg

from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart

# ================= CONFIG =================

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

ADMIN_ID = 8590402564

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

db = None

# ================= KEYBOARD =================

def delete_kb(item_id, item_type):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"del:{item_type}:{item_id}")]
    ])

# ================= LAYOUT FIX =================

def fix_layout(text):
    layout = dict(zip(
        "qwertyuiop[]asdfghjkl;'zxcvbnm,.",
        "йцукенгшщзхъфывапролджэячсмитьбю"
    ))

    fixed = "".join(layout.get(c, c) for c in text.lower())
    return fixed

# ================= TIME =================

def parse_time(text):
    text = text.lower()

    try:
        if "через" in text:
            num = int(re.findall(r"\d+", text)[0])

            if "минут" in text:
                return datetime.now() + timedelta(minutes=num)

            if "час" in text:
                return datetime.now() + timedelta(hours=num)

        if "завтра" in text:
            return datetime.now() + timedelta(days=1)

    except:
        return None

    return None

# ================= DB =================

async def init_db():
    global db
    db = await asyncpg.create_pool(DATABASE_URL)

    async with db.acquire() as conn:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            text TEXT,
            category TEXT
        );
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            text TEXT,
            remind_time TIMESTAMP
        );
        """)

# ================= REMINDER =================

async def reminder_worker(user_id, text, remind_time):
    wait = (remind_time - datetime.now()).total_seconds()

    if wait > 0:
        await asyncio.sleep(wait)

    await bot.send_message(user_id, f"⏰ Напоминание: {text}")

# ================= AI =================

def ask_openrouter(message):
    try:
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_KEY}"},
            json={
                "model": "mistralai/mixtral-8x7b-instruct",
                "messages": [{"role": "user", "content": message}]
            },
            timeout=15
        )
        return r.json()["choices"][0]["message"]["content"]
    except:
        return None

# ================= HANDLER =================

@dp.message()
async def handle(message: types.Message):
    text = message.text or ""
    user_id = message.from_user.id

    text = fix_layout(text)
    lower = text.lower()

    # ================= НАПОМИНАНИЯ =================

    if "напомни" in lower:
        t = parse_time(text)

        if not t:
            await message.answer("Когда напомнить?")
            return

        async with db.acquire() as conn:
            rec = await conn.fetchrow(
                "INSERT INTO reminders(user_id,text,remind_time) VALUES($1,$2,$3) RETURNING id",
                user_id, text, t
            )

        asyncio.create_task(reminder_worker(user_id, text, t))

        await message.answer("✅ Напоминание создано", reply_markup=delete_kb(rec["id"], "reminder"))
        return

    if "покажи напомин" in lower:
        async with db.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM reminders WHERE user_id=$1", user_id)

        if not rows:
            await message.answer("📭 Нет напоминаний")
            return

        for r in rows:
            await message.answer(
                f"{r['text']} — {r['remind_time']}",
                reply_markup=delete_kb(r["id"], "reminder")
            )
        return

    # ================= ЗАМЕТКИ =================

    if "запомни" in lower or "запиши" in lower:

        category = "обычное"
        if "куп" in lower:
            category = "покупки"
        if "наблюд" in lower:
            category = "наблюдения"

        async with db.acquire() as conn:
            rec = await conn.fetchrow(
                "INSERT INTO notes(user_id,text,category) VALUES($1,$2,$3) RETURNING id",
                user_id, text, category
            )

        await message.answer(f"📝 Сохранил ({category})", reply_markup=delete_kb(rec["id"], "note"))
        return

    if "покажи заметки" in lower:
        async with db.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM notes WHERE user_id=$1", user_id)

        if not rows:
            await message.answer("📭 Нет заметок")
            return

        for r in rows:
            await message.answer(
                f"[{r['category']}] {r['text']}",
                reply_markup=delete_kb(r["id"], "note")
            )
        return

    # ================= AI =================

    reply = ask_openrouter(text) or "Не совсем понял, уточни 🙏"
    await message.answer(reply)

# ================= CALLBACK =================

@dp.callback_query(F.data.startswith("del:"))
async def delete_item(callback: types.CallbackQuery):
    _, typ, item_id = callback.data.split(":")
    item_id = int(item_id)

    async with db.acquire() as conn:
        if typ == "note":
            await conn.execute("DELETE FROM notes WHERE id=$1", item_id)
        if typ == "reminder":
            await conn.execute("DELETE FROM reminders WHERE id=$1", item_id)

    await callback.message.edit_text("🗑 Удалено")
    await callback.answer()

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
    print("🚀 БОТ ЗАПУЩЕН")

    run_uid = os.getenv("RAILWAY_RUN_UID")
    deploy_id = os.getenv("RAILWAY_DEPLOYMENT_ID")

    if run_uid and deploy_id and run_uid != deploy_id:
        return

    await init_db()
    await start_health()

    await bot.delete_webhook(drop_pending_updates=True)
    await asyncio.sleep(2)

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())