import asyncio
import os
import glob
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, FSInputFile
from aiogram.enums import ChatAction
import yt_dlp

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("ОШИБКА: Переменная BOT_TOKEN не найдена в Environment Variables!")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ----------------- ВЕБ-СЕРВЕР ДЛЯ RENDER -----------------
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
    print(f"Сервер заглушки слушает порт {port}")
# --------------------------------------------------------

@dp.message(CommandStart())
async def start_cmd(message: Message):
    await message.answer(
        "👋 **Привет! Я бот для быстрого поиска музыки.**\n\n"
        "Отправь мне имя исполнителя или название песни (например: `Eminem Mockingbird`), "
        "и я найду трек.",
        parse_mode="Markdown"
    )

def download_audio_stream(query: str, chat_id: int):
    out_tmpl = os.path.join(DOWNLOAD_DIR, f"{chat_id}_%(id)s.%(ext)s")

    # Пробуем два источника: сначала YouTube (с обходом мобильным клиентом), затем SoundCloud
    search_queries = [
        f"ytsearch1:{query}",
        f"scsearch1:{query}"
    ]

    base_opts = {
        'format': 'bestaudio/best',
        'outtmpl': out_tmpl,
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'max_filesize': 48 * 1024 * 1024,
        # Защита от блокировок дата-центров (эмуляция мобильного клиента Android)
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web']
            }
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36'
        }
    }

    last_error = None
    for target in search_queries:
        try:
            with yt_dlp.YoutubeDL(base_opts) as ydl:
                info = ydl.extract_info(target, download=True)
                if not info:
                    continue

                if 'entries' in info and len(info['entries']) > 0:
                    video_info = info['entries'][0]
                else:
                    video_info = info

                if not video_info:
                    continue

                title = video_info.get('title', 'audio')
                performer = video_info.get('uploader', 'Unknown Artist')
                duration = video_info.get('duration', 0)

                # Находим файл, созданный под текущий запрос
                pattern = os.path.join(DOWNLOAD_DIR, f"{chat_id}_*")
                found_files = glob.glob(pattern)
                if found_files:
                    return found_files[0], title, performer, duration
        except Exception as e:
            last_error = e
            continue

    if last_error:
        print(f"Ошибка загрузки: {last_error}")
    return None, None, None, None

@dp.message(F.text)
async def handle_search(message: Message):
    query = message.text.strip()
    if len(query) < 2:
        await message.answer("Слишком короткий запрос для поиска.")
        return

    await message.bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.UPLOAD_VOICE)
    wait_msg = await message.answer(f"🔍 Ищу: <b>{query}</b>...", parse_mode="HTML")

    file_path = None
    try:
        file_path, title, performer, duration = await asyncio.to_thread(
            download_audio_stream, query, message.chat.id
        )

        if file_path and os.path.exists(file_path):
            await wait_msg.edit_text("⚡ Трек найден, отправляю...")

            ext = os.path.splitext(file_path)[1]
            audio_file = FSInputFile(file_path, filename=f"{title}{ext}")

            await message.answer_audio(
                audio=audio_file,
                title=title[:60],
                performer=performer[:40],
                duration=int(duration) if duration else None,
                caption=f"🎵 <b>{title}</b>",
                parse_mode="HTML"
            )
            await wait_msg.delete()
        else:
            await wait_msg.edit_text("😔 По этому запросу трек не найден. Попробуй уточнить исполнителя.")

    except Exception as e:
        print(f"Handler error: {e}")
        await wait_msg.edit_text("⚠️ Ошибка при обработке. Попробуй еще раз через минуту.")

    finally:
        # Очистка диска
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass

async def main():
    print("Запуск сервиса...")
    await start_web_server()
    print("Бот готов к приему сообщений!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
