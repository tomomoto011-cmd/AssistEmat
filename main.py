import os
import asyncio
import logging
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

# ================= SYSTEM PROMPT =================

SYSTEM_PROMPT = """
Ты — живой AI-ассистент.

Сам выбирай стиль:
- если человек жалуется → эмпатия
- если вопрос про здоровье → кратко и по делу
- если обычный диалог → дружелюбно

Отвечай на русском.
"""

# ================= UTILS =================

def is_russian(text):
    if not text:
        return True
    return any("а" <= c <= "я" or "А" <= c <= "Я" for c in text)

def safe_get_content(data):
    try:
        return data["choices"][0]["message"]["content"]
    except Exception:
        logging.error(f"❌ Неправильный ответ: {data}")
        return None

# ================= OPENROUTER =================

def ask_openrouter(user_id, message):
    logging.info("🧠 OPENROUTER")

    history = user_memory.get(user_id, [])

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += history[-20:]
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
                "temperature": 0.8
            },
            timeout=20
        )

        if response.status_code != 200:
            logging.error(f"❌ OpenRouter HTTP: {response.status_code} {response.text}")
            return None

        data = response.json()
        reply = safe_get_content(data)

        if not reply:
            return None

        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": reply})
        user_memory[user_id] = history[-20:]

        return reply

    except Exception as e:
        logging.error(f"❌ OpenRouter error: {e}")
        return None

# ================= HANDLER =================

@dp.message()
async def handle_message(message: types.Message):
    text = message.text or ""
    user_id = message.from_user.id

    if not is_russian(text):
        text = f"Ответь на русском: {text}"

    reply = ask_openrouter(user_id, text)

    if not reply:
        reply = "❌ AI временно недоступен"

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

    logging.info(f"🌐 Health server on {port}")

# ================= MAIN =================

async def main():
    logging.info("🚀 БОТ ЗАПУЩЕН")

    # 🛑 анти-дубль Railway
    run_uid = os.getenv("RAILWAY_RUN_UID")
    deploy_id = os.getenv("RAILWAY_DEPLOYMENT_ID")

    if run_uid and deploy_id and run_uid != deploy_id:
        logging.warning("⛔ Второй инстанс — выходим")
        return

    await start_health_server()

    await bot.delete_webhook(drop_pending_updates=True)
    await asyncio.sleep(2)

    try:
        await bot.send_message(ADMIN_ID, "✅ Бот перезапущен")
    except:
        pass

    # 🔥 ГЛАВНОЕ — не даём процессу умереть
    polling_task = asyncio.create_task(dp.start_polling(bot))

    await polling_task

# ================= ENTRY =================

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("❌ Бот остановлен")