import asyncio
import os
import aiohttp
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

# ----------------- ВЕБ-СЕРВЕР ДЛЯ БЕСПЛАТНОГО RENDER -----------------
async def health_check(request):
    return web.Response(text="Bot is running alive 24/7!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Сервер слушает порт {port}")
# ---------------------------------------------------------------------

@dp.message(CommandStart())
async def start_cmd(message: Message):
    await message.answer(
        "👋 **Привет! Я бот для быстрого поиска музыки.**\n\n"
        "Напиши название песни или исполнителя (например: `Eminem Mockingbird` или `Self Control`), "
        "и я сразу пришлю аудиофайл!",
        parse_mode="Markdown"
    )

async def search_music_api(query: str):
    """
    Поиск через открытый музыкальный API (JioSaavn / открытые базы).
    Работает без блокировок дата-центров, отдает прямые ссылки на MP3.
    """
    url = f"https://saavn.dev/api/search/songs?query={query}&page=1&limit=1"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results = data.get("data", {}).get("results", [])
                    if results:
                        song = results[0]
                        title = song.get("name", "Трек")
                        # Очищаем спецсимволы в названии (например &quot;)
                        title = title.replace("&quot;", '"').replace("&amp;", "&")
                        
                        artists = song.get("artists", {}).get("primary", [])
                        artist_name = ", ".join([a.get("name") for a in artists]) if artists else "Исполнитель"
                        duration = int(song.get("duration", 0))

                        # Получаем прямую ссылку на скачивание MP3 наилучшего качества (320kbps или 160kbps)
                        download_urls = song.get("downloadUrl", [])
                        audio_url = None
                        if download_urls:
                            # Берем самое высокое качество из доступных (последнее в списке)
                            audio_url = download_urls[-1].get("url")

                        if audio_url:
                            return {
                                "title": title,
                                "artist": artist_name,
                                "url": audio_url,
                                "duration": duration
                            }
    except Exception as e:
        print(f"API Search Error: {e}")
    
    return None

@dp.message(F.text)
async def handle_search(message: Message):
    query = message.text.strip()
    if len(query) < 2:
        await message.answer("Слишком короткий запрос.")
        return

    await message.bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.UPLOAD_VOICE)
    wait_msg = await message.answer(f"🔍 Ищу: <b>{query}</b>...", parse_mode="HTML")

    try:
        track = await search_music_api(query)

        if track:
            await wait_msg.edit_text("⚡ Трек найден, отправляю...")

            # Отправка трека напрямую по URL через серверы Telegram без расхода диска хостинга
            audio = URLInputFile(
                url=track["url"],
                filename=f"{track['artist']} - {track['title']}.mp3"
            )

            await message.answer_audio(
                audio=audio,
                title=track["title"][:60],
                performer=track["artist"][:40],
                duration=track["duration"] if track["duration"] > 0 else None,
                caption=f"🎵 <b>{track['artist']} - {track['title']}</b>",
                parse_mode="HTML"
            )
            await wait_msg.delete()
        else:
            await wait_msg.edit_text("😔 По этому запросу ничего не найдено. Попробуй уточнить название.")

    except Exception as e:
        print(f"Handler error: {e}")
        await wait_msg.edit_text("⚠️ Ошибка отправки трека. Попробуй еще раз.")

async def main():
    print("Запуск сервиса...")
    await start_web_server()
    print("Бот готов к приему сообщений!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
