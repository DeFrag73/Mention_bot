import os
from datetime import datetime
from typing import Dict, List, Union
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
from bson import ObjectId
from functools import wraps
from typing import Callable, Any
from aiogram import types

from Functions.Anti_spam.anti_spam import AntiSpam
from Functions.Anti_spam.antispam_handlers import check_spam_decorator, admin_only


load_dotenv()

MONGODB_URI = os.getenv('MONGO_URI')
DB_NAME = os.getenv('MONGO_DATABASE')

# Стани розмови
WAIT_GROUP_NAME, SELECT_USERS = range(2)

# Словник для зберігання тимчасових даних розмови
user_data_dict: Dict[int, dict] = {}

def check_spam(f: Callable) -> Callable:
    """
    Декоратор для перевірки спаму перед виконанням методу.
    Працює з методами, що приймають Update від python-telegram-bot.
    """

    @wraps(f)
    async def wrapper(self, update: Update, *args, **kwargs) -> Any:
        # Отримуємо ID користувача з Update
        user_id = update.effective_user.id

        # Перевіряємо на спам
        is_spam, spam_message = self.anti_spam.is_spam(user_id)

        if is_spam:
            # Відправляємо повідомлення про спам
            if update.message:
                await update.message.reply_text(spam_message)
            elif update.callback_query:
                await update.callback_query.answer(spam_message, show_alert=True)
            return

        # Якщо спаму немає - виконуємо оригінальний метод
        return await f(self, update, *args, **kwargs)

    return wrapper

