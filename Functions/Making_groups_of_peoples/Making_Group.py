import os
from datetime import datetime
from typing import Dict, List
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters
)
from pymongo import MongoClient
from dotenv import load_dotenv


load_dotenv()

MONGODB_URI = os.getenv('MONGO_URI')
DB_NAME = os.getenv('MONGO_DATABASE')

# Стани розмови
WAIT_GROUP_NAME, SELECT_USERS = range(2)

# Словник для зберігання тимчасових даних розмови
user_data_dict: Dict[int, dict] = {}


class GroupCreationManager:
    def __init__(self, mongodb_uri: str, database_name: str):
        self.client = MongoClient(mongodb_uri)
        self.db = self.client[database_name]
        self.users_collection = self.db['chat_users']

    async def start_group_creation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Початок створення групи"""
        # Перевіряємо чи є користувач адміністратором
        user = update.effective_user
        chat = update.effective_chat

        try:
            member = await context.bot.get_chat_member(chat.id, user.id)
            if member.status not in ['administrator', 'creator']:
                await update.message.reply_text("❌ Тільки адміністратори можуть створювати групи користувачів!")
                return ConversationHandler.END
        except Exception as e:
            await update.message.reply_text("❌ Помилка перевірки прав адміністратора!")
            return ConversationHandler.END

        # Зберігаємо chat_id для подальшого використання
        user_data_dict[user.id] = {'chat_id': chat.id}

        await update.message.reply_text(
            "📝 Будь ласка, введіть назву нової групи користувачів.\n"
            "Вимоги до назви:\n"
            "• Довжина від 3 до 30 символів\n"
            "• Може містити літери, цифри та символи - _\n"
            "• Без спеціальних символів\n\n"
            "Для скасування використайте команду /cancel"
        )

        return WAIT_GROUP_NAME

    async def validate_group_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Валідація назви групи та перехід до вибору користувачів"""
        group_name = update.message.text.strip()
        user_id = update.effective_user.id

        # Додайте на початку методу
        print(f"Шукаємо користувачів для chat_id: {user_data_dict[user_id]['chat_id']}")
        test_user = self.users_collection.find_one()
        print(f"Тестовий користувач з бази: {test_user}")

        # ... (код валідації назви групи) ...

        # Перед пошуком користувачів
        print(f"Параметри пошуку: chat_id = {user_data_dict[user_id]['chat_id']}")

        # Змініть запит до бази даних
        chat_users = list(self.users_collection.find({
            'chat_id': int(user_data_dict[user_id]['chat_id'])  # Конвертуємо в int
        }))
        print(f"Знайдено користувачів: {len(chat_users)}")
        print(f"Користувачі: {chat_users}")  # Подивимось які дані повертаються

        # Створюємо клавіатуру для вибору користувачів
        keyboard = []
        row = []
        for user in chat_users:
            display_name = user.get('first_name', '')
            if user.get('username'):
                display_name += f" (@{user['username']})"

            # Створюємо кнопку для кожного користувача
            # callback_data: user_{user_id}_{selected/unselected}
            callback_data = f"user_{user['user_id']}_unselected"
            button = InlineKeyboardButton(
                text=f"☐ {display_name}",
                callback_data=callback_data
            )

            row.append(button)
            if len(row) == 2:  # Два користувачі в ряд
                keyboard.append(row)
                row = []

        if row:  # Додаємо останній неповний ряд
            keyboard.append(row)

        # Додаємо кнопки управління внизу
        keyboard.append([
            InlineKeyboardButton("✅ Підтвердити", callback_data="confirm"),
            InlineKeyboardButton("❌ Скасувати", callback_data="cancel")
        ])

        reply_markup = InlineKeyboardMarkup(keyboard)

        # Зберігаємо повідомлення з клавіатурою для можливості оновлення
        message = await update.message.reply_text(
            f"👥 Виберіть користувачів для групи '{group_name}':\n"
            f"Виберіть користувачів та натисніть 'Підтвердити'",
            reply_markup=reply_markup
        )

        user_data_dict[user_id]['message_id'] = message.message_id
        user_data_dict[user_id]['selected_users'] = set()

        return SELECT_USERS

    async def handle_user_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Обробка вибору користувачів"""
        query = update.callback_query
        user_id = update.effective_user.id
        await query.answer()

        if query.data == "cancel":
            await query.message.edit_text("❌ Створення групи скасовано.")
            return ConversationHandler.END

        if query.data == "confirm":
            selected_users = user_data_dict[user_id]['selected_users']
            if not selected_users:
                await query.answer("⚠️ Виберіть хоча б одного користувача!", show_alert=True)
                return SELECT_USERS

            # Оновлюємо документи користувачів у базі даних
            try:
                self.users_collection.update_many(
                    {
                        'chat_id': {'$numberLong': str(user_data_dict[user_id]['chat_id'])},
                        'user_id': {'$in': list(selected_users)}
                    },
                    {
                        '$addToSet': {
                            'groups': {
                                'name': user_data_dict[user_id]['group_name'],
                                'created_by': user_id,
                                'created_at': datetime.utcnow()
                            }
                        }
                    }
                )

                await query.message.edit_text(
                    f"✅ Група '{user_data_dict[user_id]['group_name']}' успішно створена!\n"
                    f"Додано користувачів: {len(selected_users)}"
                )
                return ConversationHandler.END

            except Exception as e:
                await query.message.edit_text("❌ Помилка при створенні групи!")
                return ConversationHandler.END

        # Обробка вибору користувача
        if query.data.startswith("user_"):
            _, user_id_str, current_state = query.data.split("_")
            selected_user_id = int(user_id_str)

            # Оновлюємо стан вибору
            if current_state == "unselected":
                user_data_dict[user_id]['selected_users'].add(selected_user_id)
                new_state = "selected"
            else:
                user_data_dict[user_id]['selected_users'].remove(selected_user_id)
                new_state = "unselected"

            # Оновлюємо клавіатуру
            keyboard = []
            for row in query.message.reply_markup.inline_keyboard[:-1]:  # Без останнього ряду з кнопками управління
                new_row = []
                for button in row:
                    if button.callback_data == query.data:
                        # Оновлюємо текст та callback_data для натиснутої кнопки
                        text = button.text.replace(
                            "☐" if new_state == "selected" else "☑",
                            "☑" if new_state == "selected" else "☐"
                        )
                        new_callback_data = f"user_{user_id_str}_{new_state}"
                        new_row.append(InlineKeyboardButton(text=text, callback_data=new_callback_data))
                    else:
                        new_row.append(button)
                keyboard.append(new_row)

            # Додаємо кнопки управління
            keyboard.append([
                InlineKeyboardButton("✅ Підтвердити", callback_data="confirm"),
                InlineKeyboardButton("❌ Скасувати", callback_data="cancel")
            ])

            await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
            return SELECT_USERS

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Скасування створення групи"""
        user_id = update.effective_user.id
        if user_id in user_data_dict:
            del user_data_dict[user_id]

        await update.message.reply_text("❌ Створення групи скасовано.")
        return ConversationHandler.END


def get_group_creation_handler():
    """Повертає handler для створення групи"""
    group_manager = GroupCreationManager(
        mongodb_uri=MONGODB_URI,
        database_name=DB_NAME
    )

    return ConversationHandler(
        entry_points=[CommandHandler('create_user_group', group_manager.start_group_creation)],
        states={
            WAIT_GROUP_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, group_manager.validate_group_name),
            ],
            SELECT_USERS: [
                CallbackQueryHandler(group_manager.handle_user_selection),
            ],
        },
        fallbacks=[CommandHandler('cancel', group_manager.cancel)],
        name="group_creation",
        persistent=False
    )
