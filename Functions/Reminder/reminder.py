import gspread
from google.oauth2.service_account import Credentials
import os
from dotenv import load_dotenv
from telegram.ext import Application, ContextTypes
from telegram import Bot
from telegram import Update
from datetime import datetime, time
import traceback
import pymongo
from Functions.Anti_spam.antispam_handlers import check_spam_decorator, admin_only
from Functions.Logger.Logger_config import logger
import pytz
from datetime import datetime, time

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
        logger.info("Successfully connected to MongoDB")

        # Діагностика
        logger.info("Перевірка підключення до MongoDB...")
        collections = db.list_collection_names()
        logger.info(f"Доступні колекції: {collections}")

        members_count = users_collection.count_documents({})
        logger.info(f"Кількість документів в колекції INFO-Members: {members_count}")

        sample_doc = users_collection.find_one()

        return db, users_collection  # повертаємо кортеж з обома об'єктами
    except Exception as e:
        logger.error(f"Помилка при підключенні до MongoDB: {e}")
        logger.error(traceback.format_exc())
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

@admin_only
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
        db, users_collection = connect_to_mongo()

        # Детальне логування для діагностики
        logger.info(f"Отримано {len(all_values)} рядків з таблиці")
        if all_values:
            logger.info(f"Заголовки таблиці: {all_values[0]}")

        # Get column indices for new table structure
        headers = all_values[0]
        try:
            id_col = headers.index('ID')
            task_title_col = headers.index('Завдання для поста')
            status_col = headers.index('Статус задачі')
            deadline_col = headers.index('Дед-лайн')
            assignee_col = headers.index('Виконавець')
            subtask_col = headers.index('Задача')
            logger.info(
                f"Індекси колонок: ID={id_col}, Title={task_title_col}, Status={status_col}, Deadline={deadline_col}, Assignee={assignee_col}, Subtask={subtask_col}")
        except ValueError as e:
            logger.error(f"Не вдалося знайти необхідні колонки в таблиці: {e}")
            return

        today = datetime.now().strftime('%d.%m.%Y')
        logger.info(f"Сьогоднішня дата для пошуку: {today}")

        reminders = {}  # Групуємо нагадування за ID завдання

        for row_idx, row in enumerate(all_values[1:], start=2):
            # Логування кожного рядка для діагностики
            if len(row) > max(id_col, status_col, deadline_col, assignee_col):
                row_id = row[id_col] if id_col < len(row) else ""
                row_status = row[status_col] if status_col < len(row) else ""
                row_deadline = row[deadline_col] if deadline_col < len(row) else ""
                row_assignee = row[assignee_col] if assignee_col < len(row) else ""

                # Перевіряємо умови для нагадування - використовуємо "Виконується" замість "В роботі"
                is_test_condition = force_test and row_status == 'Виконується' and row_deadline == today
                is_regular_condition = not force_test and row_status == 'Виконується' and row_deadline == today

                if is_test_condition or is_regular_condition:
                    logger.info(f"Знайдено завдання для нагадування в рядку {row_idx}")

                    task_id = row[id_col]
                    task_title = row[task_title_col] if task_title_col < len(row) else ""
                    deadline = row[deadline_col]
                    assignee = row[assignee_col]
                    subtask = row[subtask_col] if subtask_col < len(row) else ""

                    # Якщо для цього завдання ще немає нагадування, створюємо його
                    if task_id not in reminders:
                        reminders[task_id] = {
                            'title': task_title,
                            'deadline': deadline,
                            'subtasks': []
                        }

                    # Додаємо підзавдання до нагадування
                    if assignee.strip():  # Тільки якщо є призначений виконавець
                        reminders[task_id]['subtasks'].append({
                            'subtask': subtask,
                            'assignee': assignee
                        })
                        logger.info(f"Додано підзавдання: '{subtask}' для '{assignee}'")
            else:
                logger.warning(f"Рядок {row_idx} має недостатньо колонок: {len(row)}")

        logger.info(f"Знайдено {len(reminders)} завдань для нагадування")

        # Формуємо та відправляємо нагадування
        if reminders:
            bot = Bot(token=TOKEN)

            for task_id, reminder_data in reminders.items():
                if reminder_data['subtasks']:  # Тільки якщо є підзавдання з виконавцями
                    reminder_text = f"🕒 Нагадування про завдання:\n\n"
                    reminder_text += f"📝 Завдання: {reminder_data['title']}\n"
                    reminder_text += f"🗓️ Дедлайн: {reminder_data['deadline']}\n\n"
                    reminder_text += "👥 Виконавці та їх завдання:\n"

                    usernames = []

                    for subtask_data in reminder_data['subtasks']:
                        assignee = subtask_data['assignee']
                        subtask = subtask_data['subtask']

                        reminder_text += f"• {subtask}: {assignee}\n"

                        # Шукаємо username в MongoDB по повному імені
                        if not assignee.startswith('@'):  # Якщо це повне ім'я, а не username
                            user = users_collection.find_one({'full_name': assignee})
                            if user and 'username' in user and user['username']:
                                usernames.append(f"@{user['username']}")
                                logger.info(f"Знайдено username для '{assignee}': @{user['username']}")
                            else:
                                logger.warning(f"Не знайдено username для користувача: '{assignee}'")
                        else:
                            # Якщо це вже username, додаємо як є
                            usernames.append(assignee)

                    # Додаємо usernames якщо знайдені
                    if usernames:
                        reminder_text += f"\n💬 Згадки: {', '.join(usernames)}"

                    try:
                        await bot.send_message(
                            chat_id=INFO_CHAT_ID,
                            text=reminder_text
                        )
                        logger.info(f"Sent reminder for task {task_id}: {reminder_data['title'][:50]}...")
                    except Exception as send_error:
                        logger.error(f"Failed to send reminder for task {task_id}: {send_error}")
                else:
                    logger.info(f"Пропускаємо завдання {task_id} - немає підзавдань з виконавцями")
        else:
            logger.info("No reminders to send")

    except Exception as e:
        logger.error(f"Reminder generation error: {e}")
        logger.error(traceback.format_exc())


