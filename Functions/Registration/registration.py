import logging

import asyncio
import re

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import MessageHandler, filters, CallbackContext, ConversationHandler, CommandHandler, \
    CallbackQueryHandler
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
import os
from dotenv import load_dotenv

# Налаштування логування
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        # logging.FileHandler('bot_logs.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Стани для ConversationHandler
NAME, PATRONYMIC, SURNAME, GROUP, EMPLOYMENT = range(5)

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI')
DB_NAME = os.getenv('MONGO_DATABASE')


def check_mongo_connection():
    logger.info("Спроба підключення до MongoDB...")
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        client.server_info()
        logger.info("Підключення до MongoDB успішне!")
        return client
    except ConnectionFailure as e:
        logger.error(f"Помилка підключення до MongoDB: {e}")
        return None


client = check_mongo_connection()
if client:
    db = client[DB_NAME]
    users_collection = db['INFO-Members']
    logger.info(f"Підключено до бази даних: {DB_NAME}")
else:
    logger.critical("Не вдалося підключитися до MongoDB. Завершення роботи.")
    exit(1)


async def start_registration(update: Update, context: CallbackContext) -> int:
    logger.info(f"Користувач {update.effective_user.id} розпочав реєстрацію")

    if update.message.chat.type != "private":
        logger.warning(f"Спроба реєстрації не в приватному чаті від користувача {update.effective_user.id}")
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
    logger.info(f"Збережено початкові дані користувача: ID={user.id}, Username={user.username}")

    await update.message.reply_text(
        "Будь ласка, введіть ваше повне ім'я українською мовою:\n\n"
        "Щоб скасувати реєстрацію напишіть слово \"скасувати\"",
    )
    return NAME


async def get_name(update: Update, context: CallbackContext) -> int:
    user_input = update.message.text
    logger.info(f"Отримано ім'я від користувача {update.effective_user.id}: {user_input}")

    if user_input.lower() == 'скасувати':
        logger.info(f"Користувач {update.effective_user.id} скасував реєстрацію на етапі введення імені")
        await cancel(update, context)
        return ConversationHandler.END

    context.user_data['name'] = user_input
    await update.message.reply_text("Будь ласка, введіть ваше по батькові українською мовою:")
    return PATRONYMIC


async def get_patronymic(update: Update, context: CallbackContext) -> int:
    user_input = update.message.text
    logger.info(f"Отримано по батькові від користувача {update.effective_user.id}: {user_input}")

    if user_input.lower() == 'скасувати':
        logger.info(f"Користувач {update.effective_user.id} скасував реєстрацію на етапі введення по батькові")
        await cancel(update, context)
        return ConversationHandler.END

    context.user_data['patronymic'] = user_input
    await update.message.reply_text("Будь ласка, введіть ваше прізвище українською мовою:")
    return SURNAME


async def get_surname(update: Update, context: CallbackContext) -> int:
    user_input = update.message.text
    logger.info(f"Отримано прізвище від користувача {update.effective_user.id}: {user_input}")

    if user_input.lower() == 'скасувати':
        logger.info(f"Користувач {update.effective_user.id} скасував реєстрацію на етапі введення прізвища")
        await cancel(update, context)
        return ConversationHandler.END

    context.user_data['surname'] = user_input
    await update.message.reply_text("Будь ласка, введіть номер вашої групи (три цифри):")
    return GROUP


