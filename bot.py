import asyncio
import os
import re
import tempfile
from typing import Optional, Tuple

import aiohttp
from urllib.parse import quote
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.enums import ChatAction, ParseMode

try:
    from mutagen.mp3 import MP3
    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("ОШИБКА: BOT_TOKEN не найден в Environment Variables!")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Кэш результатов поиска в оперативной памяти бота
SEARCH_CACHE = {}
TEMP_DIR = tempfile.gettempdir()

# Ограничение Telegram Bot API на размер файла, отправляемого ботом
MAX_TELEGRAM_FILE_SIZE = 49 * 1024 * 1024  # ~49 МБ, с запасом от лимита в 50 МБ

# Только коллекции archive.org со свободно распространяемым контентом:
#   etree        — концертные записи, выложенные с явного разрешения артистов
#   netlabels    — музыка, выпущенная под лицензиями Creative Commons
#   librivoxaudio — аудиокниги, целиком относящиеся к общественному достоянию
LEGAL_COLLECTIONS = "etree OR netlabels OR librivoxaudio"


# ----------------- ВЕБ-СЕРВЕР ДЛЯ RENDER 24/7 -----------------
async def health_check(request):
    return web.Response(text="Music Hunter Bot (Legal Archive Edition) online")


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
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def parse_length(value) -> int:
    """archive.org отдаёт длительность то числом секунд, то строкой MM:SS."""
    if isinstance(value, list):
        value = value[0] if value else None
    if value is None:
        return 0
    try:
        return int(float(value))
    except (ValueError, TypeError):
        pass
    if isinstance(value, str) and ":" in value:
        parts = value.split(":")
        try:
            parts = [int(p) for p in parts]
        except ValueError:
            return 0
        secs = 0
        for p in parts:
            secs = secs * 60 + p
        return secs
    return 0


@dp.message(CommandStart())
async def start_cmd(message: Message):
    welcome_text = (
        "🎧 <b>Music Hunter Bot</b>\n\n"
        "Ищу аудио в открытых легальных коллекциях Archive.org:\n"
        "• концерты, выложенные с разрешения артистов (Live Music Archive)\n"
        "• музыка под лицензией Creative Commons (нетлейблы)\n"
        "• аудиокниги в общественном достоянии (LibriVox)\n\n"
        "Просто отправь название трека, альбома, исполнителя или книги."
    )
    await message.answer(welcome_text, parse_mode=ParseMode.HTML)


async def search_archive_music(query: str):
    """Ищет только в разрешённых к свободному распространению коллекциях."""
    search_expr = (
        f"(title:({query}) OR creator:({query})) "
        f"AND mediatype:(audio) "
        f"AND collection:({LEGAL_COLLECTIONS})"
    )
    url = (
        "https://archive.org/advancedsearch.php"
        f"?q={quote(search_expr)}"
        "&fl[]=identifier&fl[]=title&fl[]=creator&fl[]=downloads"
        "&sort[]=downloads+desc"
        "&rows=5&output=json"
    )
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    results = []
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    docs = data.get("response", {}).get("docs", [])
                    for idx, doc in enumerate(docs):
                        identifier = doc.get("identifier")
                        if not identifier:
                            continue
                        title = doc.get("title", "Трек")
                        creator = doc.get("creator", "Неизвестный исполнитель")
                        if isinstance(creator, list):
                            creator = ", ".join(creator)
                        if isinstance(title, list):
                            title = title[0]
                        results.append({
                            "id": f"arch_{idx}_{identifier[:20]}",
                            "title": str(title)[:60],
                            "artist": str(creator)[:40],
                            "identifier": identifier,
                        })
    except Exception as e:
        print(f"Archive Search Error: {e}")

    return results


async def get_archive_mp3_file(identifier: str) -> Optional[Tuple[str, int, int]]:
    """
    Возвращает (url, size_bytes, duration_seconds) для наиболее подходящего
    ПОЛНОГО mp3-файла из манифеста archive.org, либо None.
    """
    meta_url = f"https://archive.org/metadata/{identifier}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(meta_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
    except Exception as e:
        print(f"Metadata error: {e}")
        return None

    files = data.get("files", [])
    candidates = []
    for f in files:
        name = f.get("name", "")
        fmt = f.get("format", "")
        if not name.lower().endswith(".mp3"):
            continue
        # Пропускаем явные превью/сэмплы — это и есть частая причина
        # "обрезанных до 30 секунд" треков: бот раньше мог случайно взять
        # именно такой файл вместо полной дорожки.
        if re.search(r"(sample|preview|snippet)", name, re.IGNORECASE):
            continue
        try:
            size = int(f.get("size", 0))
        except (ValueError, TypeError):
            size = 0
        duration = parse_length(f.get("length"))
        candidates.append((name, fmt, size, duration))

    if not candidates:
        return None

    # Предпочитаем стандартный производный формат archive.org ("VBR MP3"),
    # а из нескольких — самый большой файл (реже всего оказывается обрезком)
    candidates.sort(key=lambda c: (c[1] != "VBR MP3", -c[2]))
    name, fmt, size, duration = candidates[0]
    file_url = f"https://archive.org/download/{identifier}/{quote(name)}"
    return file_url, size, duration


