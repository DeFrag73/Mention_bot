import logging
from telegram import Update, ReactionTypeEmoji
from telegram.ext import (
    ContextTypes, CommandHandler, MessageHandler, filters
)
from pymongo import MongoClient
import os
import re
import asyncio
import time
from dotenv import load_dotenv
from Functions.Anti_spam.antispam_handlers import check_spam_decorator, admin_only

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI')
DB_NAME = os.getenv('MONGO_DATABASE')

# Глобальні словники
last_execution_time = {}
user_attempts = {}
clown_reaction_users = {}

@check_spam_decorator
async def mention_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message:
        return

    # Перевірка чи чат є приватним
    if update.effective_chat.type == "private":
        await update.message.reply_text(
            "❌ Ця команда доступна тільки в групах та спільнотах!\n"
            "Будь ласка, використовуйте її у відповідних чатах."
        )
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    bot = context.bot

    # Перевірка часу останнього виконання команди
    current_time = time.time()
    last_time = last_execution_time.get(chat_id, 0)

    if current_time - last_time < 900:  # 15 хвилин
        remaining_time = 900 - (current_time - last_time)
        minutes_left = int(remaining_time // 60)

        user_attempts[user_id] = user_attempts.get(user_id, 0) + 1

        await update.effective_message.reply_text(
            f"❗ Ви не можете виконати цю команду ще раз. Залишилося {minutes_left} хвилин."
        )

        if user_attempts[user_id] >= 3:
            await bot.set_message_reaction(
                chat_id=chat_id,
                message_id=update.effective_message.message_id,
                reaction=[ReactionTypeEmoji("🤡")]
            )

            clown_reaction_users[user_id] = 3
            user_attempts[user_id] = 0

        return    # Вихід після попередження

    user_attempts[user_id] = 0
    last_execution_time[chat_id] = current_time

    try:
        mongo_client = MongoClient(MONGO_URI)
        db = mongo_client[DB_NAME]

        users_collection = db['chat_users']
        chat_users_count = users_collection.count_documents({'chat_id': chat_id})

        if chat_users_count == 0:
            await update.message.reply_text(
                "❗ Увага! Цей чат ще не було ініціалізовано.\n"
                "Будь ласка, спочатку виконайте команду ініціалізації користувачів."
            )
            return

        chat_users = list(users_collection.find({'chat_id': chat_id}))

        def safe_name(name):
            if name is None:
                return "не знайдено"
            return re.sub(r'[_*\[\]()~`>#+-=|{}.!]', '', name).strip()

        mentions = []
        for user in chat_users:
            if user.get('username'):
                mentions.append(f"@{user['username']}")
            elif user.get('first_name') or user.get('last_name'):
                full_name = f"{safe_name(user.get('first_name', ''))} {safe_name(user.get('last_name', ''))}".strip()
                mentions.append(f"[{full_name}](tg://user?id={user['user_id']})" if full_name else f"[Користувач](tg://user?id={user['user_id']})")
            else:
                mentions.append(f"[Користувач](tg://user?id={user['user_id']})")

        max_mentions_per_message = 50
        for i in range(0, len(mentions), max_mentions_per_message):
            chunk = mentions[i:i + max_mentions_per_message]
            try:
                sent_message = await update.message.reply_text(
                    " ".join(chunk),
                    parse_mode='Markdown'
                )
                # asyncio.create_task(delete_message_after_delay(sent_message, 10))
            except Exception as mention_error:
                logging.warning(f"Помилка Markdown: {mention_error}")
                sent_message = await update.message.reply_text(" ".join(chunk))
                # asyncio.create_task(delete_message_after_delay(sent_message, 10))

        sent_message = await update.message.reply_text(
            f"📢 Всього згадано користувачів: {len(mentions)}\n\n"
            f"Якщо були згадані не всі користувачі, спробуйте команду /init знову"
        )
        asyncio.create_task(delete_message_after_delay(sent_message, 10))

    except Exception as e:
        logging.error(f"Помилка при згадуванні: {e}")
        await update.message.reply_text(f"❌ Виникла помилка: {str(e)}")

    finally:
        mongo_client.close()


async def delete_message_after_delay(message, delay):
    """Видаляє повідомлення через `delay` секунд"""
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:
        pass  # Повідомлення вже могло бути видалене


async def react_to_new_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    bot = context.bot

    if clown_reaction_users.get(user_id, 0) > 0:
        await bot.set_message_reaction(
            chat_id=chat_id,
            message_id=update.message.message_id,
            reaction=[ReactionTypeEmoji("🤡")]
        )

        clown_reaction_users[user_id] -= 1

        if clown_reaction_users[user_id] == 0:
            del clown_reaction_users[user_id]


# 🔥 **Збережена функція get_mention_handler()**
def get_mention_handler():
    return CommandHandler('mention_all', mention_users)
