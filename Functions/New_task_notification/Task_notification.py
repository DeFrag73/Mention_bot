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
        self.pending_messages = {}

        # Підключення до Google Sheets
        self.sheet = connect_to_sheet()

    async def check_and_send_tasks(self, context: CallbackContext) -> None:
        """
        Перевіряє нові завдання і надсилає повідомлення.
        Ця функція може бути викликана за розкладом або вручну.
        """
        try:
            # Перевірка наявності контексту з ботом
            if context is None or context.bot is None:
                logger.error("Відсутній контекст бота при виклику check_and_send_tasks")
                return

            # Отримуємо всі рядки таблиці
            all_rows = self.sheet.get_all_values()
            header_row = all_rows[0]

            # Визначаємо індекси колонок
            id_idx = header_row.index('ID')
            task_title_idx = header_row.index('Завдання для поста')
            status_idx = header_row.index('Статус задачі')
            deadline_idx = header_row.index('Дед-лайн')
            subtask_idx = header_row.index('Задача')

            logger.info("Початок перевірки на нові завдання")

            # Групуємо завдання за ID
            tasks_by_id = {}
            for i, row in enumerate(all_rows[1:], start=2):  # Починаємо з 2, бо рядок 1 - це заголовки
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

                    # Надсилаємо повідомлення в чат
                    message = await context.bot.send_message(
                        chat_id=self.INFO_CHAT_ID,
                        text=message_text,
                        parse_mode='Markdown',
                        reply_markup=InlineKeyboardMarkup(buttons)
                    )

                    # Зберігаємо інформацію про повідомлення в MongoDB
                    self.task_messages.insert_one({
                        'task_id': task_id,
                        'message_id': message.message_id,
                        'subtasks': task_info['subtasks']
                    })


        except Exception as e:
            logger.error(f"Помилка при перевірці та надсиланні завдань: {e}")
            logger.error(traceback.format_exc())

    async def handle_task_button(self, update: Update, context: CallbackContext) -> None:
        query = update.callback_query
        action, row_idx = query.data.split('_', 1)

        try:
            # Отримуємо інформацію про користувача
            user = update.effective_user
            username = user.username
            user_id = user.id

            # Перевіряємо, чи користувач є в базі даних
            member = self.users_collection.find_one({"user_id": user_id})
            if not member:
                await query.answer("Ви не зареєстровані. Будь ласка, зверніться до адміністратора.")
                return

            # Отримуємо інформацію про завдання
            row_idx = int(row_idx)
            row = self.sheet.row_values(row_idx)
            header_row = self.sheet.row_values(1)

            task_title_idx = header_row.index('Завдання для поста') + 1
            subtask_idx = header_row.index('Задача') + 1

            task_title = self.sheet.cell(row_idx, task_title_idx).value
            subtask = self.sheet.cell(row_idx, subtask_idx).value

            # Надсилаємо запит адміністратору для підтвердження
            admin_buttons = [
                [
                    InlineKeyboardButton("Підтвердити", callback_data=f"confirm_task_{row_idx}_{username}"),
                    InlineKeyboardButton("Відхилити", callback_data=f"reject_task_{row_idx}_{username}")
                ]
            ]

            admin_text = (
                f"Користувач @{username} хоче взяти завдання:\n\n"
                f"📝 *{task_title}*\n"
                f"📌 *Задача:* {subtask}"
            )

            await context.bot.send_message(
                chat_id=self.ADMIN_ID,
                text=admin_text,
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(admin_buttons)
            )

            # Надсилаємо повідомлення користувачу про очікування
            message = await context.bot.send_message(
                chat_id=user_id,
                text=f"⏳ Ваш запит на завдання відправлено адміністратору. Очікуйте підтвердження."
            )

            # Зберігаємо ID повідомлення для подальшого оновлення
            message_key = f"{user_id}_{row_idx}_task"
            self.pending_messages[message_key] = message.message_id

            await query.answer("Запит надіслано адміністратору")

        except Exception as e:
            logger.error(f"Помилка при обробці кнопки завдання: {e}")
            await query.answer("Сталася помилка. Спробуйте пізніше.")

    async def handle_admin_decision(self, update: Update, context: CallbackContext) -> None:
        query = update.callback_query
        decision, action, row_idx, username = query.data.split('_', 3)

        try:
            # Знаходимо користувача в MongoDB
            member = self.users_collection.find_one({
                "username": {"$regex": f"^{username}$", "$options": "i"}
            })

            if member and 'user_id' in member:
                user_id = member['user_id']
                message_key = f"{user_id}_{row_idx}_{action}"

                # Видаляємо повідомлення про очікування
                if message_key in self.pending_messages:
                    try:
                        await context.bot.edit_message_text(
                            chat_id=user_id,
                            message_id=self.pending_messages[message_key],
                            text="✅ Ваш запит схвалено!" if decision == "confirm" else "❌ Ваш запит відхилено"
                        )
                    except:
                        pass  # Ігноруємо помилки при видаленні
                    del self.pending_messages[message_key]

                # Надсилаємо нове повідомлення про рішення
                await context.bot.send_message(
                    chat_id=user_id,
                    text="✅ Ваш запит схвалено!" if decision == "confirm" else "❌ Ваш запит відхилено"
                )

        except Exception as e:
            logger.error(f"Помилка при відправці повідомлення користувачу: {e}")

        if decision == 'confirm':
            try:
                # Знаходимо користувача в MongoDB
                member = self.users_collection.find_one({
                    "username": {"$regex": f"^{username}$", "$options": "i"}
                })

                if not member:
                    await query.message.edit_text(f"Помилка: користувача @{username} не знайдено в базі даних")
                    return

                full_name = member['full_name']

                # Оновлюємо Google Sheet
                header_row = self.sheet.row_values(1)
                status_idx = header_row.index('Статус задачі') + 1
                executor_idx = header_row.index('Виконавець') + 1

                # Оновлюємо дані в таблиці
                self.sheet.update_cell(int(row_idx), status_idx, 'Виконується')
                self.sheet.update_cell(int(row_idx), executor_idx, full_name)

                # Знаходимо повідомлення в MongoDB
                task_message = self.task_messages.find_one({'subtasks': {'$elemMatch': {'row_idx': int(row_idx)}}})

                if task_message:
                    # Оновлюємо кнопки в повідомленні, видаляючи взяту задачу
                    updated_subtasks = []
                    for subtask in task_message['subtasks']:
                        if subtask['row_idx'] != int(row_idx):
                            updated_subtasks.append(subtask)

                    if updated_subtasks:
                        # Є ще невзяті підзадачі, оновлюємо повідомлення
                        buttons = []
                        for subtask in updated_subtasks:
                            buttons.append([InlineKeyboardButton(
                                subtask['text'],
                                callback_data=f"task_{subtask['row_idx']}"
                            )])

                        await context.bot.edit_message_reply_markup(
                            chat_id=self.INFO_CHAT_ID,
                            message_id=task_message['message_id'],
                            reply_markup=InlineKeyboardMarkup(buttons)
                        )

                        # Оновлюємо запис в MongoDB
                        self.task_messages.update_one(
                            {'_id': task_message['_id']},
                            {'$set': {'subtasks': updated_subtasks}}
                        )
                    else:
                        # Всі підзадачі взяті, видаляємо повідомлення
                        await context.bot.delete_message(
                            chat_id=self.INFO_CHAT_ID,
                            message_id=task_message['message_id']
                        )
                        self.task_messages.delete_one({'_id': task_message['_id']})

                await query.answer("Успішно оновлено")
                await self.cleanup_completed_tasks()
                await query.message.edit_text(
                    f"✅ Користувача @{username} призначено на завдання"
                )

            except Exception as e:
                logger.error(f"Помилка при підтвердженні завдання: {e}")
                await query.message.edit_text(f"Сталася помилка при обробці запиту: {str(e)}")

        else:  # reject
            await query.answer("Відхилено")
            await query.message.edit_text(f"❌ Відхилено запит від @{username}")

    async def delete_message(self, context: CallbackContext):
        """Функція для видалення повідомлення"""
        job = context.job
        try:
            await context.bot.delete_message(
                chat_id=job.data['chat_id'],
                message_id=job.data['message_id']
            )
        except:
            pass

    async def cleanup_completed_tasks(self):
        """
        Перевіряє, чи всі завдання для повідомлень вже розібрані,
        і якщо так - видаляє їх з бази даних та з чату.
        Викликається після рішення адміністратора.
        """
        # Отримуємо всі повідомлення з завданнями
        all_tasks = list(self.task_messages.find())

        for task_message in all_tasks:
            message_id = task_message.get('message_id')
            post_id = task_message.get('post_id')
            tasks = task_message.get('tasks', [])

            # Перевіряємо, чи всі завдання мають підтверджених виконавців
            all_tasks_assigned = all(task.get('assignee') is not None for task in tasks)

            # Якщо всі завдання мають виконавців і список завдань не порожній
            if all_tasks_assigned and tasks:
                try:
                    # Видаляємо повідомлення з чату
                    await self.delete_message(message_id)
                    logger.info(f"Видалено повідомлення {message_id} для поста {post_id}")
                except Exception as e:
                    logger.error(f"Не вдалося видалити повідомлення {message_id}: {e}")

                # Видаляємо запис з бази даних
                self.task_messages.delete_one({'_id': task_message['_id']})
                logger.info(f"Видалено запис з бази даних для поста {post_id}")

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
        # Обробка кнопок для вибору типу завдання (дизайн або текст)
        application.add_handler(CallbackQueryHandler(
            self.handle_task_button,
            pattern='^(design|text)_'))

        # Обробка кнопок для підтвердження або відхилення заявок на завдання
        application.add_handler(CallbackQueryHandler(
            self.handle_admin_decision,
            pattern='^(confirm|reject)_'))

        # Обробка команд для отримання інформації про треди та публікації завдань
        application.add_handler(CommandHandler('thread_info', self.get_thread_info))
        application.add_handler(CommandHandler('push_task', self.push_tasks))

        logger.info("Зареєстровано обробники подій для сповіщень про завдання")