@admin_only
async def set_daily_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Змінює час щоденного нагадування.
    Використання: /set_daily_reminder ГГ:ХХ [часовий_пояс]
    Наприклад: /set_daily_reminder 18:00 Europe/Kyiv
    Або просто: /set_daily_reminder 18:00 (використає Europe/Kyiv за замовчуванням)
    """
    try:
        # Перевіряємо чи надано аргумент з часом
        if not context.args:
            await update.message.reply_text(
                "❌ Будь ласка, вкажіть час у форматі ГГ:ХХ\n"
                "Наприклад: /set_daily_reminder 18:00\n"
                "Або з часовим поясом: /set_daily_reminder 18:00 Europe/Kyiv"
            )
            return

        time_str = context.args[0]

        # Визначаємо часовий пояс
        timezone_str = context.args[1] if len(context.args) > 1 else 'Europe/Kyiv'

        try:
            # Перевіряємо правильність часового поясу
            timezone = pytz.timezone(timezone_str)
        except pytz.exceptions.UnknownTimeZoneError:
            await update.message.reply_text(
                f"❌ Невідомий часовий пояс: {timezone_str}\n"
                "Використовуйте стандартні назви часових поясів, наприклад:\n"
                "• Europe/Kyiv (Київський час)\n"
                "• Europe/Moscow (Московський час)\n"
                "• UTC (Координований всесвітній час)"
            )
            return

        # Перевіряємо правильність формату часу
        try:
            # Парсимо введений час
            parsed_time = datetime.strptime(time_str, '%H:%M').time()

            # Створюємо локалізований час
            today = datetime.now().date()
            naive_datetime = datetime.combine(today, parsed_time)
            localized_time = timezone.localize(naive_datetime).time()

            # Видаляємо старі нагадування
            for job in context.job_queue.jobs():
                if job.name == 'daily_reminder':
                    job.schedule_removal()

            # Встановлюємо нове нагадування
            context.job_queue.run_daily(
                send_task_reminders,
                time=localized_time,
                name='daily_reminder'
            )

            await update.message.reply_text(
                f"✅ Час нагадування успішно встановлено на {time_str} ({timezone_str}).\n"
                f"Нагадування буде надсилатися щодня о цьому часі за вказаним часовим поясом."
            )

            logger.info(f"Встановлено щоденне нагадування на {time_str} в часовому поясі {timezone_str}")

        except ValueError:
            await update.message.reply_text(
                "❌ Неправильний формат часу. Використовуйте формат ГГ:ХХ\n"
                "Наприклад: 18:00"
            )

    except Exception as e:
        await update.message.reply_text(f"❌ Помилка: {str(e)}")
        logger.error(f"Помилка встановлення часу нагадування: {e}")


# Оновлена функція для налаштування щоденного нагадування за замовчуванням
def setup_daily_reminder(application):
    """
    Створення джоба для щоденного нагадування о 16:00 за київським часом
    """
    try:
        # Використовуємо київський часовий пояс
        kyiv_tz = pytz.timezone('Europe/Kyiv')

        # Створюємо локалізований час
        today = datetime.now().date()
        naive_time = datetime.combine(today, time(hour=16, minute=0))
        localized_time = kyiv_tz.localize(naive_time).time()

        application.job_queue.run_daily(
            send_task_reminders,
            time=localized_time,
            name='daily_reminder'
        )

        logger.info("Налаштовано щоденне нагадування на 16:00 київського часу")
    except Exception as e:
        logger.error(f"Помилка налаштування щоденного нагадування: {e}")


@admin_only
async def show_reminder_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Показує поточний розклад нагадувань
    """
    try:
        daily_jobs = [job for job in context.job_queue.jobs() if job.name == 'daily_reminder']

        if not daily_jobs:
            await update.message.reply_text("❌ Щоденні нагадування не налаштовані")
            return

        job = daily_jobs[0]  # Беремо перше (повинно бути тільки одне)

        if job.next_t:
            next_run = job.next_t

            await update.message.reply_text(
                f"📅 Поточний розклад нагадувань:\n\n"
                f"⏰ Час запуску: {next_run.strftime('%H:%M')}\n"
                f"📆 Наступне нагадування: {next_run.strftime('%d.%m.%Y о %H:%M')}\n"
                f"🔄 Повторення: щоденно"
            )
        else:
            await update.message.reply_text("❌ Не вдалося отримати інформацію про розклад")

    except Exception as e:
        await update.message.reply_text(f"❌ Помилка: {str(e)}")
        logger.error(f"Помилка отримання розкладу нагадувань: {e}")


