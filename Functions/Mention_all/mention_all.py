from telegram import Update, ReactionTypeEmoji
from telegram.constants import ParseMode
from telegram.ext import (
    ContextTypes, CommandHandler, MessageHandler, filters
)
from pymongo import MongoClient
import os
import re
import asyncio
import time
import random
from dotenv import load_dotenv
from Functions.Anti_spam.antispam_handlers import check_spam_decorator, admin_only
from Functions.Logger.Logger_config import logger

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI')
DB_NAME = os.getenv('MONGO_DATABASE')

# Глобальні словники
last_execution_time = {}
user_attempts = {}
clown_reaction_users = {}
# Словник для зберігання відповідності користувач-емодзі
user_emoji_mapping = {}

# Конфігураційні параметри
MENTION_COOLDOWN = 900  # 15 хвилин в секундах
MAX_MENTIONS_PER_MESSAGE = 100
MAX_ATTEMPTS_BEFORE_CLOWN = 3
EXPLANATION_DELETION_DELAY = 30  # секунд


@check_spam_decorator
async def mention_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Функція для згадування всіх користувачів чату за допомогою емодзі.
    Кожному користувачу присвоюється унікальне емодзі, яке зберігається між викликами команди.
    """
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

    if current_time - last_time < MENTION_COOLDOWN:
        remaining_time = MENTION_COOLDOWN - (current_time - last_time)
        minutes_left = int(remaining_time // 60)
        seconds_left = int(remaining_time % 60)

        user_attempts[user_id] = user_attempts.get(user_id, 0) + 1

        await update.effective_message.reply_text(
            f"⏱️ Ця команда має обмеження часу!\n"
            f"Залишилося {minutes_left} хв {seconds_left} сек до наступного використання."
        )

        if user_attempts[user_id] >= MAX_ATTEMPTS_BEFORE_CLOWN:
            await bot.set_message_reaction(
                chat_id=chat_id,
                message_id=update.effective_message.message_id,
                reaction=[ReactionTypeEmoji("🤡")]
            )

            clown_reaction_users[user_id] = 3
            user_attempts[user_id] = 0

        return

    user_attempts[user_id] = 0
    last_execution_time[chat_id] = current_time

    try:
        mongo_client = MongoClient(MONGO_URI)
        db = mongo_client[DB_NAME]

        users_collection = db['chat_users']
        chat_users_count = users_collection.count_documents({'chat_id': chat_id})

        def get_emoji_data():
            try:
                emoji_collection = db['emoji_list']

                # Отримуємо простий список емодзі
                emoji_doc = emoji_collection.find_one({"type": "simple_list"})
                emoji_list = emoji_doc.get("emojis", []) if emoji_doc else []

                return emoji_list
            except Exception as er:
                print(f"Помилка при отриманні емодзі з MongoDB: {str(er)}")
                # Якщо сталася помилка, повертаємо порожні списки
                return [], {}

        EMOJI_LIST = get_emoji_data()

        if chat_users_count == 0:
            await update.message.reply_text(
                "❗ Увага! Цей чат ще не було ініціалізовано.\n"
                "Будь ласка, спочатку виконайте команду /init для ініціалізації користувачів."
            )
            return

        chat_users = list(users_collection.find({'chat_id': chat_id}))

        # Унікальний ключ для цього чату
        chat_key = f"chat_{chat_id}"
        if chat_key not in user_emoji_mapping:
            user_emoji_mapping[chat_key] = {}

        # Множина для відстеження вже використаних емодзі в поточному чаті
        used_emojis = set()
        for emoji_data in user_emoji_mapping[chat_key].values():
            used_emojis.add(emoji_data)

        # Функція для отримання унікального емодзі
        def get_unique_emoji(user_data=None):
            # Якщо є дані користувача, можна обрати емодзі на основі якихось критеріїв.
            # Наприклад, адмінам - особливі емодзі

            available_emojis = [emoji for emoji in EMOJI_LIST if emoji not in used_emojis]
            if not available_emojis:  # Якщо всі емодзі вже використані
                return random.choice(EMOJI_LIST)

            emoji = random.choice(available_emojis)
            used_emojis.add(emoji)
            return emoji

        # Спробуємо спочатку використати HTML форматування
        try_html_first = True

        mentions_md = []  # Згадки у форматі Markdown
        mentions_html = []  # Згадки у форматі HTML

        for user in chat_users:
            user_unique_id = user['user_id']

            # Якщо для цього користувача ще немає емодзі, призначаємо нове
            if str(user_unique_id) not in user_emoji_mapping[chat_key]:
                user_emoji_mapping[chat_key][str(user_unique_id)] = get_unique_emoji(user)

            user_emoji = user_emoji_mapping[chat_key][str(user_unique_id)]

            # Формування посилань в обох форматах
            # Markdown формат
            mentions_md.append(f"[{user_emoji}](tg://user?id={user['user_id']})")

            # HTML формат
            mentions_html.append(f'<a href="tg://user?id={user["user_id"]}">{user_emoji}</a>')

        # Спробуємо спочатку HTML, потім Markdown якщо не вийде
        success = False

        if try_html_first:
            for i in range(0, len(mentions_html), MAX_MENTIONS_PER_MESSAGE):
                chunk = mentions_html[i:i + MAX_MENTIONS_PER_MESSAGE]
                try:
                    sent_message = await update.message.reply_text(
                        " ".join(chunk),
                        parse_mode=ParseMode.HTML
                    )
                    success = True
                except Exception as html_error:
                    logger.warning(f"Помилка HTML форматування: {html_error}")
                    success = False
                    break  # Вийдемо і спробуємо Markdown

        # Якщо HTML не спрацював, спробуємо Markdown
        if not try_html_first or not success:
            for i in range(0, len(mentions_md), MAX_MENTIONS_PER_MESSAGE):
                chunk = mentions_md[i:i + MAX_MENTIONS_PER_MESSAGE]
                try:
                    sent_message = await update.message.reply_text(
                        " ".join(chunk),
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception as md_error:
                    logger.warning(f"Помилка Markdown форматування: {md_error}")
                    # Якщо обидва формати не працюють, просто відправимо емодзі без посилань
                    raw_emojis = [user_emoji_mapping[chat_key].get(str(user['user_id']), "👤") for user in chat_users]
                    raw_chunk = raw_emojis[i:i + MAX_MENTIONS_PER_MESSAGE]
                    sent_message = await update.message.reply_text(" ".join(raw_chunk))

        # Надсилаємо пояснення про емодзі
        explanation_message = await update.message.reply_text(
            f"📢 Сповіщення про активність в чаті!\n\n"
            f"🔹 Всього згадано користувачів: {len(chat_users)}\n"
            f"🔹 Кожне емодзі є посиланням на окремого користувача\n"
            f"🔹 Натисніть на емодзі, щоб перейти до профілю\n\n"
            f"⏱️ Наступний виклик буде доступний через {MENTION_COOLDOWN // 60} хвилин"
        )
        asyncio.create_task(delete_message_after_delay(explanation_message, EXPLANATION_DELETION_DELAY))

    except Exception as e:
        logger.error(f"Помилка при згадуванні користувачів: {e}")
        await update.message.reply_text(f"❌ Сталася помилка при обробці запиту. Спробуйте пізніше.")

    finally:
        if 'mongo_client' in locals():
            mongo_client.close()


async def delete_message_after_delay(message, delay):
    """Видаляє повідомлення через `delay` секунд"""
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception as e:
        logger.debug(f"Не вдалося видалити повідомлення: {e}")


async def react_to_new_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Додає реакцію на повідомлення користувачів, які намагалися спамити командою згадування"""
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


def get_mention_handler():
    """Повертає обробник для команди згадування всіх користувачів"""
    return CommandHandler('mention_all', mention_users)
