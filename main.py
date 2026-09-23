import os
import asyncio
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN не задан!")

bot = Bot(token=TOKEN)
dp = Dispatcher()

# База игроков: {user_id: {"step": 1, "is_paid": False}}
players = {}

def get_player(user_id):
    if user_id not in players:
        players[user_id] = {"step": 1, "is_paid": False}
    return players[user_id]

# --- БАЗА СЮЖЕТА (СЮДА ДОБАВЛЯЕМ ШАГИ) ---
# Структура:
# text: описание ситуации
# video_id: id анимации (или None, если пока нет видео)
# options: 3 варианта. Один ведет на step + 1, два других — к смерти с описанием.
QUEST_DATA = {
    1: {
        "text": "🚪 **Шаг 1: Подсобка магазина.**\n\nДверь выбивают зараженные! Времени секунды. Куда кинешься?",
        "video_id": None,
        "options": [
            {"text": "🏃 В узкий вентиляционный люк", "correct": True},
            {"text": "🪓 Встретить тварей монтировкой", "correct": False, "death": "Мертвецов оказалось слишком много. Они повалили тебя на пол... ТЫ ПОГИБ."},
            {"text": "🪟 Выпрыгнуть в глухое окно витрины", "correct": False, "death": "Стекло было бронированным. Ты оглушил себя ударом, и тебя настигли... ТЫ ПОГИБ."}
        ]
    },
    2: {
        "text": "🕳 **Шаг 2: Вентиляционная шахта.**\n\nТы ползешь по коробу. Впереди развилка: направо пахнет гарью, налево слышен гул мотора, прямо — тишина.",
        "video_id": None,
        "options": [
            {"text": "➡️ Ползти направо (к запаху гари)", "correct": False, "death": "Короб прогорел, металл оборвался, и ты рухнул в огонь... ТЫ ПОГИБ."},
            {"text": "⬅️ Ползти налево (к гулу мотора)", "correct": True},
            {"text": "⬆️ Ползти прямо в тишину", "correct": False, "death": "В темноте притаился спящий мутант. Ты буквально заполз ему в пасть... ТЫ ПОГИБ."}
        ]
    },
    # Для теста сразу сделаем развилку 10-го шага и 100-го
    10: {
        "text": "🚁 **Шаг 10: Выход к вертолетной площадке.**\n\nТы на крыше! Но пилот готов взлететь без тебя, а путь преграждает первый босс.",
        "video_id": None,
        "options": [
            {"text": "🎯 Выстрелить в топливную бочку у ног босса", "correct": True},
            {"text": "🏃 Попытаться пробежать у него под ногами", "correct": False, "death": "Босс схватил тебя одной рукой и сбросил с крыши... ТЫ ПОГИБ."},
            {"text": "📢 Закричать пилоту, чтобы подождал", "correct": False, "death": "Крик только привлек монстра. Он разорвал тебя на части... ТЫ ПОГИБ."}
        ]
    },
    100: {
        "text": "☣️ **ФИНАЛ: Главный бункер.**\n\nПеред тобой панель управления. В колбе находится единственная ампула вакцины. Вертолет спасения ждет снаружи, но система требует запустить самоуничтожение комплекса, чтобы вирус не вырвался наружу.",
        "video_id": None,
        "options": [
            {"text": "💉 Забрать вакцину и сбежать на вертолете", "ending": "bad"},
            {"text": "💥 Запустить самоуничтожение и остаться заблокированным внутри", "ending": "good"},
            {"text": "🧪 Разбить ампулу прямо здесь", "correct": False, "death": "Вирус мгновенно мутировал в воздухе. Ты обратился за 3 секунды... ТЫ ПОГИБ."}
        ]
    }
}