@admin_only
async def test_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually trigger a test reminder"""
    try:
        await update.message.reply_text("Генеруємо тестове нагадування...")
        await send_task_reminders(force_test=True)
        await update.message.reply_text("Тестове нагадування відправлено!")
        logger.info("Manual test reminder triggered")
    except Exception as e:
        logger.error(f"Test reminder error: {e}")
        await update.message.reply_text(f"Помилка генерації тестового нагадування: {e}")


@admin_only
async def test_message(update, context):
    try:
        await context.bot.send_message(
            chat_id=INFO_CHAT_ID,
            text="This is a test message from the reminder bot."
        )
        logger.info("Test message sent successfully.")
    except Exception as e:
        logger.error(f"Error sending test message: {e}")
        logger.error(traceback.format_exc())
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
        setup_daily_reminder,
        set_daily_reminder,
        show_reminder_schedule
    )
    from telegram.ext import CommandHandler

    # Add command handlers for reminder-related commands
    app.add_handler(CommandHandler('check', check_connect_to_sheet))
    app.add_handler(CommandHandler('test_reminder', test_reminder))
    app.add_handler(CommandHandler('test_message', test_message))
    app.add_handler(CommandHandler('set_daily_reminder', set_daily_reminder))
    app.add_handler(CommandHandler('show_reminder_schedule', show_reminder_schedule))

    # Set up daily reminders
    setup_daily_reminder(app)
