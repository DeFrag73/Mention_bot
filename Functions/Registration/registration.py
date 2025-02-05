from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import MessageHandler, filters, CallbackContext, ConversationHandler, CommandHandler
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
import os
from dotenv import load_dotenv

# Стани для ConversationHandler
NAME, PATRONYMIC, SURNAME, GROUP = range(4)

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI')
DB_NAME = os.getenv('MONGO_DATABASE')


def check_mongo_connection():
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        client.server_info()
        print("Підключення до MongoDB успішне!")
        return client
    except ConnectionFailure as e:
        print(f"Помилка підключення до MongoDB: {e}")
        return None


client = check_mongo_connection()
if client:
    db = client[DB_NAME]
    users_collection = db['users']
else:
    print("Не вдалося підключитися до MongoDB. Перевірте налаштування.")
    exit(1)


async def start_registration(update: Update, context: CallbackContext) -> int:
    if update.message.chat.type != "private":
        keyboard = [[InlineKeyboardButton("Перейти в приватний чат", url=f"https://t.me/{context.bot.username}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "Будь ласка, перейдіть в приватний чат для реєстрації. І виберіть команду /registration",
            reply_markup=reply_markup
        )
        return ConversationHandler.END

    user = update.message.from_user
    context.user_data['user_id'] = user.id
    context.user_data['username'] = user.username if user.username else "Невідомий"

    await update.message.reply_text(
        "Будь ласка, введіть ваше повне ім'я українською мовою:\n\n"
        "Щоб скасувати реєстрацію напишіть слово \"скасувати\"",
    )
    return NAME


async def get_name(update: Update, context: CallbackContext) -> int:
    if update.message.text.lower() == 'скасувати':
        await cancel(update, context)
        return ConversationHandler.END

    context.user_data['name'] = update.message.text
    await update.message.reply_text("Будь ласка, введіть ваше по батькові українською мовою:")
    return PATRONYMIC


async def get_patronymic(update: Update, context: CallbackContext) -> int:
    if update.message.text.lower() == 'скасувати':
        await cancel(update, context)
        return ConversationHandler.END

    context.user_data['patronymic'] = update.message.text
    await update.message.reply_text("Будь ласка, введіть ваше прізвище українською мовою:")
    return SURNAME


async def get_surname(update: Update, context: CallbackContext) -> int:
    if update.message.text.lower() == 'скасувати':
        await cancel(update, context)
        return ConversationHandler.END

    context.user_data['surname'] = update.message.text
    await update.message.reply_text("Будь ласка, введіть номер вашої групи (три цифри):")
    return GROUP


async def save_user_data(update: Update, context: CallbackContext) -> None:
    if update.message.text.lower() == 'скасувати':
        await cancel(update, context)
        return

    user_id = context.user_data.get('user_id')
    username = context.user_data.get('username')
    name = context.user_data.get('name')
    patronymic = context.user_data.get('patronymic')
    surname = context.user_data.get('surname')
    group = update.message.text

    if not all([user_id, name, patronymic, surname, group]):
        await update.message.reply_text("Помилка: не всі дані були отримані. Спробуйте ще раз.")
        return

    full_name = f"{name} {patronymic} {surname}"

    try:
        result = users_collection.update_one(
            {'user_id': user_id},
            {'$set': {
                'username': username,
                'full_name': full_name,
                'group': group,
                'role': 'учасник комісії'
            }},
            upsert=True
        )

        if result.upserted_id or result.modified_count > 0:
            await update.message.reply_text(f"Дякуємо за реєстрацію, {full_name}! Ваша група: {group}.")
        else:
            await update.message.reply_text("Помилка при збереженні даних. Спробуйте ще раз.")
    except Exception as e:
        await update.message.reply_text("Сталася помилка при збереженні даних. Спробуйте пізніше.")
        print(f"Помилка при роботі з базою даних: {e}")


async def cancel(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text('Реєстрацію скасовано.')
    return ConversationHandler.END


def get_registration_handler():
    return ConversationHandler(
        entry_points=[CommandHandler('registration', start_registration)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            PATRONYMIC: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_patronymic)],
            SURNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_surname)],
            GROUP: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_user_data)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
