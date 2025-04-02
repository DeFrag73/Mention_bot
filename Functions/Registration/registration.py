import logging

import asyncio
import re
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import MessageHandler, filters, CallbackContext, ConversationHandler, CommandHandler, \
    CallbackQueryHandler
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
import os
from dotenv import load_dotenv
from Functions.Anti_spam.antispam_handlers import check_spam_decorator, admin_only
from Functions.Logger.Logger_config import logger

# Стани для ConversationHandler
NAME, PATRONYMIC, SURNAME, GROUP, EMPLOYMENT, BIRTHDAY, PHONE = range(7)

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

# Додаємо нові константи на початку файлу після імпортів
# Константи для валідації
MAX_NAME_LENGTH = 25
MIN_AGE = 16
GROUP_PATTERN = r'^\d{3}$'
UKRAINIAN_NAME_PATTERN = r'^[А-ЩЬЮЯҐЄІЇа-щьюяґєії\'\-]+$'
DATE_PATTERN = r'^(0[1-9]|[12][0-9]|3[01])\.(0[1-9]|1[0-2])\.\d{4}$'
PHONE_PATTERN = r'^(?:\+380|380|0)\d{9}$'

# Константи для напрямків роботи
EMPLOYMENT_TYPES = {
    "copywriting": "Копірайтинг",
    "video": "Відео монтаж",
    "design": "Дизайнер",
    "photo": "Фотограф"
}

# Константи для повідомлень про помилки
ERROR_MESSAGES = {
    'name_length': "❌ Помилка: Ім'я не може бути довшим за 25 символів!",
    'name_chars': "❌ Помилка: Ім'я має містити тільки українські літери!",
    'surname_length': "❌ Помилка: Прізвище не може бути довшим за 25 символів!",
    'surname_chars': "❌ Помилка: Прізвище має містити тільки українські літери!",
    'date_format': "❌ Помилка: Некоректний формат дати!",
    'future_date': "❌ Помилка: Дата народження не може бути в майбутньому!",
    'min_age': "❌ Помилка: Вік повинен бути не менше 16 років!",
    'group_format': "❌ Помилка: Номер групи має складатися з трьох цифр!",
    'phone_format': "❌ Помилка: Некоректний формат номера телефону! "
                    "Введіть у форматі +380XXXXXXXXX, 380XXXXXXXXX або 0XXXXXXXXX"
}

@check_spam_decorator
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
        "Будь ласка, введіть тільки ваше ім'я українською мовою таке яке воно є студентській пошті:\n\n"
        "Щоб скасувати реєстрацію напишіть слово \"скасувати\"",
    )
    return NAME

@check_spam_decorator
async def get_name(update: Update, context: CallbackContext) -> int:
    user_input = update.message.text
    logger.info(f"Отримано ім'я від користувача {update.effective_user.id}: {user_input}")

    if user_input.lower() == 'скасувати':
        logger.info(f"Користувач {update.effective_user.id} скасував реєстрацію на етапі введення імені")
        await cancel(update, context)
        return ConversationHandler.END

    if len(user_input) > MAX_NAME_LENGTH:
        logger.warning(f"Користувач {update.effective_user.id} ввів задовге ім'я: {user_input}")
        error_message = await update.message.reply_text(
            ERROR_MESSAGES['name_length']
        )
        await asyncio.sleep(3)
        await error_message.delete()
        return NAME

    if not re.match(UKRAINIAN_NAME_PATTERN, user_input):
        logger.warning(f"Користувач {update.effective_user.id} ввів ім'я з недопустимими символами: {user_input}")
        error_message = await update.message.reply_text(
            ERROR_MESSAGES['name_chars']
        )
        await asyncio.sleep(3)
        await error_message.delete()
        return NAME

    context.user_data['name'] = user_input
    await update.message.reply_text("Будь ласка, введіть ваше по батькові:")
    return PATRONYMIC

