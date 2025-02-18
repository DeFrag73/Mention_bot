import os
from dataclasses import dataclass
from typing import List, Optional, Tuple
from google.oauth2.credentials import Credentials
import gspread
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, CallbackQuery
from telegram.ext import ContextTypes, CallbackQueryHandler, CommandHandler
from pymongo import MongoClient
from Functions.Reminder.reminder import connect_to_sheet
from Functions.Anti_spam.antispam_handlers import admin_only
import logging
from datetime import datetime

# Налаштування логування
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
       # logging.FileHandler(f'bot_logs_{datetime.now().strftime("%Y%m%d")}.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# Константи
MONGO_URI = os.getenv('MONGO_URI')
DATABASE_NAME = os.getenv('MONGO_DATABASE')
COLLECTION_NAME = 'INFO-Members'
TEST_CHAT_ID = os.getenv('TEST_CHAT_ID')
ADMIN_ID = os.getenv('ADMIN_ID')

# Константи для роботи з Google Sheets
SHEET_COLUMNS = {
    'STATUS': 'Статус поста',
    'TASK': 'Завдання для поста',
    'DEADLINE': 'Дед-лайн',
    'TYPE': 'Тип посту',
    'DESIGN': 'Картинка',
    'TEXT': 'Текст'
}

STORY_POST_TYPES = ['stories', 'reels']
NOT_STARTED_STATUS = 'не розпочато'


@dataclass
class TaskData:
    """Клас для зберігання даних завдання"""
    task: str
    deadline: str
    post_type: str
    row_index: int


class TaskNotificationSystem:
    def __init__(self):
        self.sheet = None
        self.headers = None
        self.column_indices = {}

    def initialize(self):
        """Ініціалізація з'єднання та отримання заголовків"""
        self.sheet = connect_to_sheet()
        self.headers = self.sheet.row_values(1)
        self._setup_column_indices()

    def _setup_column_indices(self):
        """Налаштування індексів стовпців"""
        for key, column_name in SHEET_COLUMNS.items():
            try:
                self.column_indices[key] = self.headers.index(column_name)
            except ValueError:
                raise ValueError(f"Стовпець '{column_name}' не знайдено в таблиці")

    def get_task_data(self, row: List[str], row_idx: int) -> Optional[TaskData]:
        """Отримання даних завдання з рядка"""
        if row[self.column_indices['STATUS']].lower().strip() == NOT_STARTED_STATUS:
            return TaskData(
                task=row[self.column_indices['TASK']],
                deadline=row[self.column_indices['DEADLINE']],
                post_type=row[self.column_indices['TYPE']],
                row_index=row_idx
            )
        return None

    async def send_task_notification(self, context: ContextTypes.DEFAULT_TYPE, task_data: TaskData):
        """Надсилання повідомлення про завдання"""
        buttons = self._create_task_buttons(task_data)
        keyboard = InlineKeyboardMarkup(buttons)
        message_text = self._create_task_message(task_data)

        await context.bot.send_message(
            chat_id=TEST_CHAT_ID,
            text=message_text,
            reply_markup=keyboard,
            parse_mode='Markdown'
        )

    def _create_task_buttons(self, task_data: TaskData) -> List[List[InlineKeyboardButton]]:
        """Створення кнопок для завдання"""
        buttons = []

        if task_data.post_type.lower() in STORY_POST_TYPES:
            buttons.append([
                InlineKeyboardButton(
                    text="Взятися за дизайн",
                    callback_data=f"design_{task_data.row_index}"
                )
            ])
        else:
            buttons.append([
                InlineKeyboardButton(
                    text="Взятися за дизайн",
                    callback_data=f"design_{task_data.row_index}"
                ),
                InlineKeyboardButton(
                    text="Взятися за текст",
                    callback_data=f"text_{task_data.row_index}"
                )
            ])

        return buttons

    def _create_task_message(self, task_data: TaskData) -> str:
        """Створення тексту повідомлення про завдання"""
        return (f"📋 *Нове завдання!*\n\n"
                f"*Завдання:* {task_data.task}\n"
                f"*Дедлайн:* {task_data.deadline}\n"
                f"*Тип:* {task_data.post_type}")


async def check_tasks_implementation(context: ContextTypes.DEFAULT_TYPE):
    """Основна логіка перевірки завдань"""
    try:
        task_system = TaskNotificationSystem()
        task_system.initialize()

        all_values = task_system.sheet.get_all_values()
        for idx, row in enumerate(all_values[1:], start=2):
            task_data = task_system.get_task_data(row, idx)
            if task_data:
                await task_system.send_task_notification(context, task_data)

    except Exception as e:
        error_message = f"❌ Помилка при перевірці завдань: {str(e)}"
        print(error_message)
        await context.bot.send_message(chat_id=ADMIN_ID, text=error_message)