async def download_audio(url: str, expected_size: int) -> Optional[str]:
    """
    Полностью скачивает файл на диск и проверяет его размер, вместо того
    чтобы полагаться на прямую потоковую передачу в Telegram.

    Именно обрыв потоковой закачки — самая частая причина, по которой
    боты на архивах присылают куски по 20-30 секунд: aiogram/Telegram
    начинают отдавать то, что успели скачать, если соединение с archive.org
    прерывается или превышается таймаут, и получается "рабочий", но
    обрезанный mp3-файл.
    """
    fd, path = tempfile.mkstemp(suffix=".mp3", dir=TEMP_DIR)
    os.close(fd)
    headers = {"User-Agent": "Mozilla/5.0"}
    # Общий таймаут побольше (архив иногда отдаёт файлы медленно),
    # но с защитой от полностью зависшего соединения (sock_read).
    timeout = aiohttp.ClientTimeout(total=180, sock_read=60)

    try:
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    os.remove(path)
                    return None

                content_length = resp.headers.get("Content-Length")
                if content_length:
                    try:
                        expected_size = max(expected_size, int(content_length))
                    except ValueError:
                        pass

                total = 0
                with open(path, "wb") as fh:
                    async for chunk in resp.content.iter_chunked(65536):
                        fh.write(chunk)
                        total += len(chunk)

        # Если скачали заметно меньше, чем ожидалось — файл обрезан,
        # такой отправлять нельзя.
        if expected_size and total < expected_size * 0.98:
            print(f"Downloaded {total} bytes, expected ~{expected_size}")
            os.remove(path)
            return None

        if total < 50_000:
            # Слишком маленький файл — почти наверняка не полный трек
            os.remove(path)
            return None

        if total > MAX_TELEGRAM_FILE_SIZE:
            os.remove(path)
            return None

        return path
    except Exception as e:
        print(f"Download error: {e}")
        if os.path.exists(path):
            os.remove(path)
        return None


@dp.message(F.text)
async def handle_search(message: Message):
    query = message.text.strip()
    if query.startswith("/"):
        return
    if len(query) < 2:
        await message.answer("⚠️ Напишите чуть подробнее для поиска.")
        return

    await message.bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
    wait_msg = await message.answer(
        f"🔎 <i>Ищу в легальных коллекциях:</i> <b>{query}</b>...",
        parse_mode=ParseMode.HTML,
    )

    tracks = await search_archive_music(query)

    if not tracks:
        await wait_msg.edit_text(
            "😕 Ничего не нашлось в легальных коллекциях архива "
            "(концерты с разрешения артистов, CC-музыка, аудиокниги).\n"
            "Попробуйте другой вариант названия или другого исполнителя.",
            parse_mode=ParseMode.HTML,
        )
        return

    text_content = [
        f"🎯 <b>Результаты поиска:</b> <i>«{query}»</i>\n",
        "━━━━━━━━━━━━━━━━━━",
    ]
    keyboard_rows = []
    for idx, track in enumerate(tracks, start=1):
        SEARCH_CACHE[track["id"]] = track
        text_content.append(f"<b>{idx}.</b> 🎵 <b>{track['title']}</b>")
        text_content.append(f"    👤 {track['artist']}\n")
        keyboard_rows.append([
            InlineKeyboardButton(
                text=f"▶️ Получить трек #{idx}",
                callback_data=f"arc_{track['id']}",
            )
        ])

    text_content.append("━━━━━━━━━━━━━━━━━━\n<i>Нажмите на кнопку, чтобы получить аудиофайл:</i>")
    reply_kb = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    await wait_msg.edit_text("\n".join(text_content), reply_markup=reply_kb, parse_mode=ParseMode.HTML)


@dp.callback_query(F.data.startswith("arc_"))
async def callback_download_archive(callback: CallbackQuery):
    track_id = callback.data.split("_", 1)[1]
    track = SEARCH_CACHE.get(track_id)
    await callback.answer("⏳ Готовлю файл...")

    if not track:
        await callback.message.answer("⚠️ Сессия истекла. Отправьте запрос заново.")
        return

    await callback.bot.send_chat_action(chat_id=callback.message.chat.id, action=ChatAction.UPLOAD_VOICE)
    wait_msg = await callback.message.answer("⚡ Скачиваю полный файл из архива...", parse_mode=ParseMode.HTML)

    file_info = await get_archive_mp3_file(track["identifier"])
    if not file_info:
        await wait_msg.edit_text(
            "⚠️ Не удалось найти полноразмерный аудиофайл для этого результата. "
            "Попробуйте другой вариант."
        )
        return

    file_url, expected_size, meta_duration = file_info
    local_path = await download_audio(file_url, expected_size)

    if not local_path:
        await wait_msg.edit_text(
            "⚠️ Файл скачался не полностью (архив мог оборвать соединение, "
            "или файл больше 49 МБ). Попробуйте ещё раз или выберите другой трек."
        )
        return

    duration = meta_duration
    if MUTAGEN_AVAILABLE and not duration:
        try:
            duration = int(MP3(local_path).info.length)
        except Exception:
            duration = 0

    try:
        audio = FSInputFile(local_path, filename=f"{track['artist']} - {track['title']}.mp3")
        caption = (
            f"🎶 <b>{track['title']}</b>\n"
            f"👤 <i>{track['artist']}</i>"
            + (f"\n⏱ {format_time(duration)}" if duration else "")
        )
        await callback.message.answer_audio(
            audio=audio,
            title=track["title"][:60],
            performer=track["artist"][:40],
            duration=duration or None,
            caption=caption,
            parse_mode=ParseMode.HTML,
        )
        await wait_msg.delete()
    except Exception as e:
        print(f"Send audio error: {e}")
        await wait_msg.edit_text("⚠️ Ошибка отправки файла. Попробуйте другой трек.")
    finally:
        if os.path.exists(local_path):
            os.remove(local_path)


async def main():
    print("Запуск музыкального бота...")
    await start_web_server()
    print("Бот готов к работе!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
