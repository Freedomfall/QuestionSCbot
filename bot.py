import asyncio
import os
import aiohttp
from urllib.parse import quote
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, URLInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ChatAction

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("ОШИБКА: Переменная BOT_TOKEN не найдена в Environment Variables!")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Временное хранилище найденных треков в памяти {track_id: track_data}
SEARCH_CACHE = {}

# ----------------- ВЕБ-СЕРВЕР ДЛЯ RENDER И PING 24/7 -----------------
async def health_check(request):
    return web.Response(text="Bot is awake and running 24/7!")

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
        "👋 **Привет! Я музыкальный бот.**\n\n"
        "Напиши название песни или артиста, и я предложу топ-5 лучших вариантов!",
        parse_mode="Markdown"
    )

async def search_deezer_music_top5(query: str):
    """Ищет до 5 результатов через Deezer API."""
    encoded_query = quote(query)
    url = f"https://api.deezer.com/search?q={encoded_query}&limit=5"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    results_list = []
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    tracks = data.get("data", [])
                    for t in tracks:
                        preview = t.get("preview")
                        if preview:
                            results_list.append({
                                "id": str(t.get("id")),
                                "title": t.get("title", "Без названия"),
                                "artist": t.get("artist", {}).get("name", "Неизвестный исполнитель"),
                                "duration": int(t.get("duration", 0)),
                                "url": preview
                            })
    except Exception as e:
        print(f"Search API Error: {e}")

    return results_list

@dp.message(F.text)
async def handle_search(message: Message):
    query = message.text.strip()
    if len(query) < 2:
        await message.answer("Слишком короткий запрос для поиска.")
        return

    await message.bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
    status_msg = await message.answer(f"🔍 Ищу варианты для: <b>{query}</b>...", parse_mode="HTML")

    tracks = await search_deezer_music_top5(query)

    if not tracks:
        await status_msg.edit_text("😔 По твоему запросу ничего не найдено. Попробуй уточнить название.")
        return

    text_lines = ["🎵 <b>Выберите трек для скачивания:</b>\n"]
    keyboard_buttons = []

    for idx, track in enumerate(tracks, start=1):
        SEARCH_CACHE[track["id"]] = track
        text_lines.append(f"{idx}. <b>{track['artist']}</b> — {track['title']}")
        keyboard_buttons.append(
            InlineKeyboardButton(text=f"🎧 {idx}", callback_data=f"play_{track['id']}")
        )

    # Клавиатура с кнопками в один или два ряда
    inline_kb = InlineKeyboardMarkup(inline_keyboard=[keyboard_buttons])

    await status_msg.edit_text("\n".join(text_lines), reply_markup=inline_kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("play_"))
async def callback_play_song(callback: CallbackQuery):
    track_id = callback.data.split("_")[1]
    track = SEARCH_CACHE.get(track_id)

    await callback.answer()  # убираем часики на кнопке

    if not track:
        await callback.message.answer("⚠️ Срок действия выбора истек. Введите запрос заново.")
        return

    await callback.bot.send_chat_action(chat_id=callback.message.chat.id, action=ChatAction.UPLOAD_VOICE)
    wait_msg = await callback.message.answer(f"⚡ Отправляю: <b>{track['artist']} - {track['title']}</b>...", parse_mode="HTML")

    try:
        audio = URLInputFile(
            url=track["url"],
            filename=f"{track['artist']} - {track['title']}.mp3"
        )

        await callback.message.answer_audio(
            audio=audio,
            title=track["title"][:60],
            performer=track["artist"][:40],
            duration=track["duration"] if track["duration"] > 0 else None,
            caption=f"🎵 <b>{track['artist']} - {track['title']}</b>",
            parse_mode="HTML"
        )
        await wait_msg.delete()
    except Exception as e:
        print(f"Send audio error: {e}")
        await wait_msg.edit_text("⚠️ Ошибка отправки аудио. Попробуй еще раз.")

async def main():
    print("Запуск музыкального сервиса...")
    await start_web_server()
    print("Бот готов к приему сообщений!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
