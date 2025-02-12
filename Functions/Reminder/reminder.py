import gspread
from google.oauth2.service_account import Credentials
import os
import logging
from dotenv import load_dotenv
from telegram.ext import ApplicationBuilder, Application, CommandHandler, ContextTypes
from telegram import Bot
from telegram import Update
import asyncio
from datetime import datetime, time
import traceback
import pymongo

load_dotenv()

CREDENTIALS_FILE = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
SPREADSHEET_NAME = os.getenv('SPREADSHEET_NAME')
INFO_CHAT_ID = os.getenv('INFO_CHAT_ID')
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
MONGO_URI = os.getenv('MONGO_URI')
MONGO_DATABASE = os.getenv('MONGO_DATABASE')


def connect_to_mongo():
    try:
        client = pymongo.MongoClient(MONGO_URI)
        db = client[MONGO_DATABASE]
        users_collection = db['INFO-Members']
        logging.info("Successfully connected to MongoDB")
        return users_collection
    except Exception as e:
        logging.error(f"MongoDB connection error: {e}")
        logging.error(traceback.format_exc())
        raise


def connect_to_sheet():
    credential_file = CREDENTIALS_FILE
    spreadsheet_name = SPREADSHEET_NAME

    try:
        # Розширений обсяг доступу для читання та запису
        creds = Credentials.from_service_account_file(
            credential_file,
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",  # Читання та запис
                "https://www.googleapis.com/auth/drive"  # Повний доступ до Google Drive
            ]
        )
        client = gspread.authorize(creds)
        sheet = client.open(spreadsheet_name).get_worksheet(1)
        return sheet
    except FileNotFoundError:
        raise FileNotFoundError(f"Файл облікових даних '{credential_file}' не знайдено. Перевірте шлях.")
    except gspread.exceptions.SpreadsheetNotFound:
        raise Exception(f"Таблицю '{spreadsheet_name}' не знайдено. Перевірте назву.")
    except Exception as e:
        raise Exception(f"Помилка підключення до Google Sheets: {e}")


async def check_connect_to_sheet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    try:
        # Підключення до таблиці
        sheet = connect_to_sheet()
        # Отримання заголовків таблиці
        headers = sheet.row_values(1)
        await context.bot.send_message(chat_id=chat_id,
                                       text=f"✅ Підключення успішне! Заголовки таблиці: {', '.join(headers)}")
    except FileNotFoundError as fnf_error:
        await context.bot.send_message(chat_id=chat_id, text=f"❌ {fnf_error}")
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Помилка: {e}")


async def send_task_reminders(context=None, force_test=False):
    try:
        # Connect to Google Sheet
        sheet = connect_to_sheet()
        all_values = sheet.get_all_values()

        # Connect to MongoDB
        users_collection = connect_to_mongo()

        # Get column indices
        headers = all_values[0]
        status_col = headers.index('Статус поста')
        task_col = headers.index('Завдання для поста')
        deadline_col = headers.index('Дед-лайн')
        image_person_col = headers.index('Картинка')
        text_person_col = headers.index('Текст')

        today = datetime.now().strftime('%d.%m.%Y')

        reminders = []
        for row in all_values[1:]:
            # If force_test is True, or row matches today's deadline
            if (force_test and row[status_col] == 'Виконується' and row[deadline_col] == today or
                    (row[status_col] == 'Виконується' and row[deadline_col] == today)):

                reminder_text = f"🕒 Нагадування про завдання:\n\n"
                reminder_text += f"📝 Завдання: {row[task_col]}\n"
                reminder_text += f"🗓️ Дедлайн: {row[deadline_col]}\n"

                performers = []
                usernames = []

                # Check image and text performers
                if row[image_person_col].strip():
                    performers.append(row[image_person_col])
                if row[text_person_col].strip():
                    performers.append(row[text_person_col])

                # Lookup usernames in MongoDB
                for performer in performers:
                    user = users_collection.find_one({'full_name': performer})
                    if user and 'username' in user:
                        usernames.append(f"@{user['username']}")

                # Add performers to reminder
                if performers:
                    reminder_text += f"👥 Виконавці: {', '.join(performers)}\n"

                # Add usernames if found
                if usernames:
                    reminder_text += f"💬 Usernames: {', '.join(usernames)}\n"

                reminders.append(reminder_text)

        if reminders:
            bot = Bot(token=TOKEN)
            for reminder in reminders:
                try:
                    await bot.send_message(
                        chat_id=INFO_CHAT_ID,
                        text=reminder
                    )
                    logging.info(f"Sent reminder: {reminder[:50]}...")
                except Exception as send_error:
                    logging.error(f"Failed to send reminder: {send_error}")
        else:
            logging.info("No reminders to send")

    except Exception as e:
        logging.error(f"Reminder generation error: {e}")
        logging.error(traceback.format_exc())


# Функція для налаштування щоденного нагадування о 18:00
def setup_daily_reminder(application):
    # Створення джоба для щоденного нагадування о 18:00
    application.job_queue.run_daily(
        send_task_reminders,
        time=datetime.strptime('16:00', '%H:%M').time()
    )


async def test_reminder(update, context):
    """Manually trigger a test reminder"""
    try:
        await update.message.reply_text("Generating test reminder...")
        await send_task_reminders(force_test=True)
        await update.message.reply_text("Test reminder generation completed!")
        logging.info("Manual test reminder triggered")
    except Exception as e:
        logging.error(f"Test reminder error: {e}")
        await update.message.reply_text(f"Error generating test reminder: {e}")


async def test_message(update, context):
    try:
        await context.bot.send_message(
            chat_id=INFO_CHAT_ID,
            text="This is a test message from the reminder bot."
        )
        logging.info("Test message sent successfully.")
    except Exception as e:
        logging.error(f"Error sending test message: {e}")
        logging.error(traceback.format_exc())
        await update.message.reply_text(f"Error sending test message: {e}")


def setup_reminder_functionality(app):
    """
    Set up reminder functionality in the main Telegram bot application.

    Args:
        app (Application): The Telegram bot application
    """
    from Functions.Reminder.reminder import (
        send_task_reminders,
        test_reminder,
        test_message,
        setup_daily_reminder
    )
    from telegram.ext import CommandHandler

    # Add command handlers for reminder-related commands
    app.add_handler(CommandHandler('check', check_connect_to_sheet))
    app.add_handler(CommandHandler('test_reminder', test_reminder))
    app.add_handler(CommandHandler('test_message', test_message))

    # Set up daily reminders
    setup_daily_reminder(app)
