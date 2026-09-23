import asyncio
import os
import aiohttp
from urllib.parse import quote
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, URLInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ChatAction, ParseMode

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("ОШИБКА: BOT_TOKEN не найден в Environment Variables!")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Кэш треков в оперативной памяти бота: {track_id: track_info}
SEARCH_CACHE = {}

# ----------------- ВЕБ-СЕРВЕР ДЛЯ FREE RENDER -----------------
async def health_check(request):
    return web.Response(text="Bot Engine 24/7 Online!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Сервер слушает порт {port}")
# -------------------------------------------------------------

def format_time(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    return f"{m:02d}:{s:02d}"

@dp.message(CommandStart())
async def start_cmd(message: Message):
    await message.answer(
        "🎧 <b>Добро пожаловать в Music Hunter!</b>\n\n"
        "Я ищу и отправляю <b>полные версии треков</b> от начала до конца.\n\n"
        "Напиши название песни или имя артиста (например: <code>Laura Branigan Self Control</code> или <code>Eminem Mockingbird</code>).",
        parse_mode=ParseMode.HTML
    )

async def search_full_audio_api(query: str):
    """
    Поиск полных MP3-файлов через открытый аудио-шлюз.
    Возвращает прямые ссылки на полные дорожки (без 30-секундных ограничений).
    """
    encoded_query = quote(query)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    # 1. Основной источник: открытый каталог аудиозаписей с полными треками
    api_url = f"https://api.vkmusic.bot.su/search?q={encoded_query}&limit=5"
    
    results = []
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(api_url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    items = data if isinstance(data, list) else data.get("data", [])
                    for idx, item in enumerate(items[:5]):
                        audio_url = item.get("url") or item.get("audio") or item.get("download_url")
                        if not audio_url:
                            continue
                        
                        duration = int(item.get("duration", 210))
                        # Отсекаем превью короче 60 секунд
                        if duration > 0 and duration < 50:
                            continue

                        results.append({
                            "id": f"vk_{idx}_{hash(audio_url) % 100000}",
                            "title": item.get("title", "Трек"),
                            "artist": item.get("artist", "Исполнитель"),
                            "duration": duration,
                            "url": audio_url
                        })
                    if results:
                        return results
    except Exception as e:
        print(f"Primary API Error: {e}")

    # 2. Резервный источник полных MP3 (Hitmo / Zaycev open proxy)
    backup_url = f"https://api-music.smoothtrack.workers.dev/search?q={encoded_query}"
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(backup_url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for idx, item in enumerate(data.get("tracks", [])[:5]):
                        url = item.get("url")
                        if url:
                            results.append({
                                "id": f"bk_{idx}_{hash(url) % 100000}",
                                "title": item.get("title", "Трек"),
                                "artist": item.get("artist", "Исполнитель"),
                                "duration": int(item.get("duration", 200)),
                                "url": url
                            })
                    if results:
                        return results
    except Exception as e:
        print(f"Backup API Error: {e}")

    return []

@dp.message(F.text)
async def handle_search(message: Message):
    query = message.text.strip()
    if len(query) < 2:
        await message.answer("⚠️ Слишком короткий запрос.")
        return

    await message.bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
    status_msg = await message.answer(f"🔎 <i>Ищу полную версию:</i> <b>{query}</b>...", parse_mode=ParseMode.HTML)

    tracks = await search_full_audio_api(query)

    if not tracks:
        await status_msg.edit_text(
            "😔 <b>Ничего не найдено.</b>\nПопробуй написать имя исполнителя и песню без лишних символов.",
            parse_mode=ParseMode.HTML
        )
        return

    text_content = [
        f"🎯 <b>Результаты поиска:</b> <i>«{query}»</i>\n",
        "━━━━━━━━━━━━━━━━━━"
    ]

    keyboard_rows = []
    for idx, track in enumerate(tracks, start=1):
        SEARCH_CACHE[track["id"]] = track
        dur_str = format_time(track["duration"]) if track["duration"] else "03:45"

        text_content.append(f"<b>{idx}.</b> 🎵 <b>{track['title']}</b>")
        text_content.append(f"    👤 {track['artist']}  ⏱ <code>{dur_str}</code>\n")

        keyboard_rows.append([
            InlineKeyboardButton(
                text=f"▶️ Скачать полный трек #{idx} ({dur_str})",
                callback_data=f"play_{track['id']}"
            )
        ])

    text_content.append("━━━━━━━━━━━━━━━━━━\n<i>Нажмите на трек для отправки полного файла:</i>")

    reply_kb = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    await status_msg.edit_text("\n".join(text_content), reply_markup=reply_kb, parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.startswith("play_"))
async def callback_play_song(callback: CallbackQuery):
    track_id = callback.data.split("_", 1)[1]
    track = SEARCH_CACHE.get(track_id)

    await callback.answer("⏳ Отправляю полный MP3-файл...")

    if not track:
        await callback.message.answer("⚠️ Срок действия кнопок истек. Введите запрос заново.")
        return

    await callback.bot.send_chat_action(chat_id=callback.message.chat.id, action=ChatAction.UPLOAD_VOICE)

    try:
        audio = URLInputFile(
            url=track["url"],
            filename=f"{track['artist']} - {track['title']}.mp3"
        )

        caption = (
            f"🎶 <b>{track['title']}</b>\n"
            f"👤 <i>{track['artist']}</i>\n\n"
            f"⚡ <i>Music Hunter • Полная версия</i>"
        )

        await callback.message.answer_audio(
            audio=audio,
            title=track["title"][:60],
            performer=track["artist"][:40],
            duration=track["duration"] if track["duration"] > 0 else None,
            caption=caption,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        print(f"Audio send exception: {e}")
        await callback.message.answer("⚠️ Ошибка при отправке этого трека. Попробуйте нажать другую кнопку из списка.")

async def main():
    print("Запуск музыкального сервиса...")
    await start_web_server()
    print("Бот готов к выдаче полных аудиотреков!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
