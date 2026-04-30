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

# ================= CONFIG =================

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

ADMIN_ID = 8590402564

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

db = None

# ================= STATE =================

user_states = {}

# ================= KEYBOARDS =================

def style_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤝 Друг", callback_data="style:друг")],
        [InlineKeyboardButton(text="💬 Подруга", callback_data="style:подруга")],
        [InlineKeyboardButton(text="🧠 Советник", callback_data="style:советник")],
        [InlineKeyboardButton(text="📋 Секретарь", callback_data="style:секретарь")],
        [InlineKeyboardButton(text="🔥 Всё сразу", callback_data="style:all")]
    ])

def gender_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👨 Мужской", callback_data="gender:муж")],
        [InlineKeyboardButton(text="👩 Женский", callback_data="gender:жен")]
    ])

def delete_kb(item_id, typ):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"del:{typ}:{item_id}")]
    ])

# ================= UTILS =================

def fix_layout(text):
    layout = dict(zip(
        "qwertyuiop[]asdfghjkl;'zxcvbnm,.",
        "йцукенгшщзхъфывапролджэячсмитьбю"
    ))
    return "".join(layout.get(c, c) for c in text.lower())

def parse_time(text):
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
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            name TEXT,
            age INT,
            gender TEXT,
            style TEXT
        );
        """)

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

async def get_user(user_id):
    async with db.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM users WHERE user_id=$1", user_id)

# ================= REMINDER =================

async def reminder_worker(user_id, text, remind_time):
    wait = (remind_time - datetime.now()).total_seconds()
    if wait > 0:
        await asyncio.sleep(wait)
    await bot.send_message(user_id, f"⏰ Напоминание: {text}")

# ================= AI =================

def detect_mode(text):
    t = text.lower()

    psycho = ["обид", "чувств", "плохо", "ссора", "переживаю", "тревог", "груст"]
    health = ["болит", "температур", "кашель", "голова", "живот", "симптом"]

    if any(w in t for w in psycho):
        return "psycho"
    if any(w in t for w in health):
        return "doctor"
    return "normal"

def build_prompt(user, mode, text):
    base = f"Ты общаешься с пользователем по имени {user['name']}. Обращайся на ты."

    style = user["style"]

    if style == "друг":
        base += " Ты как близкий друг."
    elif style == "подруга":
        base += " Ты как тёплая подруга."
    elif style == "советник":
        base += " Ты как рациональный советник."
    elif style == "секретарь":
        base += " Ты краткий и по делу."
    else:
        base += " Комбинируй стиль общения."

    if mode == "psycho":
        base += " Максимальная эмпатия, поддержка, мягкость."
    elif mode == "doctor":
        base += " Отвечай как врач: чётко, спокойно, без назначения лекарств."
    else:
        base += " Обычное дружелюбное общение."

    return base + f"\n\nСообщение: {text}"

def ask_openrouter(prompt):
    try:
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_KEY}"},
            json={
                "model": "mistralai/mixtral-8x7b-instruct",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.8
            },
            timeout=15
        )
        return r.json()["choices"][0]["message"]["content"]
    except:
        return None

# ================= REGISTRATION =================

@dp.message(F.text == "/start")
async def start(message: types.Message):
    user = await get_user(message.from_user.id)

    if user:
        await message.answer(f"С возвращением, {user['name']} 👋")
        return

    user_states[message.from_user.id] = {"step": "name"}
    await message.answer("Как тебя зовут?")

@dp.callback_query(F.data.startswith("gender:"))
async def gender_select(cb: types.CallbackQuery):
    user_states[cb.from_user.id]["gender"] = cb.data.split(":")[1]
    user_states[cb.from_user.id]["step"] = "age"
    await cb.message.answer("Сколько тебе лет?")
    await cb.answer()

@dp.callback_query(F.data.startswith("style:"))
async def style_select(cb: types.CallbackQuery):
    data = user_states[cb.from_user.id]
    style = cb.data.split(":")[1]

    async with db.acquire() as conn:
        await conn.execute(
            "INSERT INTO users(user_id,name,age,gender,style) VALUES($1,$2,$3,$4,$5)",
            cb.from_user.id,
            data["name"],
            data["age"],
            data["gender"],
            style
        )

    user_states.pop(cb.from_user.id)

    await cb.message.answer("✅ Готово, давай общаться 😎")
    await cb.answer()

# ================= MAIN HANDLER =================

@dp.message()
async def handle(message: types.Message):
    text = message.text or ""
    user_id = message.from_user.id

    # регистрация шаги
    if user_id in user_states:
        state = user_states[user_id]

        if state["step"] == "name":
            state["name"] = text
            state["step"] = "gender"
            await message.answer("Выбери пол:", reply_markup=gender_kb())
            return

        if state["step"] == "age":
            try:
                state["age"] = int(text)
                state["step"] = "style"
                await message.answer("Выбери стиль общения:", reply_markup=style_kb())
            except:
                await message.answer("Напиши возраст числом")
            return

    user = await get_user(user_id)

    if not user:
        await message.answer("Напиши /start")
        return

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

        await message.answer("Ок, напомню 👍", reply_markup=delete_kb(rec["id"], "reminder"))
        return

    if "покажи напомин" in lower:
        async with db.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM reminders WHERE user_id=$1", user_id)

        if not rows:
            await message.answer("Пусто")
            return

        for r in rows:
            await message.answer(f"{r['text']}", reply_markup=delete_kb(r["id"], "reminder"))
        return

    # ================= ЗАМЕТКИ =================

    if "запомни" in lower or "запиши" in lower:
        cat = "обычное"
        if "куп" in lower:
            cat = "покупки"
        if "наблюд" in lower:
            cat = "наблюдения"

        async with db.acquire() as conn:
            rec = await conn.fetchrow(
                "INSERT INTO notes(user_id,text,category) VALUES($1,$2,$3) RETURNING id",
                user_id, text, cat
            )

        await message.answer(f"Сохранил ({cat})", reply_markup=delete_kb(rec["id"], "note"))
        return

    if "покажи заметки" in lower:
        async with db.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM notes WHERE user_id=$1", user_id)

        if not rows:
            await message.answer("Нет заметок")
            return

        for r in rows:
            await message.answer(f"[{r['category']}] {r['text']}", reply_markup=delete_kb(r["id"], "note"))
        return

    # ================= AI =================

    mode = detect_mode(text)
    prompt = build_prompt(user, mode, text)

    reply = ask_openrouter(prompt) or "Не совсем понял, уточни 🙏"
    await message.answer(reply)

# ================= DELETE =================

@dp.callback_query(F.data.startswith("del:"))
async def delete(cb: types.CallbackQuery):
    _, typ, item_id = cb.data.split(":")
    item_id = int(item_id)

    async with db.acquire() as conn:
        if typ == "note":
            await conn.execute("DELETE FROM notes WHERE id=$1", item_id)
        if typ == "reminder":
            await conn.execute("DELETE FROM reminders WHERE id=$1", item_id)

    await cb.message.edit_text("Удалено")
    await cb.answer()

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