class GroupCreationManager:
    def __init__(self, mongodb_uri: str, database_name: str):
        self.client = MongoClient(mongodb_uri)
        self.db = self.client[database_name]
        self.users_collection = self.db['chat_users']
        self.groups_collection = self.db['user_groups']

        # Ініціалізуємо антиспам систему
        self.anti_spam = AntiSpam(
            mongodb_uri,
            messages_limit=5,
            time_window=5,
            ban_time=30
        )

    @check_spam
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
            "Для скасування використайте команду /cancel_create_group"
        )

        return WAIT_GROUP_NAME

    @check_spam
    async def validate_group_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Валідація назви групи та перехід до вибору користувачів"""
        group_name = update.message.text.strip()
        user_id = update.effective_user.id

        # Зберігаємо назву групи у словнику
        user_data_dict[user_id]['group_name'] = group_name

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

    @check_spam
    async def handle_user_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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

            try:
                chat_id = int(user_data_dict[user_id]['chat_id'])

                # Отримуємо унікальних користувачів з поточного чату
                selected_users_info = list(self.users_collection.find(
                    {
                        'chat_id': chat_id,  # Шукаємо тільки в поточному чаті
                        'user_id': {'$in': list(selected_users)}
                    },
                    {'_id': 0, 'user_id': 1, 'username': 1, 'first_name': 1}
                ))

                # Видаляємо дублікати за допомогою set
                unique_users = {
                    user['user_id']: user
                    for user in selected_users_info
                }.values()

                # Створюємо документ групи з унікальними користувачами
                group_document = {
                    'chat_id': chat_id,
                    'name': user_data_dict[user_id]['group_name'],
                    'created_by': user_id,
                    'created_at': datetime.utcnow(),
                    'members': list(unique_users)  # Конвертуємо назад у список
                }

                # Додаємо групу до колекції груп
                self.groups_collection.insert_one(group_document)

                await query.message.edit_text(
                    f"✅ Група '{user_data_dict[user_id]['group_name']}' успішно створена!\n"
                    f"Додано користувачів: {len(unique_users)}"
                )
                return ConversationHandler.END

            except Exception as e:
                await query.message.edit_text(
                    "❌ Помилка при створенні групи!\n"
                    f"Error: {str(e)}"
                )
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

    @check_spam
    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Скасування створення групи"""
        user_id = update.effective_user.id
        if user_id in user_data_dict:
            del user_data_dict[user_id]

        await update.message.reply_text("❌ Створення групи скасовано.")
        return ConversationHandler.END

    @check_spam
    async def delete_group(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обробник команди видалення групи"""
        user = update.effective_user
        chat = update.effective_chat

        try:
            # Перевіряємо права адміністратора
            member = await context.bot.get_chat_member(chat.id, user.id)
            if member.status not in ['administrator', 'creator']:
                await update.message.reply_text("❌ Тільки адміністратори можуть видаляти групи!")
                return

            # Отримуємо всі групи в поточному чаті
            groups = list(self.groups_collection.find({'chat_id': chat.id}))

            if not groups:
                await update.message.reply_text("❌ У цьому чаті немає створених груп!")
                return

            # Створюємо клавіатуру з групами
            keyboard = []
            for group in groups:
                keyboard.append([
                    InlineKeyboardButton(
                        text=f"❌ {group['name']} ({len(group['members'])} учасників)",
                        callback_data=f"delete_group_{str(group['_id'])}"
                    )
                ])

            keyboard.append([
                InlineKeyboardButton("Скасувати", callback_data="cancel_delete")
            ])

            await update.message.reply_text(
                "🗑 Виберіть групу для видалення:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        except Exception as e:
            await update.message.reply_text(f"❌ Помилка: {str(e)}")

    @check_spam
    async def mention_group(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Показує список груп для вибору та згадування їх учасників"""
        chat = update.effective_chat

        try:
            # Отримуємо всі групи для поточного чату
            groups = list(self.groups_collection.find({'chat_id': chat.id}))

            if not groups:
                await update.message.reply_text("📝 У цьому чаті ще немає створених груп.")
                return

            # Створюємо клавіатуру з групами
            keyboard = []
            for group in groups:
                keyboard.append([
                    InlineKeyboardButton(
                        text=f"👥 {group['name']} ({len(group['members'])} учасників)",
                        callback_data=f"mention_group_{str(group['_id'])}"
                    )
                ])

            keyboard.append([
                InlineKeyboardButton("❌ Скасувати", callback_data="cancel_mention")
            ])

            await update.message.reply_text(
                "🔍 Виберіть групу для згадування учасників:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        except Exception as e:
            await update.message.reply_text(f"❌ Помилка: {str(e)}")

    @check_spam
    async def handle_mention_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обробник вибору групи для згадування"""
        query = update.callback_query
        await query.answer()

        if query.data == "cancel_mention":
            await query.message.edit_text("❌ Згадування скасовано.")
            return

        if query.data.startswith("mention_group_"):
            try:
                group_id = query.data.replace("mention_group_", "")
                group = self.groups_collection.find_one({'_id': ObjectId(group_id)})

                if not group or not group.get('members'):
                    await query.message.edit_text("❌ Група не знайдена або не має учасників!")
                    return

                # Формуємо список згадувань
                mentions = []
                for member in group['members']:
                    if member.get('username'):
                        mentions.append(f"@{member['username']}")
                    else:
                        # Екрануємо спеціальні символи в імені
                        safe_name = member.get('first_name', 'Користувач').replace('[', '\\[').replace(']', '\\]')
                        mentions.append(f"[{safe_name}](tg://user?id={member['user_id']})")

                # Відправляємо повідомлення зі згадуваннями
                mention_text = f"👥 Група «{group['name']}»:\n"
                for member in group['members']:
                    if member.get('username'):
                        mention_text += f"@{member['username']} "
                    else:
                        mention_text += f"{member.get('first_name', 'Користувач')} "

                await query.message.edit_text(
                    mention_text.strip(),
                    disable_web_page_preview=True
                )


            except Exception as e:
                await query.message.edit_text(f"❌ Помилка при згадуванні: {str(e)}")

    @check_spam
    async def show_groups(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Показує всі групи в поточному чаті"""
        chat = update.effective_chat

        try:
            # Отримуємо всі групи для поточного чату
            groups = list(self.groups_collection.find({'chat_id': chat.id}))

            if not groups:
                await update.message.reply_text("📝 У цьому чаті ще немає створених груп.")
                return

            # Формуємо повідомлення зі списком груп
            message = "📋 Список груп у чаті:\n\n"
            for group in groups:
                members_count = len(group['members'])
                message += f"👥 *{group['name']}*\n"
                message += f"├ Учасників: {members_count}\n"
                message += f"└ Створена: {group['created_at'].strftime('%d.%m.%Y %H:%M')}\n\n"

            await update.message.reply_text(message, parse_mode='Markdown')

        except Exception as e:
            await update.message.reply_text(f"❌ Помилка при отриманні списку груп: {str(e)}")

    @check_spam
    async def handle_delete_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обробник вибору групи для видалення"""
        query = update.callback_query
        await query.answer()

        if query.data == "cancel_delete":
            await query.message.edit_text("❌ Видалення скасовано.")
            return

        if query.data.startswith("delete_group_"):
            try:
                group_id = query.data.replace("delete_group_", "")

                # Знаходимо та видаляємо групу
                group = self.groups_collection.find_one_and_delete({'_id': ObjectId(group_id)})

                if group:
                    await query.message.edit_text(
                        f"✅ Група '{group['name']}' успішно видалена!"
                    )
                else:
                    await query.message.edit_text("❌ Група не знайдена!")

            except Exception as e:
                await query.message.edit_text(f"❌ Помилка при видаленні: {str(e)}")


def get_group_creation_handler():
    """Повертає handler для створення групи"""
    group_manager = GroupCreationManager(
        mongodb_uri=MONGODB_URI,
        database_name=DB_NAME
    )

    # Створюємо ConversationHandler
    conversation_handler = ConversationHandler(
        entry_points=[CommandHandler('create_user_group', group_manager.start_group_creation)],
        states={
            WAIT_GROUP_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, group_manager.validate_group_name),
            ],
            SELECT_USERS: [
                CallbackQueryHandler(group_manager.handle_user_selection),
            ],
        },
        fallbacks=[CommandHandler('cancel_create_group', group_manager.cancel)],
        name="group_creation",
        persistent=False
    )

    # Повертаємо список хендлерів без рекурсії
    handlers = [
        conversation_handler,
        CommandHandler('delete_user_group', group_manager.delete_group),
        CommandHandler('show_groups', group_manager.show_groups),
        CommandHandler('mention_group', group_manager.mention_group),
        CallbackQueryHandler(
            group_manager.handle_mention_selection,
            pattern='^(mention_group_|cancel_mention)'  # Додаємо новий pattern
        ),
        CallbackQueryHandler(
            group_manager.handle_delete_selection,
            pattern='^(delete_group_|cancel_delete)'
        )
    ]

    return handlers
