import asyncio
import logging
import os
import ssl

import asyncpg
from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

db = None


# 🔌 Подключение к БД
async def connect_db():
    global db
    ssl_context = ssl.create_default_context()
    db = await asyncpg.create_pool(
        DATABASE_URL,
        ssl=ssl_context
    )
    print("✅ Подключено к БД")


# 👋 Старт
@dp.message(CommandStart())
async def start(message: Message):
    await message.answer("Привет. Я AssistEmpat 🤝")


# 💬 Обработка сообщений
@dp.message()
async def handler(message: Message):
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
        print("✅ Сохранено в БД")

    except Exception as e:
        print("❌ Ошибка БД:", e)

    await message.answer("Я получил сообщение 👍")


# 🚀 Запуск
async def main():
    await connect_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())