@check_spam_decorator
async def get_patronymic(update: Update, context: CallbackContext) -> int:
    user_input = update.message.text
    logger.info(f"Отримано по батькові від користувача {update.effective_user.id}: {user_input}")

    if user_input.lower() == 'скасувати':
        logger.info(f"Користувач {update.effective_user.id} скасував реєстрацію на етапі введення по батькові")
        await cancel(update, context)
        return ConversationHandler.END

    if len(user_input) > MAX_NAME_LENGTH:
        logger.warning(f"Користувач {update.effective_user.id} ввів задовге по батькові: {user_input}")
        error_message = await update.message.reply_text(
            "❌ Помилка: По батькові не може бути довшим за 25 символів!\n"
            "Будь ласка, введіть коротше по батькові."
        )
        await asyncio.sleep(3)
        await error_message.delete()
        return PATRONYMIC

    if not re.match(UKRAINIAN_NAME_PATTERN, user_input):
        logger.warning(
            f"Користувач {update.effective_user.id} ввів по батькові з недопустимими символами: {user_input}")
        error_message = await update.message.reply_text(
            "❌ Помилка: По батькові має містити тільки українські літери!\n"
            "Можна використовувати апостроф (') та дефіс (-)."
        )
        await asyncio.sleep(3)
        await error_message.delete()
        return PATRONYMIC

    context.user_data['patronymic'] = user_input
    await update.message.reply_text("Будь ласка, введіть ваше прізвище:")
    return SURNAME

@check_spam_decorator
async def get_surname(update: Update, context: CallbackContext) -> int:
    user_input = update.message.text
    logger.info(f"Отримано прізвище від користувача {update.effective_user.id}: {user_input}")

    if user_input.lower() == 'скасувати':
        logger.info(f"Користувач {update.effective_user.id} скасував реєстрацію на етапі введення прізвища")
        await cancel(update, context)
        return ConversationHandler.END

    if len(user_input) > MAX_NAME_LENGTH:
        logger.warning(f"Користувач {update.effective_user.id} ввів задовге прізвище: {user_input}")
        error_message = await update.message.reply_text(
            ERROR_MESSAGES['surname_length']
        )
        await asyncio.sleep(3)
        await error_message.delete()
        return SURNAME

    if not re.match(UKRAINIAN_NAME_PATTERN, user_input):
        logger.warning(f"Користувач {update.effective_user.id} ввів прізвище з недопустимими символами: {user_input}")
        error_message = await update.message.reply_text(
            ERROR_MESSAGES['surname_chars']
        )
        await asyncio.sleep(3)
        await error_message.delete()
        return SURNAME

    context.user_data['surname'] = user_input
    await update.message.reply_text(
        "Будь ласка, введіть вашу дату народження у форматі ДД.ММ.РРРР\n"
        "Наприклад: 01.01.2000"
    )
    return BIRTHDAY

@check_spam_decorator
async def get_birthday(update: Update, context: CallbackContext) -> int:
    if not update.message:
        logger.warning(f"Отримано оновлення без повідомлення від користувача {update.effective_user.id}")
        return BIRTHDAY

    user_input = update.message.text
    logger.info(f"Отримано дату народження від користувача {update.effective_user.id}: {user_input}")

    if user_input.lower() == 'скасувати':
        logger.info(f"Користувач {update.effective_user.id} скасував реєстрацію на етапі введення дати народження")
        await cancel(update, context)
        return ConversationHandler.END

    # Перевірка формату дати
    if not re.match(DATE_PATTERN, user_input):
        logger.warning(f"Користувач {update.effective_user.id} ввів некоректну дату: {user_input}")
        error_message = await update.message.reply_text(
            ERROR_MESSAGES['date_format']
        )
        await asyncio.sleep(3)
        await error_message.delete()
        return BIRTHDAY

    try:
        # Перевірка валідності дати
        day, month, year = map(int, user_input.split('.'))
        birthday_date = datetime(year, month, day)

        # Перевірка що дата не в майбутньому
        if birthday_date > datetime.now():
            error_message = await update.message.reply_text(
                ERROR_MESSAGES['future_date']
            )
            await asyncio.sleep(3)
            await error_message.delete()
            return BIRTHDAY

        # Перевірка мінімального віку (наприклад, 16 років)
        min_birth_year = datetime.now().year - 16
        if year > min_birth_year:
            error_message = await update.message.reply_text(
                ERROR_MESSAGES['min_age']
            )
            await asyncio.sleep(3)
            await error_message.delete()
            return BIRTHDAY

        context.user_data['birthday'] = user_input
        await update.message.reply_text("Будь ласка, введіть номер вашої групи (три цифри):")
        return GROUP

    except ValueError:
        logger.warning(f"Користувач {update.effective_user.id} ввів некоректну дату: {user_input}")
        error_message = await update.message.reply_text(
            "❌ Помилка: Введена дата недійсна!\n"
            "Перевірте правильність введених даних."
        )
        await asyncio.sleep(3)
        await error_message.delete()
        return BIRTHDAY

