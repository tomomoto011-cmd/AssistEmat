import os
import asyncio
from aiogram import Bot, Dispatcher, types
from aiohttp import web

# --- переменные ---
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден!")

# --- инициализация ---
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- хендлеры ---
@dp.message()
async def echo(message: types.Message):
    await message.answer("Я жив 😄")

# --- healthcheck для Railway ---
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

# --- запуск ---
async def main():
    print("🚀 Бот запускается...")
    
    # запускаем HTTP (чтобы Railway не убивал контейнер)
    await start_health_server()
    
    print("🌐 Healthcheck сервер запущен")
    
    # запускаем Telegram polling
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())