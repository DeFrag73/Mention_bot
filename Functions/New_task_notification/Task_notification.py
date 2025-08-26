import asyncio
from contextlib import nullcontext
from typing import Dict, List, Optional
import os
from datetime import datetime
import traceback

import telegram
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackContext, CallbackQueryHandler, CommandHandler

from Functions.Anti_spam.antispam_handlers import admin_only, check_spam_decorator
from Functions.Reminder.reminder import connect_to_sheet, connect_to_mongo
from Functions.Logger.Logger_config import logger


class TaskNotification:
    def __init__(self):
        self.INFO_CHAT_ID = os.getenv('INFO_CHAT_ID')
        self.THREAD_ID = int(os.getenv('INFO_CHAT_THREAD_ID'))
        self.ADMIN_ID = os.getenv('ADMIN_ID')

        # Підключення до MongoDB
        self.db, _ = connect_to_mongo()
        self.users_collection = self.db['INFO-Members']
        # Нова колекція для повідомлень
        self.task_messages = self.db['task-messages']
        self.task_messages.create_index('row_index')
        # Нова колекція для запитів на завдання
        self.pending_messages = self.db['pending-task-requests']

        # Підключення до Google Sheets
        self.sheet = connect_to_sheet()

    async def check_and_send_tasks(self, context: CallbackContext) -> None:
        """
        Перевіряє нові завдання і надсилає повідомлення в зазначену гілку.
        """
        try:
            # Перевірка наявності контексту з ботом
            if context is None or context.bot is None:
                logger.error("Відсутній контекст бота при виклику check_and_send_tasks")
                return

            logger.info("Початок перевірки на нові завдання")

            # Отримуємо всі рядки таблиці
            all_rows = self.sheet.get_all_values()
            header_row = all_rows[0]

            # Визначаємо індекси колонок
            id_idx = header_row.index('ID')
            task_title_idx = header_row.index('Завдання для поста')
            status_idx = header_row.index('Статус задачі')
            deadline_idx = header_row.index('Дед-лайн')
            subtask_idx = header_row.index('Задача')

            # Групуємо завдання за ID
            tasks_by_id = {}
            for i, row in enumerate(all_rows[1:], start=2):
                row_idx = i
                if row[id_idx] and row[status_idx] == "Не розпочато":
                    task_id = row[id_idx]
                    if task_id not in tasks_by_id:
                        tasks_by_id[task_id] = {
                            'title': row[task_title_idx],
                            'deadline': row[deadline_idx],
                            'subtasks': []
                        }

                    tasks_by_id[task_id]['subtasks'].append({
                        'text': row[subtask_idx],
                        'row_idx': row_idx
                    })

            # Надсилаємо повідомлення для кожного унікального ID завдання
            for task_id, task_info in tasks_by_id.items():
                if task_info['subtasks']:  # Якщо є підзадачі зі статусом "не розпочато"
                    # Перевіряємо, чи вже існує повідомлення для цього task_id
                    existing_message = self.task_messages.find_one({'post_id': task_id})
                    if existing_message:
                        logger.info(f"Повідомлення для завдання {task_id} вже існує")
                        continue

                    buttons = []
                    for subtask in task_info['subtasks']:
                        buttons.append([InlineKeyboardButton(
                            subtask['text'],
                            callback_data=f"task_{subtask['row_idx']}"
                        )])

                    # Формуємо повідомлення
                    message_text = f"📝 *{task_info['title']}*\n\n"
                    message_text += f"⏰ *Дед-лайн:* {task_info['deadline']}\n\n"
                    message_text += "Доступні завдання:"

                    # Надсилаємо повідомлення в ГІЛКУ чату
                    message = await context.bot.send_message(
                        chat_id=self.INFO_CHAT_ID,
                        message_thread_id=self.THREAD_ID,  # Додаємо ID гілки
                        text=message_text,
                        parse_mode='Markdown',
                        reply_markup=InlineKeyboardMarkup(buttons)
                    )

                    logger.info(f"Надіслано нове повідомлення для завдання {task_id} в гілку {self.THREAD_ID}")

                    # Зберігаємо інформацію про повідомлення в MongoDB
                    self.task_messages.insert_one({
                        'post_id': task_id,  # Використовуємо post_id замість task_id для узгодження
                        'message_id': message.message_id,
                        'subtasks': task_info['subtasks']
                    })

        except Exception as e:
            logger.error(f"Помилка при перевірці та надсиланні завдань: {e}")
            logger.error(traceback.format_exc())

    async def handle_task_button(self, update: Update, context: CallbackContext) -> None:
        """
            Обробляє натискання на кнопку вибору завдання.
            """
        query = update.callback_query
        await query.answer()

        user = query.from_user
        username = user.username
        user_id = user.id

        logger.info(f"Користувач @{username} (ID: {user_id}) натиснув кнопку: {query.data}")

        if not username:
            await query.message.reply_text(
                "Будь ласка, налаштуйте своє ім'я користувача (username) в Telegram перед тим, як брати завдання.",
                message_thread_id=self.THREAD_ID
            )
            logger.warning(f"Користувач ID: {user_id} без username спробував взяти завдання")
            return

        # Розбираємо callback_data
        parts = query.data.split('_')
        task_type = parts[0]  # 'task'
        row_idx = int(parts[1])  # номер рядка

        logger.info(f"Обробка запиту на завдання типу '{task_type}' для рядка {row_idx}")

        # Отримуємо інформацію про повідомлення з MongoDB відповідно до структури бази
        task_message = self.task_messages.find_one({"subtasks.row_idx": row_idx})

        if not task_message:
            await query.message.reply_text(
                "Помилка: завдання не знайдено в базі даних.",
                message_thread_id=self.THREAD_ID
            )
            logger.error(f"Завдання для рядка {row_idx} не знайдено в базі даних")
            return

        # Знаходимо конкретне завдання
        task_id = f"{row_idx}_{task_type}"  # Формуємо унікальний ID завдання
        subtask = None

        for t in task_message['subtasks']:
            if t['row_idx'] == row_idx:
                subtask = t
                break

        if not subtask:
            await query.message.reply_text(
                "Помилка: конкретне завдання не знайдено.",
                message_thread_id=self.THREAD_ID
            )
            logger.error(f"Конкретне завдання з рядком {row_idx} не знайдено")
            return

        # Перевіряємо, чи завдання вже не призначено
        if 'assignee' in subtask and subtask['assignee']:
            await query.message.reply_text(
                f"Це завдання вже взято користувачем @{subtask['assignee']}.",
                message_thread_id=self.THREAD_ID
            )
            logger.info(f"Завдання з рядка {row_idx} вже призначено користувачу @{subtask['assignee']}")
            return


        # Отримуємо дані про завдання з Google Sheet
        all_rows = self.sheet.get_all_values()
        header_row = all_rows[0]
        task_row = all_rows[row_idx - 1]  # -1 тому що індексація в Google Sheets починається з 1

        # Знаходимо індекси колонок
        task_title_idx = header_row.index('Завдання для поста')
        subtask_idx = header_row.index('Задача')
        deadline_idx = header_row.index('Дед-лайн')

        task_title = task_row[task_title_idx]
        subtask_text = task_row[subtask_idx]
        deadline = task_row[deadline_idx]

        # Додаємо інформацію про текст підзавдання з бази даних
        if 'text' in subtask:
            db_subtask_text = subtask['text']
        else:
            db_subtask_text = "Не вказано"

        # Екрануємо спеціальні символи для MarkdownV2
        def escape_markdownv2(text):
            # MarkdownV2 вимагає екранування цих символів: _ * [ ] ( ) ~ ` > # + - = | { } . !
            special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
            for char in special_chars:
                text = text.replace(char, f'\\{char}')
            return text

        # Безпечні версії текстів для MarkdownV2
        safe_task_title = escape_markdownv2(task_title)
        safe_subtask_text = escape_markdownv2(subtask_text)
        safe_db_subtask_text = escape_markdownv2(db_subtask_text)
        safe_deadline = escape_markdownv2(deadline)
        safe_username = escape_markdownv2(username)

        # Формуємо текст для підтвердження
        confirmation_text = f"Користувач @{safe_username} хоче взяти завдання:\n\n"
        confirmation_text += f"*{safe_task_title}*\n"
        confirmation_text += f"Підзавдання з бази: {safe_db_subtask_text}\n"
        confirmation_text += f"Підзавдання з таблиці: {safe_subtask_text}\n"
        confirmation_text += f"Дед\\-лайн: {safe_deadline}"

        # Кнопки для адміністратора
        admin_buttons = [
            [
                InlineKeyboardButton("✅ Підтвердити", callback_data=f"confirm_{row_idx}_{username}"),
                InlineKeyboardButton("❌ Відхилити", callback_data=f"reject_{row_idx}_{username}")
            ]
        ]

        # Надсилаємо повідомлення адміністратору для підтвердження
        try:
            admin_message = await context.bot.send_message(
                chat_id=self.ADMIN_ID,
                text=confirmation_text,
                parse_mode='MarkdownV2',  # Використовуємо MarkdownV2
                reply_markup=InlineKeyboardMarkup(admin_buttons)
            )
        except Exception as e:
            logger.error(f"Помилка при відправці повідомлення адміністратору: {e}")
            # Спробуємо відправити без форматування, якщо сталася помилка
            admin_message = await context.bot.send_message(
                chat_id=self.ADMIN_ID,
                text=f"Користувач @{username} хоче взяти завдання:\n\n{task_title}\nПідзавдання з бази: {db_subtask_text}\nПідзавдання з таблиці: {subtask_text}\nДед-лайн: {deadline}",
                reply_markup=InlineKeyboardMarkup(admin_buttons)
            )

        # Зберігаємо інформацію про запит на завдання з повним ім'ям користувача
        self.pending_messages.insert_one({
            'username': username,  # Зберігаємо повне ім'я користувача
            'user_id': user_id,
            'task_id': task_id,
            'row_idx': row_idx,
            'timestamp': datetime.now()
        })

        # Повідомляємо користувача про відправку запиту
        await query.message.reply_text(
            f"@{username}, ваш запит на завдання відправлено адміністратору. Очікуйте підтвердження.",
            message_thread_id=self.THREAD_ID
        )

        logger.info(f"Запит на завдання з рядка {row_idx} від @{username} надіслано адміністратору")

    async def handle_admin_decision(self, update: Update, context: CallbackContext) -> None:
        """
        Обробляє рішення адміністратора щодо запиту на завдання.
        """
        query = update.callback_query
        await query.answer()

        # Розбираємо callback_data
        parts = query.data.split('_')
        action = parts[0]  # confirm або reject
        row_idx = int(parts[1])  # номер рядка
        username = parts[2]  # ім'я користувача

        logger.info(f"Адміністратор прийняв рішення '{action}' щодо завдання з рядка {row_idx} для @{username}")

        # Отримуємо інформацію про запит з БД
        pending_request = self.pending_messages.find_one({"username": username, "row_idx": row_idx})

        if not pending_request:
            await query.message.edit_text("Помилка: запит на завдання не знайдено.")
            logger.error(f"Запит на завдання з рядка {row_idx} для @{username} не знайдено в базі даних")
            return

        # Отримуємо інформацію про повідомлення з завданням
        task_message = self.task_messages.find_one({"subtasks.row_idx": row_idx})

        if not task_message:
            await query.message.edit_text("Помилка: повідомлення з завданням не знайдено.")
            logger.error(f"Повідомлення з завданням для рядка {row_idx} не знайдено")
            return

        user_id = pending_request['user_id']
        task_id = pending_request['task_id']

        if action == "confirm":
            # Оновлюємо статус завдання в Google Sheet
            sheet_row = row_idx
            all_rows = self.sheet.get_all_values()
            header_row = all_rows[0]

            status_idx = header_row.index('Статус задачі')
            assignee_idx = header_row.index('Виконавець')

            self.sheet.update_cell(sheet_row, status_idx + 1, "В роботі")
            self.sheet.update_cell(sheet_row, assignee_idx + 1, f"@{username}")

            logger.info(f"Оновлено статус завдання в Google Sheet: рядок {sheet_row}, призначено @{username}")

            # Оновлюємо інформацію в MongoDB
            self.task_messages.update_one(
                {"_id": task_message["_id"], "subtasks.row_idx": row_idx},
                {"$set": {"subtasks.$.assignee": username}}
            )

            # Повідомляємо користувача про підтвердження
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"✅ Ваше завдання з рядка {row_idx} підтверджено! Можете починати працювати."
                )
                logger.info(
                    f"Надіслано повідомлення користувачу @{username} про підтвердження завдання з рядка {row_idx}")
            except Exception as e:
                logger.error(f"Не вдалося надіслати повідомлення користувачу @{username}: {e}")

            # Повідомляємо в гілку про призначення завдання
            subtask = next((t for t in task_message['subtasks'] if t['row_idx'] == row_idx), None)
            if subtask:
                subtask_text = subtask['text']
                await context.bot.send_message(
                    chat_id=self.INFO_CHAT_ID,
                    message_thread_id=self.THREAD_ID,
                    text=f"✅ Завдання '{subtask_text}' призначено користувачу @{username}"
                )
                logger.info(
                    f"Надіслано повідомлення в гілку про призначення завдання з рядка {row_idx} користувачу @{username}")

            # Оновлюємо повідомлення для адміна
            await query.message.edit_text(f"✅ Завдання підтверджено для @{username}")

            # Видаляємо запис про запит з pending_messages
            self.pending_messages.delete_one({"_id": pending_request["_id"]})

            # Перевіряємо, чи всі завдання для цього повідомлення вже призначені
            await self.cleanup_completed_tasks(context)

        elif action == "reject":
            # Повідомляємо користувача про відхилення
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"❌ Ваш запит на завдання з рядка {row_idx} відхилено адміністратором."
                )
                logger.info(f"Надіслано повідомлення користувачу @{username} про відхилення завдання з рядка {row_idx}")
            except Exception as e:
                logger.error(f"Не вдалося надіслати повідомлення користувачу @{username}: {e}")

            # Оновлюємо повідомлення для адміна
            await query.message.edit_text(f"❌ Завдання відхилено для @{username}")

            # Видаляємо запис про запит з pending_messages
            self.pending_messages.delete_one({"_id": pending_request["_id"]})

            logger.info(f"Видалено запис про запит на завдання з рядка {row_idx} від @{username} з бази даних")

        logger.info(f"Обробка рішення адміністратора для завдання з рядка {row_idx} успішно завершена")

    async def delete_message(self, context, message_id):
        """
        Видаляє повідомлення з чату.
        """
        try:
            from telegram.error import BadRequest

            await context.bot.delete_message(
                chat_id=self.INFO_CHAT_ID,
                message_id=message_id
            )
            logger.info(f"Успішно видалено повідомлення {message_id}")
            return True
        except BadRequest as e:
            if "Message to delete not found" in str(e):
                logger.warning(f"Повідомлення {message_id} вже видалено або не знайдено")
            else:
                logger.error(f"Помилка при видаленні повідомлення {message_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Помилка при видаленні повідомлення {message_id}: {e}")
            return False

    async def cleanup_completed_tasks(self, context=None):
        """
        Перевіряє, чи всі завдання для повідомлень вже розібрані,
        і якщо так - видаляє їх з бази даних та з чату.
        """
        try:
            # Отримуємо всі повідомлення з завданнями
            all_tasks = list(self.task_messages.find())

            logger.info(f"Початок перевірки завершених завдань. Знайдено {len(all_tasks)} записів з завданнями")

            for task_message in all_tasks:
                message_id = task_message.get('message_id')
                post_id = task_message.get('post_id')
                subtasks = task_message.get('subtasks', [])

                # Перевіряємо, чи всі завдання мають підтверджених виконавців
                all_tasks_assigned = all('assignee' in task and task.get('assignee') is not None for task in subtasks)

                if all_tasks_assigned and subtasks:
                    logger.info(f"Всі завдання для поста {post_id} призначені. Видаляємо повідомлення {message_id}")

                    if context:
                        try:
                            # Видаляємо повідомлення з чату
                            await self.delete_message(context, message_id)
                            logger.info(f"Видалено повідомлення {message_id} для поста {post_id}")
                        except Exception as e:
                            logger.error(f"Не вдалося видалити повідомлення {message_id}: {e}")

                    # Видаляємо запис з бази даних
                    self.task_messages.delete_one({'_id': task_message['_id']})
                    logger.info(f"Видалено запис з бази даних для поста {post_id}")
        except Exception as e:
            logger.error(f"Помилка при очищенні завершених завдань: {e}")
            import traceback
            logger.error(traceback.format_exc())

    @check_spam_decorator
    @admin_only
    async def get_thread_info(self, update: Update, context: CallbackContext) -> None:
        """Команда для отримання інформації про гілку"""
        message = update.message

        thread_info = (
            f"📌 Інформація про повідомлення:\n\n"
            f"Chat ID: {message.chat_id}\n"
            f"Message ID: {message.message_id}\n"
            f"Thread ID: {message.message_thread_id}\n"
        )

        await message.reply_text(thread_info)

    @check_spam_decorator
    @admin_only
    async def push_tasks(self, update: Update, context: CallbackContext) -> None:
        """Команда для миттєвого сканування нових завдань"""
        await self.check_and_send_tasks(context)
        await update.message.reply_text("✅ Сканування завдань виконано")

    def register_handlers(self, application):
        """
        Реєструє обробники подій для Telegram бота.
        Обробляє кнопки вибору завдань та адміністративних рішень.
        """
        # Обробка кнопок для вибору типу завдання
        application.add_handler(CallbackQueryHandler(
            self.handle_task_button,
            pattern='^task_'))

        # Обробка кнопок для підтвердження або відхилення заявок на завдання
        application.add_handler(CallbackQueryHandler(
            self.handle_admin_decision,
            pattern='^(confirm|reject)_'))

        # Обробка команд для отримання інформації про треди та публікації завдань
        application.add_handler(CommandHandler('thread_info', self.get_thread_info))
        application.add_handler(CommandHandler('push_task', self.push_tasks))

        logger.info("Зареєстровано обробники подій для сповіщень про завдання")
