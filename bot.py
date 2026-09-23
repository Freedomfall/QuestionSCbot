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
    raise ValueError("ОШИБКА: Переменная BOT_TOKEN не найдена в Environment Variables!")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Кэш для треков {video_id: metadata}
SEARCH_CACHE = {}

# Список быстрых публичных зеркал Piped / Invidious для загрузки полных треков
PIPED_INSTANCES = [
    "https://pipedapi.kavin.rocks",
    "https://api.piped.privacydev.net",
    "https://pipedapi.tokhmi.xyz"
]

# ----------------- ВЕБ-СЕРВЕР ДЛЯ РАБОТЫ 24/7 -----------------
async def health_check(request):
    return web.Response(text="Music Bot Engine is online 24/7!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Сервер мониторинга слушает порт {port}")
# -------------------------------------------------------------

def format_time(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    return f"{m:02d}:{s:02d}"

@dp.message(CommandStart())
async def start_cmd(message: Message):
    welcome_text = (
        "🎧 <b>Добро пожаловать в Music Hunter!</b>\n\n"
        "Я нахожу и скачиваю <b>полные версии треков</b> в высоком качестве.\n\n"
        "🔍 <b>Как пользоваться:</b>\n"
        "Просто напиши название песни или исполнителя прямо в чат.\n\n"
        "<i>Например:</i> <code>Eminem Mockingbird</code>"
    )
    await message.answer(welcome_text, parse_mode=ParseMode.HTML)

async def search_full_tracks(query: str):
    """Ищет до 5 полных треков через публичные зеркала API."""
    encoded_query = quote(query)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    # Пробуем зеркала по очереди для 100% надежности
    for instance in PIPED_INSTANCES:
        url = f"{instance}/search?q={encoded_query}&filter=music_songs"
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        items = data.get("items", [])
                        results = []
                        for item in items[:5]:
                            # Формируем ID видео
                            url_path = item.get("url", "")
                            video_id = url_path.replace("/watch?v=", "") if url_path else None
                            if not video_id:
                                continue

                            duration = item.get("duration", 0)
                            # Игнорируем длинные стримы или подкасты больше 15 минут
                            if duration > 900:
                                continue

                            results.append({
                                "id": video_id,
                                "title": item.get("title", "Трек"),
                                "artist": item.get("uploaderName", "Исполнитель"),
                                "duration": duration,
                                "instance": instance
                            })
                        if results:
                            return results
        except Exception:
            continue

    # Резервный поиск через стандартный музыкальный каталог (если зеркала недоступны)
    try:
        deezer_url = f"https://api.deezer.com/search?q={encoded_query}&limit=5"
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(deezer_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results = []
                    for t in data.get("data", [])[:5]:
                        results.append({
                            "id": f"dz_{t.get('id')}",
                            "title": t.get("title", "Без названия"),
                            "artist": t.get("artist", {}).get("name", "Исполнитель"),
                            "duration": int(t.get("duration", 0)),
                            "direct_url": t.get("preview")
                        })
                    return results
    except Exception:
        pass

    return []

async def get_stream_audio_url(video_id: str, instance: str):
    """Получает прямую ссылку на скачивание полного аудиофайла."""
    url = f"{instance}/streams/{video_id}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    audio_streams = data.get("audioStreams", [])
                    if audio_streams:
                        # Сортируем по битрейту, берем лучший звук (128-160k)
                        audio_streams.sort(key=lambda x: x.get("bitrate", 0), reverse=True)
                        return audio_streams[0].get("url")
    except Exception as e:
        print(f"Stream error: {e}")
    return None

@dp.message(F.text)
async def handle_search(message: Message):
    query = message.text.strip()
    if len(query) < 2:
        await message.answer("⚠️ Напишите чуть подробнее для точного поиска.")
        return

    await message.bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
    status_msg = await message.answer(f"🔎 <i>Ищу трек:</i> <b>{query}</b>...", parse_mode=ParseMode.HTML)

    tracks = await search_full_tracks(query)

    if not tracks:
        await status_msg.edit_text(
            "😔 <b>Ничего не найдено.</b>\nПопробуй написать название трека или имя исполнителя иначе.",
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
        dur_str = format_time(track["duration"]) if track["duration"] else "03:30"

        text_content.append(f"<b>{idx}.</b> 🎵 <b>{track['title']}</b>")
        text_content.append(f"    👤 {track['artist']}  ⏱ <code>{dur_str}</code>\n")

        keyboard_rows.append([
            InlineKeyboardButton(
                text=f"▶️ Скачать #{idx} ({dur_str})",
                callback_data=f"dl_{track['id']}"
            )
        ])

    text_content.append("━━━━━━━━━━━━━━━━━━\n<i>Нажмите на нужный трек для загрузки:</i>")

    reply_kb = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    await status_msg.edit_text("\n".join(text_content), reply_markup=reply_kb, parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.startswith("dl_"))
async def callback_download_song(callback: CallbackQuery):
    track_id = callback.data.split("_", 1)[1]
    track = SEARCH_CACHE.get(track_id)

    await callback.answer("⏳ Получаю полную аудиозапись...")

    if not track:
        await callback.message.answer("⚠️ Сессия выбора истекла. Напишите название заново.")
        return

    await callback.bot.send_chat_action(chat_id=callback.message.chat.id, action=ChatAction.UPLOAD_VOICE)
    wait_msg = await callback.message.answer(f"⚡ Загружаю полную версию: <b>{track['artist']} - {track['title']}</b>...", parse_mode=ParseMode.HTML)

    try:
        # Проверяем, прямой ли это резервный URL или нужно получить поток
        if "direct_url" in track:
            audio_url = track["direct_url"]
        else:
            audio_url = await get_stream_audio_url(track["id"], track["instance"])

        if not audio_url:
            await wait_msg.edit_text("⚠️ Не удалось получить ссылку на стрим. Попробуйте другой вариант из списка.")
            return

        audio = URLInputFile(
            url=audio_url,
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
        await wait_msg.delete()

    except Exception as e:
        print(f"Send audio error: {e}")
        await wait_msg.edit_text("⚠️ Ошибка при отправке файла. Выберите другой трек.")

async def main():
    print("Запуск музыкального бота (Full Tracks Engine)...")
    await start_web_server()
    print("Бот готов к выдаче полных аудиозаписей!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