# Обробники команд
async def check_unstarted_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Командний варіант перевірки завдань"""
    await check_tasks_implementation(context)


async def check_unstarted_tasks_job(context: ContextTypes.DEFAULT_TYPE):
    """Планова перевірка завдань"""
    await check_tasks_implementation(context)


@dataclass
class UserRequestData:
    """Клас для зберігання даних запиту користувача"""
    username: str
    full_name: str
    action_type: str
    row_index: int
    task_name: str


@dataclass
class AdminDecisionData:
    """Клас для зберігання даних рішення адміністратора"""
    action: str
    task_type: str
    row_index: int
    username: str


class TaskAssignmentSystem:
    def __init__(self):
        self.sheet = None
        self.mongo_client = None
        self.members_collection = None

    def initialize(self):
        """Ініціалізація з'єднань"""
        self.sheet = connect_to_sheet()
        self.mongo_client = MongoClient(MONGO_URI)
        self.members_collection = self.mongo_client[DATABASE_NAME][COLLECTION_NAME]

    def _parse_callback_data(self, data: str) -> Tuple[str, str]:
        """Розбір даних колбеку"""
        return data.split('_', 1)

    def _create_admin_buttons(self, user_data: UserRequestData) -> InlineKeyboardMarkup:
        """Створення кнопок для адміністратора"""
        buttons = [[
            InlineKeyboardButton(
                "✅ Підтвердити",
                callback_data=f"confirm_{user_data.action_type}_{user_data.row_index}_{user_data.username}"
            ),
            InlineKeyboardButton(
                "❌ Відхилити",
                callback_data=f"reject_{user_data.action_type}_{user_data.row_index}_{user_data.username}"
            )
        ]]
        return InlineKeyboardMarkup(buttons)

    def _create_admin_message(self, user_data: UserRequestData) -> str:
        """Створення повідомлення для адміністратора"""
        action_type_text = 'дизайн' if user_data.action_type == 'design' else 'текст'
        return (f"👤 Користувач *{user_data.full_name}* (@{user_data.username})\n"
                f"хоче взятися за {action_type_text}\n\n"
                f"*Завдання:* {user_data.task_name}")

    def get_task_data(self, row_idx: int) -> List[str]:
        """Отримання даних завдання з таблиці"""
        return self.sheet.row_values(int(row_idx))

    async def update_task_assignment(self, member: dict, admin_data: AdminDecisionData) -> None:
        """Оновлення призначення завдання в таблиці"""
        column = SHEET_COLUMNS['DESIGN'] if admin_data.task_type == 'design' else SHEET_COLUMNS['TEXT']
        column_idx = self.sheet.row_values(1).index(column) + 1
        self.sheet.update_cell(int(admin_data.row_index), column_idx, member['full_name'])


