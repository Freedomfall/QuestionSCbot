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

# База игроков
players = {}

def get_player(user_id):
    if user_id not in players:
        players[user_id] = {"step": 1, "is_paid": False}
    return players[user_id]

# --- СЮЖЕТНАЯ БАЗА (ШАГИ 1-20 + ФИНАЛ) ---
# Если у шага есть video_id, бот пришлет видео с кнопками
QUEST_DATA = {
    1: {
        "text": "🚪 **Шаг 1: Подсобка магазина.**\n\nДверь выбивают зараженные! Времени секунды. Куда кинешься?",
        "video_id": None,
        "options": [
            {"text": "🏃 В узкий вентиляционный люк", "correct": True},
            {"text": "🪓 Встретить тварей монтировкой", "correct": False, "death": "Мертвецов оказалось слишком много. Они повалили тебя на пол и разорвали... ТЫ ПОГИБ."},
            {"text": "🪟 Выпрыгнуть в глухое окно витрины", "correct": False, "death": "Стекло было бронированным. Ты оглушил себя ударом, и тебя настигли... ТЫ ПОГИБ."}
        ]
    },
    2: {
        "text": "🕳 **Шаг 2: Вентиляционная шахта.**\n\nТы ползешь по коробу. Впереди развилка: направо пахнет гарью, налево слышен гул мотора, прямо — тишина.",
        "video_id": None,
        "options": [
            {"text": "➡️ Ползти направо (к запаху гари)", "correct": False, "death": "Короб прогорел, металл оборвался, и ты рухнул прямо в пламя... ТЫ ПОГИБ."},
            {"text": "⬅️ Ползти налево (к гулу мотора)", "correct": True},
            {"text": "⬆️ Ползти прямо в тишину", "correct": False, "death": "В темноте притаился спящий бегун. Ты заполз прямо к нему в пасть... ТЫ ПОГИБ."}
        ]
    },
    3: {
        "text": "⚙️ **Шаг 3: Машинное отделение.**\n\nТы вывалился к генераторам. На полу труп с кобурой, но рядом искрит силовой кабель. Как поступишь?",
        "video_id": None,
        "options": [
            {"text": "⚡️ Перепрыгнуть кабель и обыскать тело", "correct": False, "death": "Ты наступил в лужу под напряжением. Разряд в 10 000 вольт остановил сердце... ТЫ ПОГИБ."},
            {"text": "🚪 Осторожно обойти генераторы по сухой трубе", "correct": True},
            {"text": "🧯 Залить щиток пеной из огнетушителя", "correct": False, "death": "Пена вызвала короткое замыкание, произошел мощный взрыв... ТЫ ПОГИБ."}
        ]
    },
    4: {
        "text": "🌆 **Шаг 4: Выход в переулок.**\n\nНа улице бродит толпа слепых зомби, реагирующих на звук. Как преодолеть улицу?",
        "video_id": None,
        "options": [
            {"text": "🍾 Бросить стеклянную бутылку в дальний угол", "correct": True},
            {"text": "🏃 Спринтом рвануть к пожарной лестнице", "correct": False, "death": "Топот привлек всю стаю. Они догнали тебя у ступеней... ТЫ ПОГИБ."},
            {"text": "🚗 Залезть в брошенную машину", "correct": False, "death": "Сработала сирена сигнализации. Машину облепили за секунды... ТЫ ПОГИБ."}
        ]
    },
    5: {
        "text": "🪜 **Шаг 5: Пожарная лестница.**\n\nСтупени скрипят и гнутся, снизу тянутся десятки гнилых рук!",
        "video_id": None,
        "options": [
            {"text": "🪓 Отбиваться монтировкой по рукам", "correct": False, "death": "Лестница обломилась под нагрузкой. Падение вниз... ТЫ ПОГИБ."},
            {"text": "🦘 Прыгнуть на козырек соседнего подъезда", "correct": True},
            {"text": "🧗 Медленно карабкаться дальше вверх", "correct": False, "death": "Тебя схватили за щиколотку и сдернули вниз... ТЫ ПОГИБ."}
        ]
    },
    6: {
        "text": "🏢 **Шаг 6: Заброшенная квартира.**\n\nВ дальней темной комнате тихо плачет ребенок. Рядом открытая дверь в коридор.",
        "video_id": None,
        "options": [
            {"text": "👶 Зайти в комнату проверить ребенка", "correct": False, "death": "Это была тварь-имитатор ('Крикун'). Ультразвуковой крик оглушил тебя, мутант вцепился в горло... ТЫ ПОГИБ."},
            {"text": "🚪 Быстро выскользнуть на лестничную клетку", "correct": True},
            {"text": "📢 Громко крикнуть: 'Тут есть живые?'", "correct": False, "death": "На крик слетелась вся нечисть с нижних этажей... ТЫ ПОГИБ."}
        ]
    },
    7: {
        "text": "🛗 **Шаг 7: Лифтовой холл.**\n\nДвери шахты разворочены, лифт висит на одном скрипящем тросе.",
        "video_id": None,
        "options": [
            {"text": "🛗 Запрыгнуть в кабину лифта", "correct": False, "death": "Трос лопнул, кабина полетела на -3 этаж... ТЫ ПОГИБ."},
            {"text": "🧗 Спускаться по тросу соседней шахты", "correct": False, "death": "Руки скользнули по смазке, ты упал в шахту... ТЫ ПОГИБ."},
            {"text": "🚪 Заблокировать створки лестничной двери пожарным рукавом", "correct": True}
        ]
    },
    8: {
        "text": "🌉 **Шаг 8: Мост между крышами.**\n\nУзкая металлическая балка над пропастью, снизу — рев сотен ходячих.",
        "video_id": None,
        "options": [
            {"text": "🚶 Быстро перебежать на носочках", "correct": False, "death": "Порыв ураганного ветра сорвал тебя вниз... ТЫ ПОГИБ."},
            {"text": "🦧 Ползти, крепко обхватив балку руками и ногами", "correct": True},
            {"text": "🪢 Прыгнуть с разбега", "correct": False, "death": "Не долетел до края всего пару десятков сантиметров... ТЫ ПОГИБ."}
        ]
    },
    9: {
        "text": "🪖 **Шаг 9: Блокпост выживших военных.**\n\nВоенные погибли. На посту остался заряженный тяжелый пулемет и рация.",
        "video_id": None,
        "options": [
            {"text": "📻 Настроить рацию на волну SOS", "correct": True},
            {"text": "💣 Схватить тяжелый цинк с патронами", "correct": False, "death": "Ящик был на взводной растяжке. Взрыв осколков... ТЫ ПОГИБ."},
            {"text": "🎯 Открыть беспорядочный огонь по улице", "correct": False, "death": "Гул пулемета привлек летающих мутантов-нетопырей... ТЫ ПОГИБ."}
        ]
    },
    10: {
        "text": "🚁 **Шаг 10: Босс первой главы — Громила.**\n\nВертолет эвакуации заходит на посадку, но на площадку вырывается 3-метровый мутант!",
        "video_id": None,
        "options": [
            {"text": "🎯 Всадить выстрел из сигнального пистолета в бочку с авиакеросином", "correct": True},
            {"text": "🏃 Попытаться проскользнуть между ног монстра", "correct": False, "death": "Монстр впечатал тебя в асфальт одним ударом кулака... ТЫ ПОГИБ."},
            {"text": "📢 Жестикулировать пилоту, чтобы снизился", "correct": False, "death": "Вертолет сдуло потоком воздуха от удара босса, обломки накрыли тебя... ТЫ ПОГИБ."}
        ]
    },
    11: {
        "text": "🚇 **Шаг 11: Спуск в метро.**\n\nВзрыв бочки ослепил Громилу, но вертолет подбит. Твой единственный путь — нырнуть в разбитый вестибюль станции метро. Эскалатор завален телами.",
        "video_id": None,
        "options": [
            {"text": "🛝 Съехать вниз по гладкому центральному парапету", "correct": True},
            {"text": "👣 Аккуратно спускаться по телам на ступенях", "correct": False, "death": "Одно из тел оказалось еще живым зараженным — мертвая хватка в ногу... ТЫ ПОГИБ."},
            {"text": "💡 Включить мощный прожектор на каске", "correct": False, "death": "Свет привлек стаю пещерных бегунов, обитающих в темноте станции... ТЫ ПОГИБ."}
        ]
    },
    12: {
        "text": "🚉 **Шаг 12: Платформа станции.**\n\nВнизу стоит брошенный поезд. Двери одного вагона приоткрыты, внутри горит тусклая аварийная лампа.",
        "video_id": None,
        "options": [
            {"text": "🏃 Пройти вдоль перрона по краю платформы", "correct": False, "death": "С края путей выскочил мутант-хвататель и утащил тебя под колеса... ТЫ ПОГИБ."},
            {"text": "🚪 Пробраться сквозь вагоны поезда", "correct": True},
            {"text": "🧗 Залезть на крышу вагона", "correct": False, "death": "Контактная сеть над вагонами еще была под током. Разряд... ТЫ ПОГИБ."}
        ]
    },
    13: {
        "text": " вагоне.**\n\nТы внутри поезда. Пол усыпан разбитым стеклом. В дальнем конце вагона стоит спиной зараженный в тяжелой броне спецназа.",
        "video_id": None,
        "options": [
            {"text": "🤫 Снять обувь и бесшумно перешагнуть стекло", "correct": True},
            {"text": "🗡 Подкрасться и вонзить нож в шею со спины", "correct": False, "death": "Броневоротник спецназа не пробился. Зомби развернулся и свернул тебе шею... ТЫ ПОГИБ."},
            {"text": "🚪 Выбить боковую форточку", "correct": False, "death": "Звон стекла привел бронированного монстра в бешенство... ТЫ ПОГИБ."}
        ]
    },
    14: {
        "text": "🛤 **Шаг 14: Вход в темный тоннель.**\n\nПоезд закончился тупиком. Дальше путь только пешком по рельсам вглубь туннеля. Слышен нарастающий гул колес.",
        "video_id": None,
        "options": [
            {"text": "⚡️ Запрыгнуть на контактный рельс у стены", "correct": False, "death": "Рельс оказался под напряжением. Мгновенная смерть от тока... ТЫ ПОГИБ."},
            {"text": "🕳 Вжаться в техническую нишу в стене туннеля", "correct": True},
            {"text": "🏃 Бежать изо всех сил вперед по путям", "correct": False, "death": "Неуправляемая дрезина на полном ходу размазала тебя по путям... ТЫ ПОГИБ."}
        ]
    },
    15: {
        "text": "🐀 **Шаг 15: Затопленный перегон.**\n\nВода доходит до пояса. Вокруг плавает мусор, а на поверхности видны волны от быстро плывущих стай мутировавших крыс.",
        "video_id": None,
        "options": [
            {"text": "🧗 Карабкаться по кабельным полкам под потолком", "correct": True},
            {"text": "🏊 Плыть быстрее кролем наперерез", "correct": False, "death": "Стая плотоядных тварей облепила тебя за 5 секунд... ТЫ ПОГИБ."},
            {"text": "🔥 Поджечь факел и опустить к воде", "correct": False, "death": "Вспыхнуло скопление метана под сводами. Взрыв уничтожил весь отсек... ТЫ ПОГИБ."}
        ]
    },
    16: {
        "text": "🚪 **Шаг 16: Дверь в секретный бункер связи.**\n\nГермодверь с кодовым замком. Рядом три кнопки: красная с символом радиации, желтая с молнией и синяя с ключом.",
        "video_id": None,
        "options": [
            {"text": "🔴 Нажать красную кнопку", "correct": False, "death": "Сработала система дезинфекции — смертельный газ наполнил шлюз... ТЫ ПОГИБ."},
            {"text": "🟡 Нажать желтую кнопку", "correct": False, "death": "Защитная система ударила током высокого напряжения прямо в замок... ТЫ ПОГИБ."},
            {"text": "🔵 Нажать синюю кнопку ручного сброса давления", "correct": True}
        ]
    },
    17: {
        "text": "🧫 **Шаг 17: Биологическая лаборатория.**\n\nВнутри бункера — ряды стеклянных капсул с эмбрионами. Одна капсула разбита, на полу свежая слизь.",
        "video_id": None,
        "options": [
            {"text": "🔦 Идти по следам слизи в операционную", "correct": False, "death": "Тварь ждала на потолке прямо над следом. Прыжок на шею... ТЫ ПОГИБ."},
            {"text": "🥽 Надеть защитный костюм химзащиты со стойки", "correct": True},
            {"text": "🧪 Взять образец вируса с разбитого стекла", "correct": False, "death": "Стеклянный осколок пропорол перчатку. Заражение произошло мгновенно... ТЫ ПОГИБ."}
        ]
    },
    18: {
        "text": "❄️ **Шаг 18: Криокамера.**\n\nЧтобы пройти дальше, нужно пересечь морозильную камеру хранения штаммов. Температура -40°C, датчики движения активированы.",
        "video_id": None,
        "options": [
            {"text": "🏃 Пробежать на максимальной скорости", "correct": False, "death": "Датчики засекли тепловой контур и активировали турели... ТЫ ПОГИБ."},
            {"text": "🧊 Передвигаться ползком за замороженными тушами", "correct": True},
            {"text": "🧯 Разбить стекло пульта управления огнетушителем", "correct": False, "death": "Произошла утечка жидкого азота. Мгновенное замораживание тканей... ТЫ ПОГИБ."}
        ]
    },
    19: {
        "text": "🔬 **Шаг 19: Архив с документами.**\n\nПеред тобой терминал с координатами финального спасательного комплекса. Но за спиной раздается скрежет когтей Лизуна!",
        "video_id": None,
        "options": [
            {"text": "💾 Выдернуть флешку с данными и прыгнуть в люк сброса отходов", "correct": True},
            {"text": "🎯 Попытаться расстрелять его вслепую", "correct": False, "death": "Лизун передвигается быстрее пули. Длинный язык пробил грудь... ТЫ ПОГИБ."},
            {"text": "🚪 Запереться в серверном шкафу", "correct": False, "death": "Монстр вскрыл тонкий металл шкафа как консервную банку... ТЫ ПОГИБ."}
        ]
    },
    20: {
        "text": "🚨 **Шаг 20: Босс второй главы — Мутировавший Ученый.**\n\nТы выпал в шахту утилизации. Из чана с биомассой поднимается гибрид человека и паука, плюющийся кислотой!",
        "video_id": None,
        "options": [
            {"text": "🪓 Перерубить трос подвесного контейнера прямо над мутантом", "correct": True},
            {"text": "🦘 Прыгнуть прямо на него с высоты с ножом", "correct": False, "death": "Кислотная струя сожгла тебя еще в воздухе... ТЫ ПОГИБ."},
            {"text": "🏃 Бежать по кругу в поисках выхода", "correct": False, "death": "Паутина опутала ноги, мутант утащил тебя в кокон... ТЫ ПОГИБ."}
        ]
    },
    100: {
        "text": "☣️ **ФИНАЛ: Главный бункер.**\n\nПеред тобой панель управления. В колбе находится единственная ампула вакцины. Вертолет спасения ждет снаружи, но система требует запустить самоуничтожение комплекса, чтобы вирус не вырвался наружу.",
        "video_id": None,
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
            "🔥 Ты прошел первые 10 сложнейших испытаний и выжил!\n"
            "Впереди ещё 90 шагов, метро, лаборатории, мутанты и 2 финала.\n\n"
            "💳 **Стоимость полной версии:** 100 ₽."
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💎 Купить полную игру (100 ₽)", callback_data="buy_game")],
            [InlineKeyboardButton(text="🔄 Проверить оплату (Тест)", callback_data="check_pay")]
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

    # Если задан video_id — отправляем видео с текстом, иначе просто текст
    if data.get("video_id"):
        await bot.send_video(chat_id=chat_id, video=data["video_id"], caption=data["text"], reply_markup=kb, parse_mode="Markdown")
    else:
        await bot.send_message(chat_id=chat_id, text=data["text"], reply_markup=kb, parse_mode="Markdown")

@dp.message(CommandStart())
async def cmd_start(message: Message):
    player = get_player(message.from_user.id)
    player["step"] = 1
    await message.answer("🎮 **ЗОМБИ-КВЕСТ: 100 ШАГОВ В АД**\n\nНа каждом шагу 3 выбора. 2 из них — смерть. Дойди до финала!")
    await send_step_ui(message.chat.id, message.from_user.id)

# Хэндлер для легкого получения file_id видео или GIF
@dp.message(F.video | F.animation)
async def catch_file_id(message: Message):
    file_id = message.video.file_id if message.video else message.animation.file_id
    await message.reply(
        f"🎬 **File ID твоего медиа:**\n\n`{file_id}`\n\n"
        f"Скопируй его и вставь в нужный шаг в QUEST_DATA в поле 'video_id'."
    )

@dp.callback_query(F.data.startswith("opt_"))
async def handle_choice(callback: CallbackQuery):
    idx = int(callback.data.split("_")[1])
    player = get_player(callback.from_user.id)
    step = player["step"]
    data = QUEST_DATA.get(step)

    selected = data["options"][idx]

    if "ending" in selected:
        if selected["ending"] == "good":
            text = "🏆 **ХОРОШАЯ КОНЦОВКА: Истинный Герой.**\n\nТы взорвал комплекс изнутри. Вирус уничтожен!"
        else:
            text = "💀 **ПЛОХАЯ КОНЦОВКА: Эгоизм.**\n\nТы сбежал на вертолете, но был заражен. Человечество пало..."
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
        "💳 Для тестирования просто нажми кнопку «Проверить оплату (Тест)» ниже!"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Проверить оплату (Тест)", callback_data="check_pay")]
    ])
    await callback.message.answer(text, reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data == "check_pay")
async def check_pay(callback: CallbackQuery):
    player = get_player(callback.from_user.id)
    player["is_paid"] = True
    await callback.message.answer("🎉 Доступ открыт! Погнали дальше!")
    await send_step_ui(callback.message.chat.id, callback.from_user.id)

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
