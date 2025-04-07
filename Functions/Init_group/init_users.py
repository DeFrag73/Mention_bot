import datetime
from telegram import Update, ChatMemberAdministrator
from telegram.ext import ContextTypes, CommandHandler
from telethon import TelegramClient
from pymongo import MongoClient, UpdateOne
import asyncio
import os
from dotenv import load_dotenv
from Functions.Anti_spam.antispam_handlers import check_spam_decorator, admin_only
from Functions.Logger.Logger_config import logger

load_dotenv()

API_ID = os.getenv('TELEGRAM_API_ID')
API_HASH = os.getenv('TELEGRAM_API_HASH')
PHONE_NUMBER = os.getenv('TELEGRAM_PHONE_NUMBER')
MONGO_URI = os.getenv('MONGO_URI')
DB_NAME = os.getenv('MONGO_DATABASE')
SPECIAL_USER = os.getenv('SPECIAL_USER')

@check_spam_decorator
async def init_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    bot = context.bot

    # Перевірка чи чат є приватним
    if update.effective_chat.type == "private":
        await update.message.reply_text(
            "❌ Ця команда доступна тільки в групах та спільнотах!\n"
            "Будь ласка, використовуйте її у відповідних чатах."
        )
        return

    # # Перевірка прав адміністратора
    # try:
    #     bot_member = await bot.get_chat_member(chat_id, bot.id)
    #     if not isinstance(bot_member, ChatMemberAdministrator):
    #         await update.message.reply_text(
    #             "❗ Для коректної роботи бот повинен бути адміністратором групи.\n"
    #             "Будь ласка, надайте боту права адміністратора та спробуйте знову. /init"
    #         )
    #         return False
    # except Exception as e:
    #     logger.error(f"Помилка при перевірці прав адміністратора: {e}")
    #     await update.message.reply_text("❌ Помилка при перевірці прав бота.")
    #     return False

    # Ініціалізація клієнтів
    client = TelegramClient('session_name', API_ID, API_HASH)

    try:
        # Підключення до Telegram через Telethon
        await client.start(phone=PHONE_NUMBER)

        # Отримання інформації про чат
        chat = await client.get_entity(chat_id)

        # Отримання всіх учасників
        participants = await client.get_participants(chat)

        # Підключення до MongoDB
        mongo_client = MongoClient(MONGO_URI)
        db = mongo_client[DB_NAME]
        users_collection = db['chat_users']

        # Створення списку актуальних user_id
        current_user_ids = [user.id for user in participants]

        # Створення записів для кожного користувача
        bulk_operations = []
        for user in participants:
            user_data = {
                'user_id': user.id,
                'chat_id': chat_id,
                'username': user.username,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'is_bot': user.bot,
                'phone': user.phone if hasattr(user, 'phone') else None,
                'timestamp': datetime.datetime.now()
            }

            # Підготовка операції оновлення (upsert)
            bulk_operations.append(
                UpdateOne(
                    {'user_id': user.id, 'chat_id': chat_id},
                    {'$set': user_data},
                    upsert=True
                )
            )

        # Видалення користувачів, яких більше немає в групі
        delete_result = users_collection.delete_many({
            'chat_id': chat_id,
            'user_id': {'$nin': current_user_ids}
        })

        # Виконання bulk операції
        if bulk_operations:
            result = users_collection.bulk_write(bulk_operations)

        # Підготовка звіту
        report_message = await update.message.reply_text(
            f"✅ Успішно ініціалізовано базу користувачів!\n"
            f"Оброблено користувачів: {len(participants)}\n"
            f"Оновлено записів: {result.modified_count}\n"
            f"Додано нових записів: {result.upserted_count}\n"
            f"Видалено застарілих записів: {delete_result.deleted_count}"
        )

        await asyncio.sleep(10)

        # Видалення повідомлення
        await report_message.delete()

    except Exception as e:
        logger.error(f"Помилка при ініціалізації користувачів: {e}")
        await update.message.reply_text(f"❌ Помилка при ініціалізації: {str(e)}")
    finally:
        await client.disconnect()
        mongo_client.close()

    return True


def get_init_handler():
    return CommandHandler('init', init_user)
