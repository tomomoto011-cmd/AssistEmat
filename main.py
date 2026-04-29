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
    try:
        ssl_context = ssl.create_default_context()
        db = await asyncpg.create_pool(
            DATABASE_URL,
            ssl=ssl_context
        )
        print("✅ Подключено к БД")
    except Exception as e:
        print("❌ Ошибка подключения к БД:", e)


# 📚 Получение последних сообщений
async def get_last_messages(user_id: int, limit: int = 5):
    global db
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


# 👋 Старт
@dp.message(CommandStart())
async def start(message: Message):
    await message.answer("Привет. Я AssistEmpat 🤝")


# 💬 Обработка сообщений с памятью
@dp.message()
async def handler(message: Message):
    global db

    if db is None:
        await message.answer("❌ БД не подключена")
        return

    try:
        # сохраняем сообщение
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

        # получаем историю
        history = await get_last_messages(message.from_user.id)

        print("📚 История:", history)

        # ответ с памятью
        await message.answer(
            "Я запомнил твои последние сообщения:\n\n" +
            "\n".join(history)
        )

    except Exception as e:
        print("❌ Ошибка:", e)
        await message.answer("Ошибка при работе с БД")


# 🚀 Запуск
async def main():
    await connect_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())