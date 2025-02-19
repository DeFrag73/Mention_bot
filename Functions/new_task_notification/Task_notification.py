from typing import Dict, List, Optional
import os
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackContext, CallbackQueryHandler
from Functions.Reminder.reminder import connect_to_sheet, connect_to_mongo


class TaskNotification:
    def __init__(self):
        self.INFO_CHAT_ID = os.getenv('TEST_CHAT_ID')
        self.ADMIN_ID = os.getenv('ADMIN_ID')

        # Підключення до MongoDB
        self.db = connect_to_mongo()

        # Підключення до Google Sheets
        self.sheet = connect_to_sheet()

    async def check_and_send_tasks(self, context: CallbackContext) -> None:
        """Перевірка та відправка нових завдань"""
        try:
            # Визначаємо очікувані заголовки
            expected_headers = [
                'Завдання для поста',
                'Дата події',
                'Тип посту',
                'Дед-лайн',
                'Статус поста',
                'Картинка',
                'о',  # Порожній стовпець
                'Текст',
                'к',  # Порожній стовпець
                'Фото-закріп',
                'Текст-закріп'
            ]

            records = self.sheet.get_all_records(expected_headers=expected_headers)

            for idx, row in enumerate(records, start=2):
                if row['Статус поста'].lower() == 'не розпочато':
                    buttons = []

                    # Додаємо кнопку "Взятися за дизайн" тільки для stories або reels
                    if row['Тип посту'].lower() in ['stories', 'reels']:
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
                        f"Дедлайн: {row['Дед-лайн']}"
                    )

                    await context.bot.send_message(
                        chat_id=self.INFO_CHAT_ID,
                        text=message_text,
                        reply_markup=keyboard
                    )
        except Exception as e:
            print(f"Помилка при перевірці завдань: {e}")

    async def handle_task_button(self, update: Update, context: CallbackContext) -> None:
        """Обробка натискання кнопок"""
        query = update.callback_query
        action, row_idx = query.data.split('_')
        user = query.from_user

        admin_message = (
            f"Користувач {user.full_name} (@{user.username}) "
            f"хоче взятися за {'дизайн' if action == 'design' else 'текст'}\n"
            f"Завдання з рядка {row_idx}"
        )

        confirm_keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Підтвердити",
                                     callback_data=f"confirm_{action}_{row_idx}_{user.username}"),
                InlineKeyboardButton("❌ Відхилити",
                                     callback_data=f"reject_{action}_{row_idx}_{user.username}")
            ]
        ])

        await context.bot.send_message(
            chat_id=self.ADMIN_ID,
            text=admin_message,
            reply_markup=confirm_keyboard
        )

        await query.answer("Ваш запит надіслано адміністратору")

    async def handle_admin_decision(self, update: Update, context: CallbackContext) -> None:
        """Обробка рішення адміністратора"""
        query = update.callback_query
        # Розділяємо лише на перші 4 частини
        parts = query.data.split('_', 3)

        if len(parts) != 4:
            await query.message.edit_text("Помилка: неправильний формат даних")
            return

        decision, action, row_idx, username = parts

        if decision == 'confirm':
            try:
                # Знаходимо користувача в MongoDB
                member = self.db['INFO-Members'].find_one({"username": username})
                if member:
                    full_name = member['full_name']

                    # Визначаємо індекси стовпців
                    header_row = self.sheet.row_values(1)
                    картинка_col = header_row.index('Картинка') + 1
                    текст_col = header_row.index('Текст') + 1
                    статус_col = header_row.index('Статус поста') + 1

                    # Оновлюємо відповідну комірку
                    if action == 'design':
                        self.sheet.update_cell(int(row_idx), картинка_col, full_name)
                    else:
                        self.sheet.update_cell(int(row_idx), текст_col, full_name)

                    # Перевіряємо чи всі поля заповнені
                    row_data = self.sheet.row_values(int(row_idx))
                    if (row_data[картинка_col - 1].strip() and
                            row_data[текст_col - 1].strip()):
                        self.sheet.update_cell(
                            int(row_idx),
                            статус_col,
                            'Виконується'
                        )

                    await query.message.edit_text(
                        f"✅ Користувача @{username} призначено на завдання"
                    )
            except Exception as e:
                print(f"Помилка при підтвердженні завдання: {e}")
                await query.message.edit_text("Сталася помилка при обробці запиту")

        else:  # reject
            await query.message.edit_text(
                f"❌ Відхилено запит від @{username}"
            )

    def register_handlers(self, application):
        """Реєстрація обробників подій"""
        application.add_handler(CallbackQueryHandler(
            self.handle_task_button,
            pattern='^(design|text)_'))
        application.add_handler(CallbackQueryHandler(
            self.handle_admin_decision,
            pattern='^(confirm|reject)_'))
