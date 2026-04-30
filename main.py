import os
import asyncio
import logging
import re
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

# ================= MEMORY =================

user_memory = {}
user_states = {}
notes_db = {}

# ================= SYSTEM PROMPT =================

SYSTEM_PROMPT = """
Ты — живой, дружелюбный AI-ассистент.

Правила:
- Всегда отвечай на русском языке
- Пиши естественно
- Добавляй лёгкую живость
- Поддерживай диалог

Если не понял:
→ "Не совсем тебя понял, уточни пожалуйста 🙏"
"""

# ================= UTILS =================

def is_russian(text):
    if not text:
        return False
    return any("а" <= c <= "я" or "А" <= c <= "Я" for c in text)


def safe_get_content(data):
    try:
        return data["choices"][0]["message"]["content"]
    except Exception:
        print("❌ Неправильный формат ответа:", data)
        return None


# ================= TIME PARSER =================

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


# ================= REMINDER =================

async def reminder_worker(user_id, text, remind_time):
    wait = (remind_time - datetime.now()).total_seconds()

    if wait > 0:
        await asyncio.sleep(wait)

    try:
        await bot.send_message(user_id, f"⏰ Напоминание: {text}")
    except:
        pass


# ================= OPENROUTER =================

def ask_openrouter(user_id, message):
    print("🧠 OPENROUTER")

    history = user_memory.get(user_id, [])

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
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
                "temperature": 0.85
            },
            timeout=15
        )

        if response.status_code != 200:
            print("❌ OpenRouter:", response.status_code, response.text)
            return None

        data = response.json()
        reply = safe_get_content(data)

        if not reply:
            return None

        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": reply})
        user_memory[user_id] = history[-10:]

        return reply

    except Exception as e:
        print("❌ OpenRouter ERROR:", e)
        return None


# ================= HANDLER =================

@dp.message()
async def handle_message(message: types.Message):
    text = message.text
    user_id = message.from_user.id

    if not text:
        await message.answer("Не совсем тебя понял, уточни 🙏")
        return

    # ================= НАПОМИНАНИЯ =================

    if "напомни" in text.lower():
        remind_time = parse_time(text)

        if not remind_time:
            user_states[user_id] = {"mode": "await_time", "text": text}
            await message.answer("Когда напомнить?")
            return

        asyncio.create_task(reminder_worker(user_id, text, remind_time))
        await message.answer("✅ Напоминание поставил")
        return

    # === ожидание времени ===

    if user_states.get(user_id, {}).get("mode") == "await_time":
        remind_time = parse_time(text)

        if not remind_time:
            await message.answer("Напиши время так: 'через 10 минут' или 'через 1 час'")
            return

        original_text = user_states[user_id]["text"]

        asyncio.create_task(reminder_worker(user_id, original_text, remind_time))

        user_states.pop(user_id)

        await message.answer("✅ Напоминание поставил")
        return

    # ================= ЗАМЕТКИ =================

    if "запомни" in text.lower() or "запиши" in text.lower():
        notes = notes_db.get(user_id, [])
        notes.append(text)
        notes_db[user_id] = notes

        await message.answer("📝 Записал")
        return

    if "покажи заметки" in text.lower():
        notes = notes_db.get(user_id, [])

        if not notes:
            await message.answer("Пока пусто")
            return

        await message.answer("\n".join(notes))
        return

    # ================= AI =================

    if not is_russian(text):
        text = f"Ответь на русском: {text}"

    reply = ask_openrouter(user_id, text)

    if not reply:
        reply = "Не совсем тебя понял, уточни 🙏"

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

    print("🌐 Сервер здоровья запущен")


# ================= MAIN =================

async def main():
    print("🚀 БОТ ЗАПУЩЕН")

    # 🛑 анти-дубль Railway
    run_uid = os.getenv("RAILWAY_RUN_UID")
    deploy_id = os.getenv("RAILWAY_DEPLOYMENT_ID")

    if run_uid and deploy_id and run_uid != deploy_id:
        print("⛔ Второй инстанс — выходим")
        return

    await start_health_server()

    await bot.delete_webhook(drop_pending_updates=True)
    await asyncio.sleep(2)

    try:
        await bot.send_message(ADMIN_ID, "✅ Бот перезапущен")
    except:
        pass

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())