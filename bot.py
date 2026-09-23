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

# Кэш треков в памяти бота: {track_id: track_data}
SEARCH_CACHE = {}

# ----------------- ВЕБ-СЕРВЕР ДЛЯ FREE RENDER -----------------
async def health_check(request):
    return web.Response(text="Music Engine 24/7 is Online!")

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

def format_time(ms: int) -> str:
    """Форматирует миллисекунды в MM:SS."""
    seconds = int(ms / 1000)
    m, s = divmod(seconds, 60)
    return f"{m:02d}:{s:02d}"

@dp.message(CommandStart())
async def start_cmd(message: Message):
    await message.answer(
        "🎧 <b>Music Hunter Bot готов к работе!</b>\n\n"
        "Отправь мне имя артиста или название трека, и я найду <b>полную версию</b> песни.\n\n"
        "<i>Пример:</i> <code>Laura Branigan Self Control</code>",
        parse_mode=ParseMode.HTML
    )

async def get_soundcloud_client_id(session: aiohttp.ClientSession) -> str:
    """Получает актуальный открытый client_id для SoundCloud."""
    return "a3e059563d7fd3372b49b37f00a00bcf"

async def search_soundcloud_tracks(query: str):
    """Поиск полных аудиодорожек через открытый шлюз SoundCloud."""
    encoded_query = quote(query)
    client_id = "a3e059563d7fd3372b49b37f00a00bcf"
    url = f"https://api-v2.soundcloud.com/search/tracks?q={encoded_query}&client_id={client_id}&limit=5"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }

    results = []
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    collection = data.get("collection", [])
                    for item in collection:
                        title = item.get("title", "Без названия")
                        user_info = item.get("user", {})
                        artist = user_info.get("username", "Исполнитель")
                        duration_ms = item.get("duration", 0)
                        
                        # Отбираем аудиопоток (progressive mp3 или hls)
                        media = item.get("media", {}).get("transcodings", [])
                        stream_endpoint = None
                        for trans in media:
                            if trans.get("format", {}).get("protocol") == "progressive":
                                stream_endpoint = trans.get("url")
                                break
                        if not stream_endpoint and media:
                            stream_endpoint = media[0].get("url")

                        if stream_endpoint:
                            track_id = str(item.get("id"))
                            results.append({
                                "id": track_id,
                                "title": title,
                                "artist": artist,
                                "duration_ms": duration_ms,
                                "endpoint": stream_endpoint
                            })
                        if len(results) >= 5:
                            break
    except Exception as e:
        print(f"SoundCloud Search Error: {e}")

    return results

async def resolve_audio_stream_url(endpoint: str) -> str:
    """Получает конечную прямую ссылку на воспроизведение mp3."""
    client_id = "a3e059563d7fd3372b49b37f00a00bcf"
    target_url = f"{endpoint}?client_id={client_id}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(target_url, timeout=aiohttp.ClientTimeout(total=6)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("url")
    except Exception as e:
        print(f"Stream resolve error: {e}")
    return None

@dp.message(F.text)
async def handle_search(message: Message):
    query = message.text.strip()
    if len(query) < 2:
        await message.answer("⚠️ Напишите чуть подробнее для поиска.")
        return

    await message.bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
    wait_msg = await message.answer(f"🔎 <i>Ищу:</i> <b>{query}</b>...", parse_mode=ParseMode.HTML)

    tracks = await search_soundcloud_tracks(query)

    if not tracks:
        await wait_msg.edit_text(
            "😔 <b>По этому запросу ничего не найдено.</b>\nПопробуй написать название трека немного иначе.",
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
        dur_str = format_time(track["duration_ms"])

        text_content.append(f"<b>{idx}.</b> 🎵 <b>{track['title']}</b>")
        text_content.append(f"    👤 {track['artist']}  ⏱ <code>{dur_str}</code>\n")

        keyboard_rows.append([
            InlineKeyboardButton(
                text=f"▶️ Скачать полный трек #{idx} ({dur_str})",
                callback_data=f"sc_{track['id']}"
            )
        ])

    text_content.append("━━━━━━━━━━━━━━━━━━\n<i>Нажмите на кнопку ниже, чтобы получить полный файл:</i>")

    reply_kb = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    await wait_msg.edit_text("\n".join(text_content), reply_markup=reply_kb, parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.startswith("sc_"))
async def callback_download_sc(callback: CallbackQuery):
    track_id = callback.data.split("_", 1)[1]
    track = SEARCH_CACHE.get(track_id)

    await callback.answer("⏳ Загружаю полную версию трека...")

    if not track:
        await callback.message.answer("⚠️ Время сессии истекло. Отправьте запрос заново.")
        return

    await callback.bot.send_chat_action(chat_id=callback.message.chat.id, action=ChatAction.UPLOAD_VOICE)

    try:
        direct_url = await resolve_audio_stream_url(track["endpoint"])
        if not direct_url:
            await callback.message.answer("⚠️ Не удалось получить поток аудио. Попробуйте другой трек.")
            return

        audio = URLInputFile(
            url=direct_url,
            filename=f"{track['artist']} - {track['title']}.mp3"
        )

        dur_sec = int(track["duration_ms"] / 1000)
        caption = (
            f"🎶 <b>{track['title']}</b>\n"
            f"👤 <i>{track['artist']}</i>\n\n"
            f"⚡ <i>Music Hunter • Полная версия</i>"
        )

        await callback.message.answer_audio(
            audio=audio,
            title=track["title"][:60],
            performer=track["artist"][:40],
            duration=dur_sec,
            caption=caption,
            parse_mode=ParseMode.HTML
        )

    except Exception as e:
        print(f"Send audio error: {e}")
        await callback.message.answer("⚠️ Ошибка отправки файла. Выберите другой вариант из списка.")

async def main():
    print("Запуск музыкального сервиса...")
    await start_web_server()
    print("Бот готов к выдаче полных аудиотреков!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
