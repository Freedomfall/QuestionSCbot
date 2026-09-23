import asyncio
import os
import aiohttp
from urllib.parse import quote
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, URLInputFile
from aiogram.enums import ChatAction

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("ОШИБКА: Переменная BOT_TOKEN не найдена в Environment Variables!")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ----------------- ВЕБ-СЕРВЕР ДЛЯ FREE ТАРИФА RENDER -----------------
async def health_check(request):
    return web.Response(text="Bot is online 24/7!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Веб-сервер запущен на порту {port}")
# ---------------------------------------------------------------------

@dp.message(CommandStart())
async def start_cmd(message: Message):
    await message.answer(
        "👋 **Привет! Я бот для быстрого поиска музыки.**\n\n"
        "Отправь мне имя исполнителя или название песни (например: `Eminem Mockingbird` или `Self Control`), "
        "и я найду трек.",
        parse_mode="Markdown"
    )

async def search_deezer_music(query: str):
    """
    Поиск через официальный открытый Deezer API.
    Работает без ключей, не блокирует дата-центры, возвращает чистые метаданные и MP3.
    """
    encoded_query = quote(query)
    url = f"https://api.deezer.com/search?q={encoded_query}&limit=1"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results = data.get("data", [])
                    if results:
                        track = results[0]
                        title = track.get("title", "Трек")
                        artist_name = track.get("artist", {}).get("name", "Исполнитель")
                        preview_url = track.get("preview")
                        duration = int(track.get("duration", 0))

                        if preview_url:
                            return {
                                "title": title,
                                "artist": artist_name,
                                "url": preview_url,
                                "duration": duration
                            }
    except Exception as e:
        print(f"Deezer Search Error: {e}")

    return None

@dp.message(F.text)
async def handle_search(message: Message):
    query = message.text.strip()
    if len(query) < 2:
        await message.answer("Слишком короткий запрос для поиска.")
        return

    await message.bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.UPLOAD_VOICE)
    wait_msg = await message.answer(f"🔍 Ищу: <b>{query}</b>...", parse_mode="HTML")

    try:
        track = await search_deezer_music(query)

        if track:
            await wait_msg.edit_text("⚡ Трек найден, отправляю...")

            audio = URLInputFile(
                url=track["url"],
                filename=f"{track['artist']} - {track['title']}.mp3"
            )

            await message.answer_audio(
                audio=audio,
                title=track["title"][:60],
                performer=track["artist"][:40],
                duration=track["duration"] if track["duration"] > 0 else None,
                caption=f"🎵 <b>{track['artist']} - {track['title']}</b>\n\nБот готов искать следующий трек!",
                parse_mode="HTML"
            )
            await wait_msg.delete()
        else:
            await wait_msg.edit_text("😔 По этому запросу трек не найден. Попробуй написать точнее (например: артист + трек).")

    except Exception as e:
        print(f"Handler error: {e}")
        await wait_msg.edit_text("⚠️ Ошибка при отправке аудио. Попробуй еще раз.")

async def main():
    print("Запуск сервиса...")
    await start_web_server()
    print("Бот готов к приему сообщений!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