async def get_group(update: Update, context: CallbackContext) -> int:
    user_input = update.message.text
    logger.info(f"Отримано групу від користувача {update.effective_user.id}: {user_input}")

    if user_input.lower() == 'скасувати':
        logger.info(f"Користувач {update.effective_user.id} скасував реєстрацію на етапі введення групи")
        await cancel(update, context)
        return ConversationHandler.END

    # Перевірка формату групи (три цифри)
    if not re.match(r'^\d{3}$', user_input):
        logger.warning(f"Користувач {update.effective_user.id} ввів некоректний номер групи: {user_input}")

        # Надсилаємо повідомлення про помилку
        error_message = await update.message.reply_text(
            "❌ Помилка: Номер групи має складатися з трьох цифр!\n"
            "Спробуйте ще раз."
        )

        # Видаляємо повідомлення про помилку через 3 секунди
        await asyncio.sleep(3)
        await error_message.delete()

        return GROUP

    context.user_data['group'] = user_input

    keyboard = [
        [
            InlineKeyboardButton("Копірайтинг ✍️", callback_data="copywriting"),
            InlineKeyboardButton("Відео монтаж 🎥", callback_data="video"),
            InlineKeyboardButton("Дизайнер 🎨", callback_data="design")
        ],
        [InlineKeyboardButton("Завершити вибір ✅", callback_data="done")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message = await update.message.reply_text(
        "Оберіть, що вам більше подобається (можна обрати декілька варіантів):",
        reply_markup=reply_markup
    )
    logger.info(f"Відправлено клавіатуру з напрямками користувачу {update.effective_user.id}")

    context.user_data['message_id'] = message.message_id
    context.user_data['employment_types'] = []
    return EMPLOYMENT



async def handle_employment_choice(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    logger.info(f"Отримано callback_data: {query.data} від користувача {query.from_user.id}")

    try:
        if query.data == "done":
            if not context.user_data.get('employment_types'):
                logger.warning(f"Користувач {query.from_user.id} намагається завершити без вибору напрямків")
                # Показуємо спливаюче повідомлення
                await query.answer(
                    text="⚠️ Виберіть хоча б один напрямок!",
                    show_alert=True
                )
                # Надсилаємо нове повідомлення
                error_message = await query.message.reply_text(
                    "❌ Помилка: Ви не обрали жодного напрямку!\n"
                    "Будь ласка, оберіть хоча б один варіант."
                )
                # Видаляємо повідомлення через 3 секунди
                await asyncio.sleep(3)
                await error_message.delete()

                return EMPLOYMENT

            logger.info("Початок збереження даних користувача")
            user_id = context.user_data.get('user_id')
            username = context.user_data.get('username')
            name = context.user_data.get('name')
            patronymic = context.user_data.get('patronymic')
            surname = context.user_data.get('surname')
            group = context.user_data.get('group')
            employment_types = context.user_data.get('employment_types', [])

            if not all([user_id, name, patronymic, surname, group]):
                logger.error(f"Неповні дані користувача {user_id}: {context.user_data}")
                await query.message.reply_text("Помилка: не всі дані були отримані. Спробуйте ще раз.")
                return ConversationHandler.END

            full_name = f"{name} {patronymic} {surname}"
            logger.info(f"Спроба збереження даних для користувача {user_id}: {full_name}")

            try:
                result = users_collection.update_one(
                    {'user_id': user_id},
                    {'$set': {
                        'username': username,
                        'full_name': full_name,
                        'group': group,
                        'role': 'учасник комісії',
                        'type_of_employment': employment_types
                    }},
                    upsert=True
                )

                if result.upserted_id or result.modified_count > 0:
                    logger.info(f"Успішно збережено дані користувача {user_id}")
                    await query.message.edit_text(
                        f"Дякуємо за реєстрацію, {full_name}!\n"
                        f"Ваша група: {group}\n"
                        f"Обрані напрямки: {', '.join(employment_types)}"
                    )
                else:
                    logger.error(f"Помилка при збереженні даних користувача {user_id}")
                    await query.message.edit_text("Помилка при збереженні даних. Спробуйте ще раз.")
            except Exception as e:
                logger.error(f"Помилка бази даних для користувача {user_id}: {str(e)}")
                await query.message.edit_text("Сталася помилка при збереженні даних. Спробуйте пізніше.")

            return ConversationHandler.END

        employment_types = context.user_data.get('employment_types', [])
        employment_names = {
            "copywriting": "Копірайтинг",
            "video": "Відео монтаж",
            "design": "Дизайнер"
        }

        if query.data in employment_types:
            employment_types.remove(query.data)
            logger.info(f"Видалено напрямок {query.data} для користувача {query.from_user.id}")
        else:
            employment_types.append(query.data)
            logger.info(f"Додано напрямок {query.data} для користувача {query.from_user.id}")

        context.user_data['employment_types'] = employment_types

        selected = "\n".join([f"✅ {employment_names[emp]}" for emp in employment_types])
        if not selected:
            selected = "Ще нічого не обрано"

        await query.message.edit_text(
            f"Оберіть, що вам більше подобається:\n\n"
            f"Обрані напрямки:\n{selected}",
            reply_markup=query.message.reply_markup
        )

        return EMPLOYMENT

    except Exception as e:
        logger.error(f"Неочікувана помилка в handle_employment_choice: {str(e)}")
        await query.message.reply_text("Сталася неочікувана помилка. Спробуйте пізніше.")
        return ConversationHandler.END


async def cancel(update: Update, context: CallbackContext) -> int:
    logger.info(f"Користувач {update.effective_user.id} скасував реєстрацію")
    await update.message.reply_text('Реєстрацію скасовано.')
    return ConversationHandler.END


def get_registration_handler():
    logger.info("Створення обробника реєстрації")
    return ConversationHandler(
        entry_points=[CommandHandler('registration', start_registration)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            PATRONYMIC: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_patronymic)],
            SURNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_surname)],
            GROUP: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_group)],
            EMPLOYMENT: [CallbackQueryHandler(handle_employment_choice)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        per_message=False
    )
