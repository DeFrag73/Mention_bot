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

        user = query.from_user
        username = user.username
        user_id = user.id

        logger.info(f"Користувач @{username} (ID: {user_id}) натиснув кнопку: {query.data}")

        if not username:
            await query.answer(
                "Будь ласка, налаштуйте своє ім'я користувача (username) в Telegram перед тим, як брати завдання.",
                show_alert=True
            )
            logger.warning(f"Користувач ID: {user_id} без username спробував взяти завдання")
            return

        # Перевіряємо, чи користувач зареєстрований в системі
        user_info = self.users_collection.find_one({"username": username})
        if not user_info or not user_info.get('full_name'):
            await query.answer(
                "❌ Ви не зареєстровані в системі!\n"
                "Будь ласка, спочатку пройдіть реєстрацію в боті командою /registration",
                show_alert=True
            )
            logger.warning(f"Незареєстрований користувач @{username} спробував взяти завдання")
            return

        # Розбираємо callback_data
        parts = query.data.split('_')
        task_type = parts[0]  # 'task'
        row_idx = int(parts[1])  # номер рядка

        logger.info(f"Обробка запиту на завдання типу '{task_type}' для рядка {row_idx}")

        # Перевіряємо, чи користувач уже не відправляв запит на це завдання
        existing_request = self.pending_messages.find_one({
            "user_id": user_id,
            "row_idx": row_idx
        })

        if existing_request:
            await query.answer(
                "⚠️ Ви вже відправили запит на це завдання!\n"
                "Очікуйте рішення адміністратора. Не потрібно натискати кнопку повторно.",
                show_alert=True
            )
            logger.info(f"Користувач @{username} спробував повторно взяти завдання з рядка {row_idx}")
            return

        # Отримуємо інформацію про повідомлення з MongoDB відповідно до структури бази
        task_message = self.task_messages.find_one({"subtasks.row_idx": row_idx})

        if not task_message:
            await query.answer(
                "Помилка: завдання не знайдено в базі даних.",
                show_alert=True
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
            await query.answer(
                "Помилка: конкретне завдання не знайдено.",
                show_alert=True
            )
            logger.error(f"Конкретне завдання з рядком {row_idx} не знайдено")
            return

        # Перевіряємо, чи завдання вже не призначено
        if 'assignee' in subtask and subtask['assignee']:
            await query.answer(
                f"Це завдання вже взято користувачем @{subtask['assignee']}.",
                show_alert=True
            )
            logger.info(f"Завдання з рядка {row_idx} вже призначено користувачу @{subtask['assignee']}")
            return

        # Отримуємо дані про завдання з Google Sheet
        all_rows = self.sheet.get_all_values()
        header_row = all_rows[0]
        task_row = all_rows[row_idx - 1]  # -1, бо індексація в Google Sheets починається з 1

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

        # Отримуємо повне ім'я користувача
        full_name = user_info['full_name']
        logger.info(f"Знайдено повне ім'я користувача @{username}: {full_name}")

        # Екрануємо спеціальні символи для MarkdownV2
        def escape_markdown_special_chars(text):
            # MarkdownV2 вимагає екранування цих символів: _ * [ ] ( ) ~ ` > # + - = | { } . !
            special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
            for char in special_chars:
                text = text.replace(char, f'\\{char}')
            return text

        # Безпечні версії текстів для MarkdownV2
        safe_task_title = escape_markdown_special_chars(task_title)
        safe_subtask_text = escape_markdown_special_chars(subtask_text)
        safe_db_subtask_text = escape_markdown_special_chars(db_subtask_text)
        safe_deadline = escape_markdown_special_chars(deadline)
        safe_username = escape_markdown_special_chars(username)
        safe_full_name = escape_markdown_special_chars(full_name)

        # Формуємо текст для підтвердження - показуємо і username і повне ім'я
        confirmation_text = f"Користувач {safe_full_name} \\(@{safe_username}\\) хоче взяти завдання:\n\n"
        confirmation_text += f"*{safe_task_title}*\n"
        confirmation_text += f"Підзавдання з бази: {safe_db_subtask_text}\n"
        confirmation_text += f"Підзавдання з таблиці: {safe_subtask_text}\n"
        confirmation_text += f"Дед\\-лайн: {safe_deadline}"

        # Кнопки для адміністратора
        admin_buttons = [
            [
                InlineKeyboardButton("✅ Підтвердити", callback_data=f"confirm_{row_idx}_{user_id}"),
                InlineKeyboardButton("❌ Відхилити", callback_data=f"reject_{row_idx}_{user_id}")
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
                text=f"Користувач {full_name} (@{username}) хоче взяти завдання:\n\n{task_title}\nПідзавдання з бази: {db_subtask_text}\nПідзавдання з таблиці: {subtask_text}\nДед-лайн: {deadline}",
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

        # Показуємо попередження користувачеві на екрані
        await query.answer(
            f"{full_name}, ваш запит на завдання відправлено адміністратору. Очікуйте підтвердження.",
            show_alert=True
        )

        logger.info(f"Запит на завдання з рядка {row_idx} від @{username} ({full_name}) надіслано адміністратору")

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
        user_id = int(parts[2])  # ID користувача замість username

        logger.info(
            f"Адміністратор прийняв рішення '{action}' щодо завдання з рядка {row_idx} для користувача ID: {user_id}")

        # Отримуємо інформацію про запит з БД по user_id та row_idx
        pending_request = self.pending_messages.find_one({"user_id": user_id, "row_idx": row_idx})

        if not pending_request:
            # Спробуємо знайти запит тільки по user_id
            pending_request_by_user = self.pending_messages.find_one({"user_id": user_id})
            if pending_request_by_user:
                logger.warning(f"Знайдено запит тільки по user_id: {pending_request_by_user}")
                pending_request = pending_request_by_user
            else:
                await query.message.edit_text("Помилка: запит на завдання не знайдено.")
                logger.error(
                    f"Запит на завдання з рядка {row_idx} для користувача ID {user_id} не знайдено в базі даних")
                return

        # Отримуємо username з знайденого запиту
        username = pending_request['username']

        # Шукаємо користувача в базі INFO-Members для отримання повного імені
        user_info = self.users_collection.find_one({"username": username})
        if user_info and user_info.get('full_name'):
            full_name = user_info['full_name']
            logger.info(f"Знайдено повне ім'я користувача @{username}: {full_name}")
        else:
            full_name = f"@{username}"
            logger.warning(f"Користувач @{username} не знайдений в базі INFO-Members, використовуємо username")

        # Отримуємо інформацію про повідомлення із завданням
        task_message = self.task_messages.find_one({"subtasks.row_idx": row_idx})

        if not task_message:
            await query.message.edit_text("Помилка: повідомлення з завданням не знайдено.")
            logger.error(f"Повідомлення з завданням для рядка {row_idx} не знайдено")
            return

        task_id = pending_request['task_id']
        actual_row_idx = pending_request.get('row_idx', row_idx)

        if action == "confirm":
            # Оновлюємо статус завдання в Google Sheet
            sheet_row = actual_row_idx
            all_rows = self.sheet.get_all_values()
            header_row = all_rows[0]

            status_idx = header_row.index('Статус задачі')
            assignee_idx = header_row.index('Виконавець')

            # Записуємо повне ім'я замість username
            self.sheet.update_cell(sheet_row, status_idx + 1, "Виконується")
            self.sheet.update_cell(sheet_row, assignee_idx + 1, full_name)

            logger.info(f"Оновлено статус завдання в Google Sheet: рядок {sheet_row}, призначено {full_name}")

            # Оновлюємо інформацію в MongoDB - зберігаємо username для внутрішньої логіки
            self.task_messages.update_one(
                {"_id": task_message["_id"], "subtasks.row_idx": actual_row_idx},
                {"$set": {"subtasks.$.assignee": username}}
            )

            # Оновлюємо повідомлення з кнопками - видаляємо кнопку підтвердженого завдання
            await self.update_message_buttons(context, task_message, actual_row_idx)

            # Повідомляємо користувача про підтвердження
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"✅ Ваше завдання з рядка {actual_row_idx} підтверджено! Можете починати працювати."
                )
                logger.info(
                    f"Надіслано повідомлення користувачу @{username} про підтвердження завдання з рядка {actual_row_idx}")
            except Exception as e:
                logger.error(f"Не вдалося надіслати повідомлення користувачу @{username}: {e}")

            # Оновлюємо повідомлення для адміна - використовуємо повне ім'я
            await query.message.edit_text(f"✅ Завдання підтверджено для {full_name}")

            # Видаляємо запис про запит з pending_messages
            self.pending_messages.delete_one({"_id": pending_request["_id"]})

            # Перевіряємо, чи всі завдання для цього повідомлення вже призначені
            await self.cleanup_completed_tasks(context)

        elif action == "reject":
            # Повідомляємо користувача про відхилення
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"❌ Ваш запит на завдання з рядка {actual_row_idx} відхилено адміністратором."
                )
                logger.info(
                    f"Надіслано повідомлення користувачу @{username} про відхилення завдання з рядка {actual_row_idx}")
            except Exception as e:
                logger.error(f"Не вдалося надіслати повідомлення користувачу @{username}: {e}")

            # Оновлюємо повідомлення для адміна - використовуємо повне ім'я
            await query.message.edit_text(f"❌ Завдання відхилено для {full_name}")

            # Видаляємо запис про запит з pending_messages
            self.pending_messages.delete_one({"_id": pending_request["_id"]})

            logger.info(f"Видалено запис про запит на завдання з рядка {actual_row_idx} від @{username} з бази даних")

        logger.info(f"Обробка рішення адміністратора для завдання з рядка {actual_row_idx} успішно завершена")

    async def update_message_buttons(self, context: CallbackContext, task_message, completed_row_idx):
        """
        Оновлює кнопки в повідомленні, видаляючи кнопку завершеного завдання.
        """
        try:
            message_id = task_message['message_id']
            subtasks = task_message['subtasks']

            # Створюємо нові кнопки, виключаючи завершене завдання
            buttons = []
            for subtask in subtasks:
                # Пропускаємо завдання, які вже мають призначеного виконавця або це завершене завдання
                if subtask['row_idx'] == completed_row_idx or subtask.get('assignee'):
                    continue

                buttons.append([InlineKeyboardButton(
                    subtask['text'],
                    callback_data=f"task_{subtask['row_idx']}"
                )])

            # Якщо залишились кнопки, оновлюємо повідомлення
            if buttons:
                await context.bot.edit_message_reply_markup(
                    chat_id=self.INFO_CHAT_ID,
                    message_id=message_id,
                    reply_markup=InlineKeyboardMarkup(buttons)
                )
                logger.info(
                    f"Оновлено кнопки в повідомленні {message_id}, видалено завдання з рядка {completed_row_idx}")
            else:
                # Якщо кнопок не залишилось, видаляємо повідомлення
                await context.bot.delete_message(
                    chat_id=self.INFO_CHAT_ID,
                    message_id=message_id
                )
                logger.info(f"Видалено повідомлення {message_id} - всі завдання призначені")

        except Exception as e:
            logger.error(f"Помилка при оновленні кнопок повідомлення: {e}")

    async def delete_message(self, context, message_id):
        """
        Видаляє повідомлення із чату.
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
        Перевіряє, чи всі завдання для повідомлень у розібрані,
        і якщо так - видаляє їх з бази даних та із чату.
        """
        try:
            # Отримуємо всі повідомлення із завданнями
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
                            # Видаляємо повідомлення із чату
                            await self.delete_message(context, message_id)
                            logger.info(f"Видалено повідомлення {message_id} для поста {post_id}")
                        except Exception as e:
                            logger.error(f"Не вдалося видалити повідомлення {message_id}: {e}")

                    # Видаляємо запис із бази даних
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
        Реєструє обробник подій для Telegram бота.
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
