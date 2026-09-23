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

# Кэш для быстрого поиска треков по ID: {track_id: track_dict}
SEARCH_CACHE = {}

# ----------------- ВЕБ-СЕРВЕР ДЛЯ РАБОТЫ 24/7 -----------------
async def health_check(request):
    return web.Response(text="Bot UI & Engine online 24/7!")

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
    """Форматирует секунды в вид MM:SS."""
    m, s = divmod(seconds, 60)
    return f"{m:02d}:{s:02d}"

@dp.message(CommandStart())
async def start_cmd(message: Message):
    welcome_text = (
        "🎧 <b>Добро пожаловать в Music Hunter!</b>\n\n"
        "Я помогу найти и прослушать любой трек без лишних поисков и рекламы.\n\n"
        "✨ <b>Как пользоваться:</b>\n"
        "Просто отправь мне название песни или артиста в чат.\n\n"
        "<i>Например:</i> <code>The Weeknd Blinding Lights</code>"
    )
    await message.answer(welcome_text, parse_mode=ParseMode.HTML)

async def search_deezer_music_top5(query: str):
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
                    for t in data.get("data", []):
                        preview = t.get("preview")
                        if preview:
                            results_list.append({
                                "id": str(t.get("id")),
                                "title": t.get("title", "Без названия"),
                                "artist": t.get("artist", {}).get("name", "Исполнитель"),
                                "duration": int(t.get("duration", 0)),
                                "url": preview,
                                "cover": t.get("album", {}).get("cover_medium")
                            })
    except Exception as e:
        print(f"API Error: {e}")

    return results_list

@dp.message(F.text)
async def handle_search(message: Message):
    query = message.text.strip()
    if len(query) < 2:
        await message.answer("⚠️ Напишите чуть подробнее для точного поиска.")
        return

    await message.bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
    status_msg = await message.answer(f"🔎 <i>Ищу:</i> <b>{query}</b>...", parse_mode=ParseMode.HTML)

    tracks = await search_deezer_music_top5(query)

    if not tracks:
        await status_msg.edit_text(
            "😔 <b>Ничего не нашлось.</b>\nПопробуй проверить ошибки или написать имя артиста на английском.",
            parse_mode=ParseMode.HTML
        )
        return

    # Стильное оформление карточки выдачи
    text_content = [
        f"🎯 <b>Результаты поиска по запросу:</b> <i>«{query}»</i>\n",
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
                text=f"▶️ Слушать #{idx}: {track['title'][:22]}",
                callback_data=f"play_{track['id']}"
            )
        ])

    text_content.append("━━━━━━━━━━━━━━━━━━\n<i>Нажмите на кнопку ниже, чтобы запустить трек:</i>")

    reply_kb = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    await status_msg.edit_text("\n".join(text_content), reply_markup=reply_kb, parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.startswith("play_"))
async def callback_play_song(callback: CallbackQuery):
    track_id = callback.data.split("_")[1]
    track = SEARCH_CACHE.get(track_id)

    await callback.answer("⏳ Загружаю аудио...")

    if not track:
        await callback.message.answer("⚠️ Сессия истекла. Отправьте запрос заново.")
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
            f"⚡ <i>Music Hunter Bot • Приятного прослушивания!</i>"
        )

        await callback.message.answer_audio(
            audio=audio,
            title=track["title"][:60],
            performer=track["artist"][:40],
            caption=caption,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        print(f"Send audio error: {e}")
        await callback.message.answer("⚠️ Не удалось воспроизвести этот трек. Попробуйте другой из списка.")

async def main():
    print("Запуск музыкального бота с новым интерфейсом...")
    await start_web_server()
    print("Бот готов к работе!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
