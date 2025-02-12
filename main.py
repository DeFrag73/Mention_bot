import logging
import asyncio
import json
import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (ApplicationBuilder, CommandHandler, MessageHandler, filters,
                          ContextTypes)
import gspread
from google.oauth2.service_account import Credentials
import functools

from Functions.Registration.registration import get_registration_handler
from Functions.Init_group.init_users import get_init_handler, init_user
from Functions.Mention_all.mention_all import get_mention_handler, react_to_new_messages
from Functions.Reminder.reminder import setup_reminder_functionality
from Functions.Anti_spam.antispam_handlers import SpamHandlers, check_spam_decorator, admin_only

# from Functions.Reminder.reminder import check_connect_to_sheet

# Logging setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

load_dotenv()

TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
API_ID = os.getenv('TELEGRAM_API_ID')
API_HASH = os.getenv('TELEGRAM_API_HASH')
PHONE_NUMBER = os.getenv('TELEGRAM_PHONE_NUMBER')
CREDENTIALS_FILE = os.getenv('CREDENTIALS_FILE')
SPREADSHEET_NAME = os.getenv('SPREADSHEET_NAME')
MONGODB_URI = os.getenv('MONGODB_URI')
ADMIN_ID = int(os.getenv('ADMIN_ID'))

# Створюємо глобальний екземпляр обробника антиспаму
spam_handlers = SpamHandlers(MONGODB_URI, ADMIN_ID)

@check_spam_decorator
async def bot_added_to_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Функція спрацьовує, коли бота додають до групи.
    Надсилає вітальне повідомлення з описом та інструкцією з ініціалізації.
    """
    chat = update.effective_chat

    welcome_message = (
        "👋 Привіт! Я багатофункціональний посіпака для управління групою.\n\n"
        "📊 Мої основні можливості:\n"
        "• Миттєві згадки користувачів\n"
        "🚀 Для початку роботи, будь ласка, виконайте команду /init\n"
    )

    try:
        await context.bot.send_message(
            chat_id=chat.id,
            text=welcome_message
        )
    except Exception as e:
        logging.error(f"Помилка при надсиланні привітального повідомлення: {e}")


async def new_member_added(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Функція спрацьовує при додаванні нового учасника до групи.
    Автоматично викликає функцію ініціалізації групи.
    """
    # Перевірка, чи є новий учасник
    new_members = update.message.new_chat_members
    chat = update.effective_chat

    # Перевіряємо, чи серед нових учасників є bot
    bot = context.bot
    for member in new_members:
        if member.id == bot.id:
            # Якщо доданий сам бот, використовуємо bot_added_to_group
            return await bot_added_to_group(update, context)

    # Виклик функції ініціалізації
    try:
        await init_user(update, context)

        # Додаткове привітання для нових учасників (за бажанням)
        welcome_text = "🎉 Вітаємо нового учасника групи! Інформацію про користувача додано до бази."
        await context.bot.send_message(
            chat_id=chat.id,
            text=welcome_text
        )
    except Exception as e:
        logging.error(f"Помилка при ініціалізації групи після додавання користувача: {e}")


# Main function to run the bot
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # Створюємо обробник антиспаму і зберігаємо його в bot_data як значення словника
    spam_handlers_bot = SpamHandlers(MONGODB_URI, ADMIN_ID)
    app.bot_data['spam_handlers'] = spam_handlers_bot

    # Додаємо обробники антиспаму
    for handler in spam_handlers_bot.get_handlers():
        app.add_handler(handler)

    # Handlers for different commands and button clicks
    app.add_handler(CommandHandler('start', bot_added_to_group))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_member_added))

    # Обробник для команди /registration
    registration_handler = get_registration_handler()
    app.add_handler(registration_handler)

    # Обробник для ініціалізації користувачів в групі
    init_handler = get_init_handler()
    app.add_handler(init_handler)

    # Обробник для згадки всіх користувачів у групі
    mention_handler = get_mention_handler()
    app.add_handler(mention_handler)

    setup_reminder_functionality(app)
    app.add_handler(MessageHandler(filters.ALL, react_to_new_messages))

    # Запуск Бота
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