class TaskButtonHandler:
    def __init__(self):
        self.task_system = TaskAssignmentSystem()
        self.logger = logging.getLogger(__name__)

    async def handle_task_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обробка натискання кнопок 'Взятися за дизайн/текст'"""
        try:
            query = update.callback_query
            self.logger.info(f"Отримано callback query від користувача {query.from_user.username}: {query.data}")

            # Перевірка правильності формату даних
            if '_' not in query.data:
                self.logger.error(f"Неправильний формат callback data: {query.data}")
                await query.answer("❌ Помилка формату даних")
                return

            action_type, row_idx = query.data.split('_')

            # Валідація типу дії
            if action_type not in ['design', 'text']:
                self.logger.error(f"Невідомий тип дії: {action_type}")
                await query.answer("❌ Невідомий тип дії")
                return

            self.logger.info(f"Розібрані дані: action_type={action_type}, row_idx={row_idx}")

            # Ініціалізація та отримання даних
            self.task_system.initialize()

            try:
                task_data = self.task_system.get_task_data(row_idx)
                headers = self.task_system.sheet.row_values(1)
                task_idx = headers.index(SHEET_COLUMNS['TASK'])
            except Exception as e:
                self.logger.error(f"Помилка отримання даних з таблиці: {str(e)}")
                await query.answer("❌ Помилка отримання даних завдання")
                return

            # Створення даних запиту користувача
            user_data = UserRequestData(
                username=query.from_user.username,
                full_name=query.from_user.full_name or "Невідомий користувач",
                action_type=action_type,
                row_index=row_idx,
                task_name=task_data[task_idx]
            )

            self.logger.info(f"Створено запит від користувача: {user_data}")

            # Створення клавіатури та повідомлення для адміна
            admin_keyboard = self.task_system._create_admin_buttons(user_data)
            admin_message = self.task_system._create_admin_message(user_data)

            self.logger.info(f"Надсилання повідомлення адміністратору для {user_data.username}")

            # Надсилання повідомлення адміну
            sent_message = await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=admin_message,
                reply_markup=admin_keyboard,
                parse_mode='Markdown'
            )

            if sent_message:
                self.logger.info(f"Повідомлення успішно надіслано адміну (message_id: {sent_message.message_id})")
                await query.answer("✍️ Ваш запит надіслано адміністратору!")
            else:
                self.logger.warning("Не вдалося отримати підтвердження надсилання повідомлення адміну")
                await query.answer("⚠️ Запит надіслано, але виникли проблеми")

        except Exception as e:
            self.logger.error(f"Критична помилка при обробці кнопки: {str(e)}", exc_info=True)
            await query.answer("❌ Виникла помилка. Спробуйте пізніше.")


class AdminDecisionHandler:
    def __init__(self):
        self.task_system = TaskAssignmentSystem()
        self.logger = logging.getLogger(__name__)

    def _parse_admin_decision(self, data: str) -> Optional[AdminDecisionData]:
        """Розбір даних рішення адміністратора"""
        try:
            parts = data.split('_')
            if len(parts) != 4:
                self.logger.error(f"Неправильний формат даних рішення: {data}")
                return None

            action, task_type, row_idx, username = parts

            if action not in ['confirm', 'reject']:
                self.logger.error(f"Невідома дія: {action}")
                return None

            if task_type not in ['design', 'text']:
                self.logger.error(f"Невідомий тип завдання: {task_type}")
                return None

            return AdminDecisionData(action, task_type, row_idx, username)
        except Exception as e:
            self.logger.error(f"Помилка при розборі даних рішення: {str(e)}")
            return None

    async def handle_admin_decision(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обробка рішення адміністратора щодо призначення завдання"""
        try:
            query = update.callback_query
            self.logger.info(f"Отримано рішення адміністратора: {query.data}")

            admin_data = self._parse_admin_decision(query.data)
            if not admin_data:
                await query.answer("❌ Помилка формату даних рішення")
                return

            self.task_system.initialize()

            if admin_data.action == 'confirm':
                await self._handle_confirmation(context, query, admin_data)
            else:
                await self._handle_rejection(context, query, admin_data)

        except Exception as e:
            self.logger.error(f"Помилка при обробці рішення адміністратора: {str(e)}", exc_info=True)
            await query.edit_message_text(text="❌ Виникла помилка при обробці рішення")

    async def _handle_confirmation(self, context, query, admin_data):
        try:
            # Знаходимо користувача в базі даних
            member = self.task_system.members_collection.find_one({"username": admin_data.username})
            if not member:
                await query.edit_message_text("❌ Користувача не знайдено в базі даних")
                return

            # Оновлюємо призначення в таблиці
            await self.task_system.update_task_assignment(member, admin_data)

            # Повідомляємо про успішне призначення
            await query.edit_message_text(
                f"✅ Завдання призначено для @{admin_data.username}\n"
                f"Тип: {'дизайн' if admin_data.task_type == 'design' else 'текст'}"
            )

            # Надсилаємо повідомлення користувачу
            await context.bot.send_message(
                chat_id=member['chat_id'],
                text=f"✅ Ваш запит на {'дизайн' if admin_data.task_type == 'design' else 'текст'} було підтверджено!"
            )

        except Exception as e:
            self.logger.error(f"Помилка при підтвердженні завдання: {str(e)}")
            await query.edit_message_text("❌ Помилка при призначенні завдання")

    async def _handle_rejection(self, context, query, admin_data):
        try:
            # Знаходимо користувача в базі даних
            member = self.task_system.members_collection.find_one({"username": admin_data.username})
            if not member:
                await query.edit_message_text("❌ Користувача не знайдено в базі даних")
                return

            # Повідомляємо про відхилення
            await query.edit_message_text(
                f"❌ Запит відхилено для @{admin_data.username}\n"
                f"Тип: {'дизайн' if admin_data.task_type == 'design' else 'текст'}"
            )

            # Надсилаємо повідомлення користувачу
            await context.bot.send_message(
                chat_id=member['chat_id'],
                text=f"❌ Ваш запит на {'дизайн' if admin_data.task_type == 'design' else 'текст'} було відхилено"
            )

        except Exception as e:
            self.logger.error(f"Помилка при відхиленні завдання: {str(e)}")
            await query.edit_message_text("❌ Помилка при відхиленні завдання")


@admin_only
def setup_task_handlers(application):
    """Налаштування обробників для функціонала завдань"""
    logger = logging.getLogger(__name__)

    # Створюємо екземпляри обробників
    button_handler = TaskButtonHandler()
    admin_handler = AdminDecisionHandler()

    # Додаємо обробники з чіткими патернами
    application.add_handler(CallbackQueryHandler(
        button_handler.handle_task_button,
        pattern='^(design|text)_[0-9]+$'
    ))

    application.add_handler(CallbackQueryHandler(
        admin_handler.handle_admin_decision,
        pattern='^(confirm|reject)_(design|text)_[0-9]+_[\w\d]+$'
    ))

    application.add_handler(CommandHandler('check_tasks', check_unstarted_tasks))

    logger.info("Обробники завдань успішно налаштовано")
