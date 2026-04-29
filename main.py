import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)

bot = Bot(token=os.getenv("BOT_TOKEN"))
dp = Dispatcher()


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

async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())