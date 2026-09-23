import os
import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# Токен берется из настроек облака
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("Токен BOT_TOKEN не задан в переменных окружения!")

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Состояния для диалога
class SendSecret(StatesGroup):
    target_user_id = State()
    waiting_for_message = State()

@dp.message(CommandStart(deep_link=True))
async def cmd_start_deeplink(message: Message, command: CommandObject, state: FSMContext):
    target_id = command.args
    # Если человек перешел по своей же ссылке
    if target_id == str(message.from_user.id):
        await message.answer("Это ваша личная ссылка! Отправьте её друзьям или поставьте в статус.")
        return

    await state.update_data(target_id=target_id)
    await state.set_state(SendSecret.waiting_for_message)
    await message.answer(
        "🤫 **Напишите любое сообщение или вопрос.**\n\n"
        "Получатель увидит текст, но никогда не узнает, кто его отправил (полная анонимность)."
    )

@dp.message(CommandStart())
async def cmd_start_regular(message: Message):
    bot_info = await bot.get_me()
    my_link = f"https://t.me/{bot_info.username}?start={message.from_user.id}"
    
    text = (
        f"👋 **Привет, {message.from_user.first_name}!**\n\n"
        f"Здесь тебе могут писать анонимные сообщения.\n\n"
        f"🔗 **Твоя персональная ссылка:**\n`{my_link}`\n\n"
        f"Скопируй её и выложи в свой канал, статус Telegram, VK или сторис!"
    )
    await message.answer(text, parse_mode="Markdown")

@dp.message(SendSecret.waiting_for_message)
async def process_secret_message(message: Message, state: FSMContext):
    data = await state.get_data()
    target_id = data.get("target_id")

    try:
        # Кнопка для ответа
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="💬 Ответить анонимно", url=f"https://t.me/{(await bot.get_me()).username}?start={message.from_user.id}")
        ]])

        # Отправляем сообщение адресату
        await bot.send_message(
            chat_id=target_id,
            text=f"📩 **Вам пришло новое анонимное сообщение:**\n\n{message.text}",
            reply_markup=kb,
            parse_mode="Markdown"
        )
        await message.answer("🚀 Ваше сообщение успешно отправлено анонимно!")
    except Exception:
        await message.answer("❌ Не удалось доставить сообщение. Возможно, пользователь заблокировал бота.")
    
    await state.clear()

async def main():
    print("Бот запускается...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