async def send_step_ui(chat_id, user_id):
    player = get_player(user_id)
    step = player["step"]

    # Проверка на Paywall (после 10 шага)
    if step > 10 and not player["is_paid"]:
        pay_text = (
            "🛑 **БЕСПЛАТНАЯ ЧАСТЬ ПРОЙДЕНА!**\n\n"
            "Ты выжил в первых 10 смертельных испытаниях.\n"
            "Впереди ещё 90 шагов, боссы, уникальные анимации смертей и 2 финала.\n\n"
            "💳 **Стоимость полной версии игры:** всего 100 ₽."
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💎 Купить полную игру (100 ₽)", callback_data="buy_game")],
            [InlineKeyboardButton(text="🔄 Проверить оплату", callback_data="check_pay")]
        ])
        await bot.send_message(chat_id=chat_id, text=pay_text, reply_markup=kb, parse_mode="Markdown")
        return

    data = QUEST_DATA.get(step)
    if not data:
        # Заглушка, если шаг пока в разработке
        await bot.send_message(chat_id, f"🚧 Шаг {step} сейчас дописывается! Твой прогресс сохранен.")
        return

    # Формируем 3 кнопки выбора
    buttons = []
    for idx, opt in enumerate(data["options"]):
        buttons.append([InlineKeyboardButton(text=opt["text"], callback_data=f"opt_{idx}")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    # Если есть video_id — шлем видео с описанием, если нет — обычный текст
    if data.get("video_id"):
        await bot.send_video(chat_id=chat_id, video=data["video_id"], caption=data["text"], reply_markup=kb, parse_mode="Markdown")
    else:
        await bot.send_message(chat_id=chat_id, text=data["text"], reply_markup=kb, parse_mode="Markdown")

@dp.message(CommandStart())
async def cmd_start(message: Message):
    player = get_player(message.from_user.id)
    player["step"] = 1
    await message.answer("🎮 **ЗОМБИ-КВЕСТ: 100 ШАГОВ В АД**\n\nПравило одно: на каждом шагу 3 выбора. 2 из них — мгновенная смерть. Выживи до конца!")
    await send_step_ui(message.chat.id, message.from_user.id)

@dp.callback_query(F.data.startswith("opt_"))
async def handle_choice(callback: CallbackQuery):
    idx = int(callback.data.split("_")[1])
    player = get_player(callback.from_user.id)
    step = player["step"]
    data = QUEST_DATA.get(step)

    selected = data["options"][idx]

    # Проверка финалов на 100 шаге
    if "ending" in selected:
        if selected["ending"] == "good":
            text = "🏆 **ХОРОШАЯ КОНЦОВКА: Истинный Герой.**\n\nТы активировал детонатор и запер гермодвери. Взрыв очистил эпицентр заражения. Человечество спасено благодаря твоей жертве!"
        else:
            text = "💀 **ПЛОХАЯ КОНЦОВКА: Эгоизм.**\n\nТы улетел на вертолете с вакциной. Но ты не заметил царапину на своей руке. Через 2 часа пилот был заражен, вертолет рухнул на последний оплот выживших..."
        await callback.message.answer(text, parse_mode="Markdown")
        return

    # Если правильный выбор
    if selected.get("correct"):
        player["step"] += 1
        await callback.message.answer("✅ **Ты выжил!** Двигаемся дальше...")
        await send_step_ui(callback.message.chat.id, callback.from_user.id)
    else:
        # Если выбор привел к смерти
        death_text = f"☠️ {selected.get('death')}\n\nПопробуешь снова с этого шага?"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔁 Попробовать этот шаг снова", callback_data="retry_step")]
        ])
        await callback.message.answer(death_text, reply_markup=kb)

@dp.callback_query(F.data == "retry_step")
async def retry_step(callback: CallbackQuery):
    await send_step_ui(callback.message.chat.id, callback.from_user.id)

@dp.callback_query(F.data == "buy_game")
async def buy_game(callback: CallbackQuery):
    # Тут подключается ссылка на ЮMoney / СБП
    text = (
        "💳 Для оплаты переведите 100 ₽ по ссылке (СБП / Карта):\n"
        "`https://yoomoney.ru/to/твой_номер_кошелька`\n\n"
        "После перевода нажмите кнопку «Проверить оплату»."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Я оплатил", callback_data="check_pay")]
    ])
    await callback.message.answer(text, reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data == "check_pay")
async def check_pay(callback: CallbackQuery):
    # В тестовом режиме для тебя активируем сразу:
    player = get_player(callback.from_user.id)
    player["is_paid"] = True
    await callback.message.answer("🎉 Оплата подтверждена! Полный доступ на 100 шагов открыт!")
    await send_step_ui(callback.message.chat.id, callback.from_user.id)

# --- ПИНГ-СЕРВЕР ДЛЯ БЕСПЛАТНОГО RENDER ---
async def handle_ping(request):
    return web.Response(text="Game running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def main():
    await start_web_server()
    print("Игра запущена!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
