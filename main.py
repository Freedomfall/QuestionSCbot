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

# --- ПОЛНЫЙ СЮЖЕТ БЕСПЛАТНОЙ ЧАСТИ (ШАГИ 1-10) И ФИНАЛ ---
QUEST_DATA = {
    1: {
        "text": "🚪 **Шаг 1: Подсобка магазина.**\n\nДверь выбивают зараженные! Времени секунды. Куда кинешься?",
        "options": [
            {"text": "🏃 В узкий вентиляционный люк", "correct": True},
            {"text": "🪓 Встретить тварей монтировкой", "correct": False, "death": "Мертвецов оказалось слишком много. Они повалили тебя на пол и разорвали... ТЫ ПОГИБ."},
            {"text": "🪟 Выпрыгнуть в глухое окно витрины", "correct": False, "death": "Стекло было бронированным. Ты оглушил себя ударом, и тебя настигли... ТЫ ПОГИБ."}
        ]
    },
    2: {
        "text": "🕳 **Шаг 2: Вентиляционная шахта.**\n\nТы ползешь по коробу. Впереди развилка: направо пахнет гарью, налево слышен гул мотора, прямо — тишина.",
        "options": [
            {"text": "➡️ Ползти направо (к запаху гари)", "correct": False, "death": "Короб прогорел, металл оборвался, и ты рухнул прямо в пламя... ТЫ ПОГИБ."},
            {"text": "⬅️ Ползти налево (к гулу мотора)", "correct": True},
            {"text": "⬆️ Ползти прямо в тишину", "correct": False, "death": "В темноте притаился спящий бегун. Ты заполз прямо к нему в пасть... ТЫ ПОГИБ."}
        ]
    },
    3: {
        "text": "⚙️ **Шаг 3: Машинное отделение.**\n\nТы вывалился к гудящим генераторам. На полу лежит труп охранника с кобурой, но рядом капает оголенный силовой кабель. Как поступишь?",
        "options": [
            {"text": "⚡️ Перепрыгнуть кабель и обыскать тело", "correct": False, "death": "Ты наступил в лужу под напряжением. Разряд в 10 000 вольт остановил сердце... ТЫ ПОГИБ."},
            {"text": "🚪 Осторожно обойти генераторы по сухой трубе", "correct": True},
            {"text": "🧯 Потушить кабель пеной из огнетушителя", "correct": False, "death": "Пена замкнула щиток, произошел мощный взрыв... ТЫ ПОГИБ."}
        ]
    },
    4: {
        "text": "🌆 **Шаг 4: Выход на улицу.**\n\nДверь вывела тебя в темный переулок. На перекрестке бродит толпа слепых зомби, реагирующих на звук. Как преодолеть переулок?",
        "options": [
            {"text": "🍾 Бросить стеклянную бутылку в дальний угол", "correct": True},
            {"text": "🏃 Спринтом рвануть к пожарной лестнице", "correct": False, "death": "Гул твоих шагов всполошил всю стаю. Они догнали тебя у лестницы... ТЫ ПОГИБ."},
            {"text": "🚗 Залезть в брошенный автомобиль и запереться", "correct": False, "death": "Сработала автосигнализация. Машину окружили и выбили стекла... ТЫ ПОГИБ."}
        ]
    },
    5: {
        "text": "🪜 **Шаг 5: Пожарная лестница.**\n\nТы взбираешься наверх, но ступени прогнили от ржавчины. Снизу за ноги уже хватают руки тварей!",
        "options": [
            {"text": "🪓 Бить монтировкой по рукам зомби", "correct": False, "death": "Лестница не выдержала веса и обломилась. Ты упал в толпу... ТЫ ПОГИБ."},
            {"text": "🦘 Прыгнуть на козырек соседнего подъезда", "correct": True},
            {"text": "🧗 Продолжать медленно лезть по центру", "correct": False, "death": "Ты замешкался, твари схватили тебя за щиколотку и стащили вниз... ТЫ ПОГИБ."}
        ]
    },
    6: {
        "text": "🏢 **Шаг 6: Заброшенная квартира.**\n\nЧерез окно ты попал в чужую квартиру. В темноте плачет ребенок. Рядом дверь в коридор и аптечка на столе.",
        "options": [
            {"text": "👶 Подойти и успокоить ребенка", "correct": False, "death": "Это был 'Крикун' — мутант-ловушка. Его ультразвуковой визг оглушил тебя, и он разорвал горло... ТЫ ПОГИБ."},
            {"text": "🚪 Тихо выскользнуть в коридор, не оборачиваясь", "correct": True},
            {"text": "💊 Схватить аптечку со стола", "correct": False, "death": "Стол был заминирован растяжкой прежних хозяев. Взрыв... ТЫ ПОГИБ."}
        ]
    },
    7: {
        "text": "🛗 **Шаг 7: Лифтовой холл.**\n\nВ подъезде застрял старый грузовой лифт. Трос скрипит, двери приоткрыты, а по лестнице поднимается стая.",
        "options": [
            {"text": "🛗 Заскочить в кабину лифта", "correct": False, "death": "Трос лопнул в ту же секунду. Кабина рухнула с 9-го этажа в шахту... ТЫ ПОГИБ."},
            {"text": "🧗 Спуститься по тросу соседней шахты руками", "correct": False, "death": "Руки соскользнули на масле, ты сорвался в бездну... ТЫ ПОГИБ."},
            {"text": "🚪 Забаррикадироваться на этаже пожарным рукавом", "correct": True}
        ]
    },
    8: {
        "text": "🌉 **Шаг 8: Переходной мост на соседнее здание.**\n\nМежду крышами перекинута узкая металлическая балка. Дул ураганный ветер, а снизу — сотни голодных глаз.",
        "options": [
            {"text": "🚶 Быстро пробежать на цыпочках", "correct": False, "death": "Порыв ветра сбил тебя с баланса. Падение с высоты 30 метров... ТЫ ПОГИБ."},
            {"text": "🦧 Ползти на брюхе, обхватив балку руками и ногами", "correct": True},
            {"text": "🪢 Попытаться перепрыгнуть с разбега", "correct": False, "death": "Не хватило буквально полметра. Ты не долетел до парапета... ТЫ ПОГИБ."}
        ]
    },
    9: {
        "text": "🪖 **Шаг 9: Блокпост военных.**\n\nНа крыше соседнего дома разбит пост. Но все солдаты мертвы. Перед тобой рабочий пулемет, ящик с гранатами и рация.",
        "options": [
            {"text": "📻 Выйти в эфир по рации на открытой частоте", "correct": True},
            {"text": "💣 Взять ящик с гранатами без осмотра", "correct": False, "death": "Ящик был заминирован на случай отступления. Сработал детонатор... ТЫ ПОГИБ."},
            {"text": "🎯 Встать за пулемет и начать поливать улицу", "correct": False, "death": "Грохот пулемета привлек огромного Прыгуна, который сбил тебя со спины... ТЫ ПОГИБ."}
        ]
    },
    10: {
        "text": "🚁 **Шаг 10: Финал первой главы (Босс).**\n\nРация ожила: 'Эвакуационный вертолет заходит на посадку!'. Но на посадочную площадку выпрыгивает трехметровый Громила-мутант!",
        "options": [
            {"text": "🎯 Выстрелить из ракетницы в цистерну с топливом за боссом", "correct": True},
            {"text": "🏃 Попытаться проскочить мимо его ног к вертолету", "correct": False, "death": "Громила сгреб тебя в кулак и раздавил ребра... ТЫ ПОГИБ."},
            {"text": "📢 Закричать пилоту вертолета, чтобы открыл огонь", "correct": False, "death": "Пилот испугался монстра, набрал высоту и улетел без тебя. Тварь размазала тебя по бетону... ТЫ ПОГИБ."}
        ]
    },
    100: {
        "text": "☣️ **ФИНАЛ: Главный бункер.**\n\nПеред тобой панель управления. В колбе находится единственная ампула вакцины. Вертолет спасения ждет снаружи, но система требует запустить самоуничтожение комплекса, чтобы вирус не вырвался наружу.",
        "options": [
            {"text": "💉 Забрать вакцину и сбежать на вертолете", "ending": "bad"},
            {"text": "💥 Запустить самоуничтожение и остаться внутри", "ending": "good"},
            {"text": "🧪 Разбить ампулу прямо здесь", "correct": False, "death": "Вирус мгновенно мутировал в воздухе. Ты обратился за 3 секунды... ТЫ ПОГИБ."}
        ]
    }
}

