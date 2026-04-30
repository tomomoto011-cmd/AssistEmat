import os
import asyncio
import logging
from datetime import datetime, timedelta
from aiohttp import web
import requests

from aiogram import Bot, Dispatcher, types

# ================= CONFIG =================

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")

ADMIN_ID = 8590402564

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ================= STORAGE =================

user_memory = {}

notes = {}
reminders = {}

# ================= SYSTEM =================

BASE_SYSTEM = """
Ты — живой ассистент.

Всегда:
- отвечай на русском
- пиши естественно
- без "я как AI"

Если не понял:
→ "Не совсем тебя понял, уточни пожалуйста 🙏"
"""

PSYCHO_MODE = """
Ты эмпатичный психолог.
Максимально бережный, поддерживающий.
Помогаешь разобраться в чувствах.
"""

HEALTH_MODE = """
Ты спокойный врач.
Говоришь чётко и по делу.
НЕ назначаешь лекарства.
Даёшь безопасные рекомендации.
"""

# ================= UTILS =================

def is_russian(text):
    if not text:
        return False
    return any("а" <= c <= "я" or "А" <= c <= "Я" for c in text)

def safe_get(data):
    try:
        return data["choices"][0]["message"]["content"]
    except:
        return None

# ================= DETECT =================

def detect_intent(text):
    t = text.lower()

    if "напомни" in t:
        return "reminder"

    if "запомни" in t or "запиши" in t:
        return "note"

    if "покажи" in t and "напомин" in t:
        return "show_reminders"

    if "покажи" in t and "замет" in t:
        return "show_notes"

    if "удали" in t:
        return "delete"

    if any(w in t for w in ["поссор", "обид", "не понимаю его", "отношен"]):
        return "psycho"

    if any(w in t for w in ["болит", "температура", "симптом", "здоров"]):
        return "health"

    return "chat"

# ================= REMINDERS =================

async def reminder_worker():
    while True:
        now = datetime.now()

        for user_id in list(reminders.keys()):
            new_list = []
            for r in reminders[user_id]:
                if now >= r["time"]:
                    try:
                        await bot.send_message(user_id, f"⏰ Напоминание: {r['text']}")
                    except:
                        pass
                else:
                    new_list.append(r)

            reminders[user_id] = new_list

        await asyncio.sleep(30)

# ================= AI =================

def ask_ai(user_id, message, mode=None):
    system = BASE_SYSTEM

    if mode == "psycho":
        system += PSYCHO_MODE

    if mode == "health":
        system += HEALTH_MODE

    history = user_memory.get(user_id, [])

    messages = [{"role": "system", "content": system}]
    messages += history[-5:]
    messages.append({"role": "user", "content": message})

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "mistralai/mixtral-8x7b-instruct",
                "messages": messages,
                "temperature": 0.9 if mode == "psycho" else 0.7
            },
            timeout=15
        )

        if response.status_code != 200:
            print(response.text)
            return None

        data = response.json()
        reply = safe_get(data)

        if not reply:
            return None

        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": reply})
        user_memory[user_id] = history[-10:]

        return reply

    except Exception as e:
        print(e)
        return None

# ================= HANDLER =================

@dp.message()
async def handle_message(message: types.Message):
    text = message.text or ""
    user_id = message.from_user.id

    intent = detect_intent(text)

    # -------- НАПОМИНАНИЕ --------
    if intent == "reminder":
        time = datetime.now() + timedelta(minutes=1)

        reminders.setdefault(user_id, []).append({
            "text": text,
            "time": time
        })

        await message.answer("⏰ Ок, напомню через минуту (пока базово)")
        return

    # -------- ЗАМЕТКА --------
    if intent == "note":
        notes.setdefault(user_id, []).append(text)
        await message.answer("📝 Записал")
        return

    # -------- ПОКАЗ --------
    if intent == "show_notes":
        data = notes.get(user_id, [])
        if not data:
            await message.answer("📭 Нет заметок")
        else:
            await message.answer("\n".join(data))
        return

    if intent == "show_reminders":
        data = reminders.get(user_id, [])
        if not data:
            await message.answer("📭 Нет напоминаний")
        else:
            txt = "\n".join([r["text"] for r in data])
            await message.answer(txt)
        return

    # -------- AI --------

    mode = None
    if intent == "psycho":
        mode = "psycho"
    elif intent == "health":
        mode = "health"

    if not is_russian(text):
        text = f"Ответь на русском: {text}"

    reply = ask_ai(user_id, text, mode)

    if not reply:
        reply = "❌ Не удалось получить ответ"

    await message.answer(reply)

# ================= HEALTH =================

async def health(request):
    return web.Response(text="OK")

async def start_health_server():
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
        print("⛔ дубль")
        return

    await start_health_server()

    await bot.delete_webhook(drop_pending_updates=True)
    await asyncio.sleep(2)

    asyncio.create_task(reminder_worker())

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())