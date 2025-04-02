import asyncio
from contextlib import nullcontext
from typing import Dict, List, Optional
import os
from datetime import datetime

import telegram
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackContext, CallbackQueryHandler, CommandHandler

from Functions.Anti_spam.antispam_handlers import admin_only
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
        await self.cleanup_completed_tasks()
        logger.info("Перевірка чи є нові завдання")
        try:
            expected_headers = [
                'Завдання для поста',
                'Дата події',
                'Тип посту',
                'Дед-лайн',
                'Статус поста',
                'Картинка',
                'о',
                'Текст',
                'к',
                'Фото-закріп',
                'Текст-закріп'
            ]

            records = self.sheet.get_all_records(expected_headers=expected_headers)

            for idx, row in enumerate(records, start=2):
                # Перевіряємо чи існує вже завдання з таким row_index
                existing_task = self.task_messages.find_one({'row_index': idx})

                # Якщо завдання не існує і статус "не розпочато"
                if not existing_task and row['Статус поста'].lower() == 'не розпочато':
                    logger.info(f"Нове завдання: {row['Завдання для поста']}")
                    buttons = []

                    if row['Тип посту'].lower() in ['storis', 'reels']:
                        buttons.append([InlineKeyboardButton(
                            "Взятися за дизайн",
                            callback_data=f"design_{idx}")])
                    else:
                        buttons.extend([
                            [InlineKeyboardButton(
                                "Взятися за дизайн",
                                callback_data=f"design_{idx}")],
                            [InlineKeyboardButton(
                                "Взятися за текст",
                                callback_data=f"text_{idx}")]
                        ])

                    keyboard = InlineKeyboardMarkup(buttons)

                    message_text = (
                        f"📋 Нове завдання:\n\n"
                        f"Завдання: {row['Завдання для поста']}\n"
                        f"Тип посту: {row['Тип посту']}\n"
                        f"Дедлайн: {row['Дед-лайн']}"
                    )

                    message = await context.bot.send_message(
                        chat_id=self.INFO_CHAT_ID,
                        message_thread_id=int(self.THREAD_ID),
                        text=message_text,
                        reply_markup=keyboard
                    )

                    # Зберігаємо інформацію про нове повідомлення
                    self.task_messages.insert_one({
                        'message_id': message.message_id,
                        'message_thread_id': self.THREAD_ID,
                        'row_index': idx,
                        'type': row['Тип посту'],
                        'designer': None,
                        'writer': None,
                        'created_at': datetime.now()
                    })

        except Exception as e:
            logger.error(f"Помилка при перевірці завдань: {e}")

    async def handle_task_button(self, update: Update, context: CallbackContext) -> None:
        query = update.callback_query
        action, row_idx = query.data.split('_')
        user = query.from_user
        worksheet_data = self.sheet.get_all_records()
        task_data = worksheet_data[int(row_idx) - 2]

        logger.info(f"Отримано запит від користувача: {user.id} {user.username}")

        # Спочатку перевіряємо чи є користувач в базі
        member = self.users_collection.find_one({
            "username": {"$regex": f"^{user.username}$", "$options": "i"}
        })

        if not member:
            notification_message = (
                "⚠️ Вас не знайдено в базі даних системи сповіщень!\n\n"
                "Можливі причини:\n"
                "• Ви змінили свій нікнейм в Telegram\n"
                "• Ви змінили ім'я користувача\n"
                "• Ви ще не зареєстровані в системі\n\n"
                "🔄 Будь ласка, перереєструйтеся, використовуючи команду /registration"
            )
            await context.bot.send_message(chat_id=user.id, text=notification_message)
            await query.answer("Необхідна перереєстрація")
            return

        # Надсилаємо повідомлення користувачу про очікування
        try:
            await query.answer(
                show_alert=True,
                text="⏳ Ваш запит надіслано адміністратору. Очікуйте на рішення."
            )
        except telegram.error.Forbidden:
            await query.answer(
                "❗ Будь ласка, спочатку активуйте бота в приватних повідомленнях, "
                "щоб отримувати сповіщення",
                show_alert=True
            )
            return

        admin_message = (
            f"Користувач {user.full_name} (@{user.username}) "
            f"хоче взятися за {'дизайн' if action == 'design' else 'текст'}\n"
            f"Завдання з рядка {row_idx}\n"
            f"Опис завдання: {task_data['Завдання для поста']}"
        )

        try:
            admin_msg = await context.bot.send_message(
                chat_id=self.ADMIN_ID,
                text=admin_message,
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("✅ Підтвердити",
                                             callback_data=f"confirm_{action}_{row_idx}_{user.username}"),
                        InlineKeyboardButton("❌ Відхилити",
                                             callback_data=f"reject_{action}_{row_idx}_{user.username}")
                    ]
                ])
            )
            logger.debug(f"Відправлено повідомлення адміну: {admin_msg.message_id}")
        except Exception as e:
            logger.error(f"Помилка при відправці повідомлення адміну: {e}")

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
                result_message = await context.bot.send_message(
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
                картинка_col = header_row.index('Картинка') + 1
                текст_col = header_row.index('Текст') + 1
                статус_col = header_row.index('Статус поста') + 1

                # Знаходимо повідомлення в MongoDB
                task_message = self.task_messages.find_one({'row_index': int(row_idx)})

                if task_message:
                    update_data = {}
                    if action == 'design':
                        update_data['designer'] = username
                        self.sheet.update_cell(int(row_idx), картинка_col, full_name)
                    else:  # text
                        update_data['writer'] = username
                        self.sheet.update_cell(int(row_idx), текст_col, full_name)

                    # Оновлюємо запис в MongoDB
                    self.task_messages.update_one(
                        {'row_index': int(row_idx)},
                        {'$set': update_data}
                    )

                    # Перевіряємо чи потрібно оновити повідомлення або видалити його
                    updated_task = self.task_messages.find_one({'row_index': int(row_idx)})

                    try:
                        if task_message['type'].lower() in ['storis', 'reels']:
                            if updated_task.get('designer'):
                                # Видаляємо повідомлення для stories/reels
                                await context.bot.delete_message(
                                    chat_id=self.INFO_CHAT_ID,
                                    message_id=task_message['message_id']
                                )
                                self.task_messages.delete_one({'row_index': int(row_idx)})
                        else:
                            if updated_task.get('designer') and updated_task.get('writer'):
                                # Видаляємо повідомлення, якщо обидві ролі заповнені
                                try:
                                    await asyncio.sleep(1)  # Затримка в 1 секунду
                                    await context.bot.delete_message(
                                        chat_id=self.INFO_CHAT_ID,
                                        message_id=task_message['message_id']
                                    )
                                except telegram.error.BadRequest as e:
                                    if "Message to delete not found" in str(e):
                                        self.task_messages.delete_one({'row_index': int(row_idx)})
                                        logger.warning(f"Повідомлення вже було видалено: {task_message['message_id']}")
                                    else:
                                        raise e
                            else:
                                # Оновлюємо кнопки
                                buttons = []
                                if not updated_task.get('designer'):
                                    buttons.append([InlineKeyboardButton(
                                        "Взятися за дизайн",
                                        callback_data=f"design_{row_idx}"
                                    )])
                                if not updated_task.get('writer'):
                                    buttons.append([InlineKeyboardButton(
                                        "Взятися за текст",
                                        callback_data=f"text_{row_idx}"
                                    )])

                                if buttons:
                                    await context.bot.edit_message_reply_markup(
                                        chat_id=self.INFO_CHAT_ID,
                                        message_id=task_message['message_id'],
                                        reply_markup=InlineKeyboardMarkup(buttons)
                                    )

                    except Exception as e:
                        logger.error(f"Помилка при оновленні повідомлення: {e}")

                # Оновлюємо статус в таблиці
                self.sheet.update_cell(int(row_idx), статус_col, 'Виконується')

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
        """Функція для очищення бази даних від завершених завдань"""
        try:
            # Отримуємо всі записи з бази даних
            all_tasks = list(self.task_messages.find())

            for task in all_tasks:
                # Перевіряємо чи всі учасники додані
                if task['type'].lower() in ['storis', 'reels']:
                    if task.get('designer'):
                        # Для stories/reels потрібен тільки дизайнер
                        self.task_messages.delete_one({'_id': task['_id']})
                else:
                    # Для інших типів потрібні обидва учасники
                    if task.get('designer') and task.get('writer'):
                        self.task_messages.delete_one({'_id': task['_id']})

            logger.info("Очищення бази даних завершено успішно")
        except Exception as e:
            logger.error(f"Помилка при очищенні бази даних: {e}")

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

    @admin_only
    async def push_tasks(self, update: Update, context: CallbackContext) -> None:
        """Команда для миттєвого сканування нових завдань"""
        await self.check_and_send_tasks(context)
        await update.message.reply_text("✅ Сканування завдань виконано")

    def register_handlers(self, application):
        """Реєстрація обробників подій"""
        application.add_handler(CallbackQueryHandler(
            self.handle_task_button,
            pattern='^(design|text)_'))
        application.add_handler(CallbackQueryHandler(
            self.handle_admin_decision,
            pattern='^(confirm|reject)_'))
        application.add_handler(CommandHandler('thread_info', self.get_thread_info))
        application.add_handler(CommandHandler('push_task', self.push_tasks))