async def send_step_ui(chat_id, user_id):
    player = get_player(user_id)
    step = player["step"]

    # Блокировка после 10 шага (Paywall)
    if step > 10 and not player["is_paid"]:
        pay_text = (
            "🛑 **БЕСПЛАТНАЯ ЧАСТЬ ПРОЙДЕНА!**\n\n"
            "🔥 Ты прошел 10 сложнейших испытаний и выжил!\n"
            "Впереди ещё 90 шагов, боссы, мутации, уникальные смерти и 2 финала.\n\n"
            "💳 **Стоимость полной версии:** 100 ₽."
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💎 Купить полную игру (100 ₽)", callback_data="buy_game")],
            [InlineKeyboardButton(text="🔄 Проверить оплату", callback_data="check_pay")]
        ])
        await bot.send_message(chat_id=chat_id, text=pay_text, reply_markup=kb, parse_mode="Markdown")
        return

    data = QUEST_DATA.get(step)
    if not data:
        await bot.send_message(chat_id, f"🚧 Шаг {step} сейчас дописывается! Твой прогресс сохранен.")
        return

    buttons = []
    for idx, opt in enumerate(data["options"]):
        buttons.append([InlineKeyboardButton(text=opt["text"], callback_data=f"opt_{idx}")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
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

    if "ending" in selected:
        if selected["ending"] == "good":
            text = "🏆 **ХОРОШАЯ КОНЦОВКА: Истинный Герой.**\n\nТы активировал детонатор и запер гермодвери. Взрыв очистил эпицентр заражения. Человечество спасено благодаря твоей жертве!"
        else:
            text = "💀 **ПЛОХАЯ КОНЦОВКА: Эгоизм.**\n\nТы улетел на вертолете с вакциной. Но ты не заметил царапину на руке. Через 2 часа вирус взял верх, и вертолет рухнул на последний оплот выживших..."
        await callback.message.answer(text, parse_mode="Markdown")
        return

    if selected.get("correct"):
        player["step"] += 1
        await callback.message.answer("✅ **Ты выжил!** Двигаемся дальше...")
        await send_step_ui(callback.message.chat.id, callback.from_user.id)
    else:
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
    text = (
        "💳 Для оплаты переведите 100 ₽ по СБП / карте на ЮMoney:\n"
        "`https://yoomoney.ru/to/твой_номер_кошелька`\n\n"
        "После перевода нажмите кнопку «Проверить оплату»."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Я оплатил", callback_data="check_pay")]
    ])
    await callback.message.answer(text, reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data == "check_pay")
async def check_pay(callback: CallbackQuery):
    player = get_player(callback.from_user.id)
    player["is_paid"] = True
    await callback.message.answer("🎉 Оплата подтверждена! Полный доступ открыт!")
    await send_step_ui(callback.message.chat.id, callback.from_user.id)

# Мини веб-сервер для Render
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