@check_spam_decorator
async def get_group(update: Update, context: CallbackContext) -> int:
    user_input = update.message.text
    logger.info(f"Отримано групу від користувача {update.effective_user.id}: {user_input}")

    if user_input.lower() == 'скасувати':
        logger.info(f"Користувач {update.effective_user.id} скасував реєстрацію на етапі введення групи")
        await cancel(update, context)
        return ConversationHandler.END

    try:
        # Підключення до MongoDB
        client_mongo = MongoClient(MONGO_URI)
        db_group = client_mongo[DB_NAME]
        collection = db_group['FMI_Group_numbers']

        # Перевірка існування групи в базі даних
        group_exists = collection.find_one({"groupNumber": user_input})

        if not group_exists:
            logger.warning(f"Користувач {update.effective_user.id} ввів неіснуючий номер групи: {user_input}")
            error_message = await update.message.reply_text(
                "❌ Помилка: Такої групи не існує! Будь ласка, перевірте номер групи та спробуйте ще раз."
            )
            await asyncio.sleep(3)
            await error_message.delete()
            return GROUP

        # Перевірка формату групи
        if not re.match(GROUP_PATTERN, user_input):
            logger.warning(f"Користувач {update.effective_user.id} ввів некоректний номер групи: {user_input}")
            error_message = await update.message.reply_text(
                ERROR_MESSAGES['group_format']
            )
            await asyncio.sleep(3)
            await error_message.delete()
            return GROUP

        context.user_data['group'] = user_input

        await update.message.reply_text(
            "Будь ласка, введіть ваш номер телефону у форматі:\n"
            "+380XXXXXXXXX, 380XXXXXXXXX або 0XXXXXXXXX"
        )

    except Exception as e:
        logger.error(f"Помилка при роботі з базою даних: {e}")
        await update.message.reply_text("Вибачте, виникла технічна помилка. Спробуйте пізніше.")
        return GROUP

    finally:
        client_mongo.close()

    return PHONE

@check_spam_decorator
async def get_phone(update: Update, context: CallbackContext) -> int:
    user_input = update.message.text
    logger.info(f"Отримано номер телефону від користувача {update.effective_user.id}: {user_input}")

    if user_input.lower() == 'скасувати':
        logger.info(f"Користувач {update.effective_user.id} скасував реєстрацію на етапі введення номера телефону")
        await cancel(update, context)
        return ConversationHandler.END

    if not re.match(PHONE_PATTERN, user_input):
        logger.warning(f"Користувач {update.effective_user.id} ввів некоректний номер телефону: {user_input}")
        error_message = await update.message.reply_text(ERROR_MESSAGES['phone_format'])
        await asyncio.sleep(3)
        await error_message.delete()
        return PHONE

    # Нормалізація номера телефону
    if user_input.startswith('0'):
        normalized_phone = '+38' + user_input
    elif user_input.startswith('380'):
        normalized_phone = '+' + user_input
    else:
        normalized_phone = user_input

    context.user_data['phone'] = normalized_phone

    keyboard = [
        [
            InlineKeyboardButton("Копірайтинг ✍️", callback_data="copywriting"),
            InlineKeyboardButton("Відео монтаж 🎥", callback_data="video"),
        ],
        [
            InlineKeyboardButton("Дизайнер 🎨", callback_data="design"),
            InlineKeyboardButton("Фотограф 📸", callback_data="photo")
        ],
        [InlineKeyboardButton("Завершити вибір ✅", callback_data="done")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message = await update.message.reply_text(
        "Оберіть, що вам більше подобається (можна обрати декілька варіантів), \n\n"
        "Щоб скасувати вибір натисніть на напрямок ще раз:",
        reply_markup=reply_markup
    )
    logger.info(f"Відправлено клавіатуру з напрямками користувачу {update.effective_user.id}")

    context.user_data['message_id'] = message.message_id
    context.user_data['employment_types'] = []

    return EMPLOYMENT

@check_spam_decorator
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
                        'birthday': context.user_data.get('birthday'),
                        'group': group,
                        'phone': context.user_data.get('phone'),
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
            "design": "Дизайнер",
            "photo": "Фотограф"
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

@check_spam_decorator
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
            BIRTHDAY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_birthday)],
            GROUP: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_group)],
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)],
            EMPLOYMENT: [CallbackQueryHandler(handle_employment_choice)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        per_message=False
    )
