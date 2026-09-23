import asyncio
import os
import glob
from urllib.parse import quote
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ChatAction, ParseMode
import static_ffmpeg
import yt_dlp

# Автоматически подключаем встроенные кодеки ffmpeg
static_ffmpeg.add_paths()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("ОШИБКА: BOT_TOKEN не найден в Environment Variables!")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

SEARCH_CACHE = {}

# ----------------- ВЕБ-СЕРВЕР ДЛЯ FREE RENDER 24/7 -----------------
async def health_check(request):
    return web.Response(text="Music Bot Engine is 100% Online!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Веб-сервер запущен на порту {port}")
# ------------------------------------------------------------------

def format_time(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    return f"{m:02d}:{s:02d}"

@dp.message(CommandStart())
async def start_cmd(message: Message):
    welcome_text = (
        "🎧 <b>Music Hunter Bot готов к работе!</b>\n\n"
        "Я ищу и отправляю <b>полные версии треков</b> без ограничений.\n\n"
        "Отправь мне имя артиста или название трека (например: <code>Laura Branigan Self Control</code>)."
    )
    await message.answer(welcome_text, parse_mode=ParseMode.HTML)

def search_tracks_sync(query: str):
    """Ищет до 5 треков через YouTube Music клиент."""
    ydl_opts = {
        'extract_flat': True,
        'skip_download': True,
        'quiet': True,
        'no_warnings': True,
        'default_search': 'ytsearch5',
        'extractor_args': {
            'youtube': {
                'player_client': ['web_creator', 'web', 'android'],
                'skip': ['dash', 'hls']
            }
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7'
        }
    }

    results = []
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(f"ytsearch5:{query} audio", download=False)
            entries = info.get('entries', []) if info else []
            for item in entries:
                if not item:
                    continue
                v_id = item.get('id')
                title = item.get('title', 'Трек')
                artist = item.get('uploader', 'Исполнитель')
                duration = int(item.get('duration') or 0)

                if duration > 600 or duration < 40:
                    continue

                results.append({
                    'id': v_id,
                    'title': title,
                    'artist': artist,
                    'duration': duration,
                    'url': f"https://www.youtube.com/watch?v={v_id}"
                })
                if len(results) >= 5:
                    break
        except Exception as e:
            print(f"Search error: {e}")

    return results

def download_track_sync(video_url: str, chat_id: int):
    """Скачивает аудиодорожку с использованием встроенного static-ffmpeg."""
    out_tmpl = os.path.join(DOWNLOAD_DIR, f"{chat_id}_%(id)s.%(ext)s")
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': out_tmpl,
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'max_filesize': 45 * 1024 * 1024,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web_creator']
            }
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36'
        }
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(video_url, download=True)
        title = info.get('title', 'track')
        artist = info.get('uploader', 'artist')
        duration = int(info.get('duration') or 0)

        pattern = os.path.join(DOWNLOAD_DIR, f"{chat_id}_*.mp3")
        found = glob.glob(pattern)
        if found:
            return found[0], title, artist, duration
    return None, None, None, None

@dp.message(F.text)
async def handle_search(message: Message):
    query = message.text.strip()
    if query.startswith("/"):
        return
    if len(query) < 2:
        await message.answer("⚠️ Напишите чуть подробнее для поиска.")
        return

    await message.bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
    wait_msg = await message.answer(f"🔎 <i>Ищу полные версии для:</i> <b>{query}</b>...", parse_mode=ParseMode.HTML)

    tracks = await asyncio.to_thread(search_tracks_sync, query)

    if not tracks:
        await wait_msg.edit_text(
            "😔 <b>По этому запросу ничего не найдено.</b>\nПопробуй написать точнее имя артиста и трека.",
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
        dur_str = format_time(track["duration"])

        text_content.append(f"<b>{idx}.</b> 🎵 <b>{track['title']}</b>")
        text_content.append(f"    👤 {track['artist']}  ⏱ <code>{dur_str}</code>\n")

        keyboard_rows.append([
            InlineKeyboardButton(
                text=f"▶️ Скачать полный трек #{idx} ({dur_str})",
                callback_data=f"yt_{track['id']}"
            )
        ])

    text_content.append("━━━━━━━━━━━━━━━━━━\n<i>Нажмите на нужный трек для скачивания:</i>")

    reply_kb = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    await wait_msg.edit_text("\n".join(text_content), reply_markup=reply_kb, parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.startswith("yt_"))
async def callback_download_yt(callback: CallbackQuery):
    track_id = callback.data.split("_", 1)[1]
    track = SEARCH_CACHE.get(track_id)

    await callback.answer("⏳ Скачиваю полную аудиозапись...")

    if not track:
        await callback.message.answer("⚠️ Время сессии истекло. Отправьте запрос заново.")
        return

    await callback.bot.send_chat_action(chat_id=callback.message.chat.id, action=ChatAction.UPLOAD_VOICE)
    wait_msg = await callback.message.answer("⚡ Загружаю трек в Telegram...", parse_mode=ParseMode.HTML)

    file_path = None
    try:
        file_path, title, artist, duration = await asyncio.to_thread(
            download_track_sync, track["url"], callback.message.chat.id
        )

        if file_path and os.path.exists(file_path):
            audio_file = FSInputFile(file_path, filename=f"{track['artist']} - {track['title']}.mp3")

            caption = (
                f"🎶 <b>{track['title']}</b>\n"
                f"👤 <i>{track['artist']}</i>\n\n"
                f"⚡ <i>Music Hunter • Полная версия</i>"
            )

            await callback.message.answer_audio(
                audio=audio_file,
                title=track["title"][:60],
                performer=track["artist"][:40],
                duration=duration if duration > 0 else None,
                caption=caption,
                parse_mode=ParseMode.HTML
            )
            await wait_msg.delete()
        else:
            await wait_msg.edit_text("⚠️ Ошибка получения файла. Попробуйте выбрать другой вариант.")

    except Exception as e:
        print(f"Callback download error: {e}")
        await wait_msg.edit_text("⚠️ Не удалось загрузить данный файл. Выберите другой трек.")

    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass

async def main():
    print("Запуск музыкального сервиса с поддержкой static-ffmpeg...")
    await start_web_server()
    print("Бот готов к приему сообщений!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
