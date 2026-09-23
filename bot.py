import asyncio
import os
import re
from urllib.parse import quote
from aiohttp import web
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, URLInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ChatAction, ParseMode
import aiohttp

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("ОШИБКА: BOT_TOKEN не найден в Environment Variables!")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Кэш треков в памяти бота: {track_id: track_info}
SEARCH_CACHE = {}

# ----------------- ВЕБ-СЕРВЕР ДЛЯ FREE RENDER 24/7 -----------------
async def health_check(request):
    return web.Response(text="Music Bot Engine 24/7 is Active!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Веб-сервер заглушки запущен на порту {port}")
# ------------------------------------------------------------------

@dp.message(CommandStart())
async def start_cmd(message: Message):
    welcome_text = (
        "🎧 <b>Music Hunter Bot готов к поиску!</b>\n\n"
        "Отправь мне название песни или имя исполнителя, "
        "и я найду <b>полные треки</b> в высоком качестве (320 kbps).\n\n"
        "<i>Пример:</i> <code>Laura Branigan Self Control</code>"
    )
    await message.answer(welcome_text, parse_mode=ParseMode.HTML)

async def search_full_mp3(query: str):
    """
    Прямой парсинг открытой базы Hitmo / Zvuk.
    Отдает полные MP3 файлы без ограничений по длительности.
    """
    encoded_query = quote(query)
    search_url = f"https://rus.hitmotop.com/search?q={encoded_query}"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }

    results = []
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(search_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    soup = BeautifulSoup(html, "html.parser")
                    tracks_html = soup.find_all("li", class_="tracks__item")

                    for idx, item in enumerate(tracks_html[:5]):
                        # Извлекаем ссылку на скачивание MP3
                        dl_link = item.find("a", class_="track__download-btn")
                        if not dl_link or not dl_link.get("href"):
                            continue

                        mp3_url = dl_link.get("href").strip()
                        
                        # Извлекаем название и автора
                        title_elem = item.find("div", class_="track__title")
                        desc_elem = item.find("div", class_="track__desc")
                        time_elem = item.find("div", class_="track__fulltime")

                        title = title_elem.text.strip() if title_elem else "Трек"
                        artist = desc_elem.text.strip() if desc_elem else "Исполнитель"
                        duration_str = time_elem.text.strip() if time_elem else "03:30"

                        # Вычисляем секунды для плеера
                        dur_sec = 210
                        if ":" in duration_str:
                            parts = duration_str.split(":")
                            try:
                                dur_sec = int(parts[0]) * 60 + int(parts[1])
                            except ValueError:
                                pass

                        track_id = f"t_{idx}_{hash(mp3_url) % 100000}"
                        results.append({
                            "id": track_id,
                            "title": title,
                            "artist": artist,
                            "duration_str": duration_str,
                            "dur_sec": dur_sec,
                            "url": mp3_url
                        })
    except Exception as e:
        print(f"Parsing error: {e}")

    return results

@dp.message(F.text)
async def handle_search(message: Message):
    query = message.text.strip()
    
    # Игнорируем случайные команды без текста
    if query.startswith("/"):
        return

    if len(query) < 2:
        await message.answer("⚠️ Напишите чуть подробнее для поиска.")
        return

    await message.bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
    wait_msg = await message.answer(f"🔎 <i>Ищу полные версии для:</i> <b>{query}</b>...", parse_mode=ParseMode.HTML)

    tracks = await search_full_mp3(query)

    if not tracks:
        await wait_msg.edit_text(
            "😔 <b>По этому запросу треков не найдено.</b>\n"
            "Попробуй ввести только исполнителя или проверить правильность написания.",
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

        text_content.append(f"<b>{idx}.</b> 🎵 <b>{track['title']}</b>")
        text_content.append(f"    👤 {track['artist']}  ⏱ <code>{track['duration_str']}</code>\n")

        keyboard_rows.append([
            InlineKeyboardButton(
                text=f"▶️ Скачать #{idx} ({track['duration_str']})",
                callback_data=f"dl_{track['id']}"
            )
        ])

    text_content.append("━━━━━━━━━━━━━━━━━━\n<i>Нажмите на кнопку с треком для отправки:</i>")

    reply_kb = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    await wait_msg.edit_text("\n".join(text_content), reply_markup=reply_kb, parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.startswith("dl_"))
async def callback_download(callback: CallbackQuery):
    track_id = callback.data.split("_", 1)[1]
    track = SEARCH_CACHE.get(track_id)

    await callback.answer("⏳ Отправляю полный MP3 трек...")

    if not track:
        await callback.message.answer("⚠️ Время сессии истекло. Отправьте запрос заново.")
        return

    await callback.bot.send_chat_action(chat_id=callback.message.chat.id, action=ChatAction.UPLOAD_VOICE)

    try:
        audio = URLInputFile(
            url=track["url"],
            filename=f"{track['artist']} - {track['title']}.mp3"
        )

        caption = (
            f"🎶 <b>{track['title']}</b>\n"
            f"👤 <i>{track['artist']}</i>\n"
            f"⏱ Длительность: <code>{track['duration_str']}</code>\n\n"
            f"⚡ <i>Music Hunter • Полная версия</i>"
        )

        await callback.message.answer_audio(
            audio=audio,
            title=track["title"][:60],
            performer=track["artist"][:40],
            duration=track["dur_sec"],
            caption=caption,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        print(f"Send audio error: {e}")
        await callback.message.answer("⚠️ Не удалось загрузить данный файл. Выберите другой вариант из списка.")

async def main():
    print("Запуск надежного музыкального сервиса...")
    await start_web_server()
    print("Бот готов к приему сообщений!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
