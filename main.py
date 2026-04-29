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


@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "Привет. Я AssistEmpat 🤝\n"
        "Я рядом, чтобы помочь."
    )


@dp.message()
async def handler(message: Message):
    await message.answer("Я получил сообщение 👍")


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())