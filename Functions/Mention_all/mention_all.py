import logging
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler
from pymongo import MongoClient
import os
import re
from dotenv import load_dotenv
import time

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI')
DB_NAME = os.getenv('MONGO_DATABASE')

# Словник для зберігання часу останнього виконання команди для кожного чату
last_execution_time = {}


async def mention_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    bot = context.bot

    # Перевірка часу останнього виконання команди
    current_time = time.time()
    last_time = last_execution_time.get(chat_id, 0)

    if current_time - last_time < 900:  # 900 секунд = 15 хвилин
        remaining_time = 900 - (current_time - last_time)
        minutes_left = int(remaining_time // 60)
        await update.message.reply_text(
            f"❗ Ви не можете виконати цю команду ще раз. Залишилося {minutes_left} хвилин."
        )
        return

    # Оновлення часу останнього виконання команди
    last_execution_time[chat_id] = current_time

    # Підключення до MongoDB
    try:
        mongo_client = MongoClient(MONGO_URI)
        db = mongo_client[DB_NAME]

        # Перевірка ініціалізації чату шляхом пошуку користувачів
        users_collection = db['chat_users']
        chat_users_count = users_collection.count_documents({'chat_id': chat_id})

        if chat_users_count == 0:
            await update.message.reply_text(
                "❗ Увага! Цей чат ще не було ініціалізовано.\n"
                "Будь ласка, спочатку виконайте команду ініціалізації користувачів."
            )
            mongo_client.close()
            return

        # Отримання користувачів для цього чату
        chat_users = list(users_collection.find({'chat_id': chat_id}))

        # Функція для безпечного екранування імен
        def safe_name(name):
            if name is None:  # Додаємо перевірку на None
                return "не знайдено"
            # Видаляємо спеціальні символи, які можуть зламати Markdown
            return re.sub(r'[_*\[\]()~`>#+-=|{}.!]', '', name).strip()

        # Формування повідомлення зі згадками
        mentions = []
        for user in chat_users:
            # Пріоритет: username > full name > user_id
            if user.get('username'):
                mentions.append(f"@{user['username']}")
            elif user.get('first_name') or user.get('last_name'):
                full_name = f"{safe_name(user.get('first_name', ''))} {safe_name(user.get('last_name', ''))}".strip()
                if full_name:
                    mentions.append(f"[{full_name}](tg://user?id={user['user_id']})")
                else:
                    mentions.append(f"[Користувач](tg://user?id={user['user_id']})")
            else:
                mentions.append(f"[Користувач](tg://user?id={user['user_id']})")

        # Розбиття великої кількості згадок на частини
        max_mentions_per_message = 50
        for i in range(0, len(mentions), max_mentions_per_message):
            chunk = mentions[i:i + max_mentions_per_message]
            try:
                await update.message.reply_text(
                    " ".join(chunk),
                    parse_mode='Markdown'
                )
            except Exception as mention_error:
                # Якщо markdown не спрацював, надсилаємо без форматування
                logging.warning(f"Помилка Markdown, надсилаємо без форматування: {mention_error}")
                await update.message.reply_text(" ".join(chunk))

        # Додаткова інформація
        await update.message.reply_text(
            f"📢 Всього згадано користувачів: {len(mentions)}\n\n"
            f"Якщо були згадані не всі користувачі спробуйте виконати команду /init знову"
        )

    except Exception as e:
        logging.error(f"Помилка при згадуванні користувачів: {e}")
        await update.message.reply_text(f"❌ Виникла помилка: {str(e)}")

    finally:
        # Закриття з'єднання з MongoDB
        mongo_client.close()


def get_mention_handler():
    return CommandHandler('mention_all', mention_users)
