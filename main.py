import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)

from Functions.Registration.registration import get_registration_handler
from Functions.Init_group.init_users import get_init_handler, init_user
from Functions.Mention_all.mention_all import get_mention_handler, react_to_new_messages
from Functions.Reminder.reminder import setup_reminder_functionality
from Functions.Anti_spam.antispam_handlers import SpamHandlers, check_spam_decorator
from Functions.Greating_members_with_birthday.Birthday import setup_birthday_handler
from Functions.New_task_notification.Task_notification import TaskNotification
from Functions.Making_groups_of_peoples.Making_Group import get_group_creation_handler
from  Functions.Logger.Logger_config import logger

# Завантаження змінних середовища
load_dotenv()

# Конфігураційні змінні
config = {
    'TELEGRAM_BOT_TOKEN': os.getenv('TELEGRAM_BOT_TOKEN'),
    'TELEGRAM_API_ID': os.getenv('TELEGRAM_API_ID'),
    'TELEGRAM_API_HASH': os.getenv('TELEGRAM_API_HASH'),
    'PHONE_NUMBER': os.getenv('TELEGRAM_PHONE_NUMBER'),
    'CREDENTIALS_FILE': os.getenv('CREDENTIALS_FILE'),
    'SPREADSHEET_NAME': os.getenv('SPREADSHEET_NAME'),
    'MONGODB_URI': os.getenv('MONGO_URI'),
    'ADMIN_ID': int(os.getenv('ADMIN_ID')),
    'DATABASE_NAME': os.getenv('MONGO_DATABASE'),
    'GEMINI_API_KEY': os.getenv('GEMINI_API_KEY'),
    'WORK_GROUP_ID': os.getenv('INFO_CHAT_ID')
}

# Створення глобального екземпляра обробника антиспаму
spam_handlers = SpamHandlers(config['MONGODB_URI'], config['ADMIN_ID'])


@check_spam_decorator
async def bot_added_to_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробка події додавання бота до групи."""
    chat = update.effective_chat
    welcome_message = (
        "👋 Привіт! Я багатофункціональний посіпака для управління групою.\n\n"
        "📊 Мої основні можливості:\n"
        "• Миттєві згадки користувачів\n"
        "🚀 Для початку роботи, будь ласка, виконайте команду /init\n\n"
        "❗ Якщо ви учасник комісії то натисніть /registration\n"
    )

    try:
        await context.bot.send_message(
            chat_id=chat.id,
            text=welcome_message
        )
    except Exception as e:
        logger.error(f"Помилка при надсиланні привітального повідомлення: {e}")


async def new_member_added(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробка події додавання нового учасника до групи."""
    new_members = update.message.new_chat_members
    chat = update.effective_chat
    bot = context.bot

    # Перевірка чи новий учасник - це бот
    for member in new_members:
        if member.id == bot.id:
            return await bot_added_to_group(update, context)

    try:
        await init_user(update, context)
        welcome_text = "🎉 Вітаємо нового учасника групи! Інформацію про користувача додано до бази."
        await context.bot.send_message(
            chat_id=chat.id,
            text=welcome_text
        )
    except Exception as e:
        logger.error(f"Помилка при ініціалізації нового користувача: {e}")


def main():
    """Головна функція запуску бота."""
    try:
        # Перевірка конфігурації
        required_config = ['MONGODB_URI', 'DATABASE_NAME', 'GEMINI_API_KEY', 'WORK_GROUP_ID']
        missing_params = [param for param in required_config if not config.get(param)]
        if missing_params:
            raise ValueError(f"Відсутні обов'язкові параметри конфігурації: {', '.join(missing_params)}")

        # Ініціалізація бота
        app = ApplicationBuilder().token(config['TELEGRAM_BOT_TOKEN']).build()
        logger.info("Запуск бота...")

        # Налаштування обробників
        setup_birthday_handler(app, config) # /test_birthday
        logger.info("Birthday handler встановлено")

        # Налаштування антиспаму
        spam_handlers_bot = SpamHandlers(config['MONGODB_URI'], config['ADMIN_ID'])
        app.bot_data['spam_handlers'] = spam_handlers_bot
        for handler in spam_handlers_bot.get_handlers():
            app.add_handler(handler) # /whitelist_add /whitelist_remove /reset_warnings

        # Додавання обробників команд
        handlers = [
            CommandHandler('start', bot_added_to_group),
            MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_member_added),
            get_registration_handler(), # /registration
            get_init_handler(), # /init
            get_mention_handler(), # /mention_all
        ]

        # Додаємо handlers для груп окремо
        group_handlers = get_group_creation_handler() # /mention_group /create_user_group /
        handlers.extend(group_handlers)

        for handler in handlers:
            app.add_handler(handler)

        task_notification = TaskNotification() # /thread_info /push_task
        task_notification.register_handlers(app)

        # Налаштування періодичної перевірки завдань
        app.job_queue.run_repeating(
            task_notification.check_and_send_tasks,
            interval=3600,  # перевіряти кожну годину
            first=10  # перша перевірка через 10 секунд після запуску
        )

        # Налаштування додаткової функціональності
        setup_reminder_functionality(app) # /check /test_reminder /test_message /set_daily_reminder /show_reminder_schedule
        app.add_handler(MessageHandler(filters.ALL, react_to_new_messages))

        logger.info("Всі обробники успішно встановлено")
        logger.info("Запускаємо бота...")

        # Запуск бота
        app.run_polling(allowed_updates=Update.ALL_TYPES)

    except Exception as e:
        logger.error(f"Критична помилка при запуску бота: {str(e)}", exc_info=True)
        raise


if __name__ == '__main__':
    main()
