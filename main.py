import asyncio
import logging
import os
import ssl

import asyncpg
import aiohttp

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

db = None


# 🔌 БД
async def connect_db():
    global db
    try:
        ssl_context = ssl.create_default_context()
        db = await asyncpg.create_pool(
            DATABASE_URL,
            ssl=ssl_context
        )
        print("✅ Подключено к БД")
    except Exception as e:
        print("❌ Ошибка подключения к БД:", e)


# 📚 история
async def get_last_messages(user_id: int, limit: int = 5):
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT text FROM messages
            WHERE user_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            user_id,
            limit
        )
    return [r["text"] for r in rows]


# 🤖 OpenAI
async def ask_ai(history: list[str]) -> str:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "gpt-4.1-mini",
                    "messages": [
                        {
                            "role": "system",
                            "content": "Ты тёплый, эмпатичный помощник. Поддерживай человека, говори просто."
                        },
                        {
                            "role": "user",
                            "content": "\n".join(history)
                        }
                    ]
                }
            ) as resp:
                data = await resp.json()

                print("🧠 AI raw:", data)

                return data["choices"][0]["message"]["content"]

    except Exception as e:
        print("❌ Ошибка AI:", e)
        return "Я рядом. Попробуй сказать ещё раз."


# 👋 старт
@dp.message(CommandStart())
async def start(message: Message):
    await message.answer("Привет. Я AssistEmpat 🤝")


# 💬 обработка
@dp.message()
async def handler(message: Message):
    if db is None:
        await message.answer("❌ БД не подключена")
        return

    try:
        async with db.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO messages(user_id, text)
                VALUES($1, $2)
                """,
                message.from_user.id,
                message.text
            )

        history = await get_last_messages(message.from_user.id)

        ai_response = await ask_ai(history)

        await message.answer(ai_response)

    except Exception as e:
        print("❌ Ошибка:", e)
        await message.answer("Ошибка системы")


# 🚀 запуск
async def main():
    await connect_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())