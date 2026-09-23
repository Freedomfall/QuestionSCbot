import asyncio
import os
import glob
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, FSInputFile
from aiogram.enums import ChatAction
import yt_dlp

# Получаем токен из настроек хостинга
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("ОШИБКА: Переменная BOT_TOKEN не найдена в Environment Variables!")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ----------------- ОБХОД ОГРАНИЧЕНИЯ RENDER -----------------
# Render Free требует открытый веб-порт, иначе глушит процесс.
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
    print(f"Веб-сервер заглушки запущен на порту {port}")
# -------------------------------------------------------------

@dp.message(CommandStart())
async def start_cmd(message: Message):
    await message.answer(
        "👋 **Привет! Я бот для быстрого поиска музыки.**\n\n"
        "Напиши мне название песни и исполнителя (например: `Eminem Mockingbird`), "
        "и я мгновенно пришлю аудиозапись.",
        parse_mode="Markdown"
    )

def download_audio_stream(query: str, chat_id: int):
    """
    Скачивание лучшего доступного аудио (m4a/mp3) без необходимости ffmpeg.
    """
    out_tmpl = os.path.join(DOWNLOAD_DIR, f"{chat_id}_%(id)s.%(ext)s")
    
    ydl_opts = {
        # Берем готовое аудио в m4a/mp3 (Telegram идеально их играет)
        'format': 'bestaudio[ext=m4a]/bestaudio/best',
        'default_search': 'ytsearch1:',
        'outtmpl': out_tmpl,
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        # Ограничение размера до 45 МБ, чтобы влезть в лимит Telegram (50 МБ)
        'max_filesize': 45 * 1024 * 1024,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(query, download=True)
        if 'entries' in info and len(info['entries']) > 0:
            video_info = info['entries'][0]
        else:
            video_info = info

        title = video_info.get('title', 'audio')
        performer = video_info.get('uploader', 'Music Bot')
        duration = video_info.get('duration', 0)

        # Находим скачанный файл
        pattern = os.path.join(DOWNLOAD_DIR, f"{chat_id}_*")
        found_files = glob.glob(pattern)
        if found_files:
            return found_files[0], title, performer, duration
            
    return None, None, None, None

@dp.message(F.text)
async def handle_search(message: Message):
    query = message.text.strip()
    if len(query) < 2:
        await message.answer("Слишком короткий запрос для поиска.")
        return

    # Показываем статус «Бот отправляет аудиофайл...»
    await message.bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.UPLOAD_VOICE)
    wait_msg = await message.answer(f"🔍 Ищу: <b>{query}</b>...", parse_mode="HTML")

    file_path = None
    try:
        # Выполняем скачивание в отдельном потоке
        file_path, title, performer, duration = await asyncio.to_thread(
            download_audio_stream, query, message.chat.id
        )

        if file_path and os.path.exists(file_path):
            await wait_msg.edit_text("⚡ Загружаю трек в Telegram...")
            
            # Определяем расширение
            ext = os.path.splitext(file_path)[1]
            audio_file = FSInputFile(file_path, filename=f"{title}{ext}")

            await message.answer_audio(
                audio=audio_file,
                title=title[:60],
                performer=performer[:40],
                duration=int(duration) if duration else None,
                caption=f"🎧 <b>{title}</b>\n\nПриятного прослушивания!",
                parse_mode="HTML"
            )
            await wait_msg.delete()
        else:
            await wait_msg.edit_text("😔 Не удалось найти подходящий трек. Попробуй уточнить название.")

    except Exception as e:
        err_msg = str(e)
        if "File is larger than max_filesize" in err_msg:
            await wait_msg.edit_text("⚠️ Трек слишком длинный (размер превышает лимит в 45 МБ).")
        else:
            await wait_msg.edit_text("⚠️ Ошибка при обработке запроса. Попробуй другой трек.")
        print(f"Error: {e}")

    finally:
        # Гарантированное удаление файла после отправки или при ошибке
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass

async def main():
    print("Запуск сервиса...")
    # Запускаем фоновый веб-сервер для бесплатного тарифа Render
    await start_web_server()
    # Запускаем поллинг Telegram-бота
    print("Бот готов к приему сообщений!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
