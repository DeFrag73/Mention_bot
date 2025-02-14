import os
from datetime import datetime
import asyncio
from typing import Optional, List, Dict
import pytz
import logging
from telegram import Bot
from telegram.ext import Application, CommandHandler
from pymongo import MongoClient
import google.generativeai as genai

from Functions.Anti_spam.antispam_handlers import admin_only

# Налаштування логування
birthday_logger = logging.getLogger('birthday_greetings')
birthday_logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler = logging.FileHandler('birthday_greetings.log', encoding='utf-8')
file_handler.setFormatter(formatter)
birthday_logger.addHandler(file_handler)

# Константи
TIMEZONE = pytz.timezone('Europe/Kiev')
CHECK_HOUR = 9
CHECK_MINUTE = 0


class BirthdayGreeter:
    def __init__(self, mongo_uri: str, database_name: str, gemini_key: str, work_group_id: str):
        self.client = MongoClient(mongo_uri)
        self.db = self.client[database_name]
        self.members_collection = self.db['INFO-Members']
        self.work_group_id = work_group_id

        # Налаштування Gemini
        genai.configure(api_key=gemini_key)
        self.model = genai.GenerativeModel('gemini-pro')

        birthday_logger.info("BirthdayGreeter успішно ініціалізовано")

    async def generate_birthday_message(self, first_name: str, telegram_username: Optional[str] = None) -> str:
        try:
            mention = f"@{telegram_username}" if telegram_username else first_name

            prompt = f"""
            Ти експерт з написання теплих і душевних привітань з днем народження.
            Напиши душевне привітання з днем народження для {first_name} (звертання {mention}).
            Використовуй обидва варіанти звертання у тексті - і {first_name}, і {mention}.
            Використовуй емодзі. Привітання має бути коротким але щирим.
            Пиши українською мовою.
            """

            response = await asyncio.to_thread(
                self.model.generate_content,
                prompt
            )

            if response.text:
                return response.text
            else:
                return self._get_default_greeting(mention, first_name)

        except Exception as e:
            birthday_logger.error(f"Помилка генерації привітання: {str(e)}")
            return self._get_default_greeting(mention, first_name)

    def _get_default_greeting(self, mention: str, first_name: str) -> str:
        """Повертає стандартне привітання"""
        return (f"🎉 Вітаємо {mention} з Днем Народження! 🎂\n\n"
                f"Любий(а) {first_name}, бажаємо міцного здоров'я, успіхів та щастя! 🌟\n"
                f"Нехай кожен день приносить радість та натхнення! ✨")

    async def get_birthday_people(self) -> List[Dict]:
        """Отримує список людей у яких сьогодні день народження"""
        today = datetime.now(TIMEZONE)
        today_format = f"{today.day:02d}.{today.month:02d}"  # Формат "DD.MM"
        birthday_logger.info(f"Пошук іменинників для дати: {today_format}")

        try:
            # Використовуємо регулярний вираз для порівняння дати
            pipeline = [{
                "$addFields": {
                    "birthDayMonth": {
                        "$substr": ["$birthday", 0, 5]  # Беремо перші 5 символів (DD.MM)
                    }
                }
            }, {
                "$match": {
                    "birthDayMonth": today_format
                }
            }]

            result = list(self.members_collection.aggregate(pipeline))
            birthday_logger.info(f"Знайдено {len(result)} іменинників")
            if result:
                birthday_logger.info(f"Знайдені іменинники: {[person.get('full_name') for person in result]}")
            return result

        except Exception as e:
            birthday_logger.error(f"Помилка при пошуку іменинників: {str(e)}")
            return []

    async def send_birthday_greetings(self, bot: Bot) -> None:
        """Надсилає привітання іменинникам"""
        try:
            birthday_people = await self.get_birthday_people()
            if not birthday_people:
                birthday_logger.info("Сьогодні немає іменинників")
                return

            for person in birthday_people:
                first_name = person['full_name'].split()[0]
                telegram_username = person.get('username')
                greeting = await self.generate_birthday_message(first_name, telegram_username)

                try:
                    await bot.send_message(
                        chat_id=self.work_group_id,
                        text=greeting,
                        parse_mode='HTML'
                    )
                    birthday_logger.info(f"Надіслано привітання для {first_name}")
                except Exception as e:
                    birthday_logger.error(f"Помилка надсилання привітання: {str(e)}")
        except Exception as e:
            birthday_logger.error(f"Помилка обробки привітань: {str(e)}")

    async def birthday_check_loop(self, bot: Bot):
        """Запускає цикл перевірки днів народження"""
        while True:
            try:
                now = datetime.now(TIMEZONE)
                if now.hour == CHECK_HOUR and now.minute == CHECK_MINUTE:
                    await self.send_birthday_greetings(bot)
                await asyncio.sleep(60)
            except Exception as e:
                birthday_logger.error(f"Помилка в циклі перевірки: {str(e)}")
                await asyncio.sleep(60)


@admin_only
async def test_birthday_command(update, context):
    """Обробник команди /test_birthday"""
    birthday_logger.info(f"Отримано команду /test_birthday від користувача {update.effective_user.id}")

    birthday_greeter = context.bot_data.get('birthday_greeter')
    if not birthday_greeter:
        error_msg = "❌ Система привітань не ініціалізована"
        birthday_logger.error(error_msg)
        await update.message.reply_text(error_msg)
        return

    try:
        # Перевіряємо підключення до MongoDB
        birthday_logger.info("Перевірка підключення до бази даних...")
        await update.message.reply_text("🔄 Перевіряю наявність іменинників...")

        birthday_people = await birthday_greeter.get_birthday_people()
        birthday_logger.info(f"Знайдено {len(birthday_people)} іменинників")

        if not birthday_people:
            msg = "📝 Сьогодні немає іменинників"
            birthday_logger.info(msg)
            await update.message.reply_text(msg)
            return

        # Якщо є іменинники, надсилаємо привітання
        birthday_logger.info("Надсилаю привітання...")
        await birthday_greeter.send_birthday_greetings(context.bot)
        await update.message.reply_text("✅ Тестове привітання надіслано!")

    except Exception as e:
        error_msg = f"❌ Помилка при виконанні тесту: {str(e)}"
        birthday_logger.error(error_msg, exc_info=True)
        await update.message.reply_text(error_msg)


def setup_birthday_handler(application: Application, config: dict) -> None:
    required_config = ['MONGODB_URI', 'DATABASE_NAME', 'GEMINI_API_KEY', 'WORK_GROUP_ID']
    for param in required_config:
        if param not in config:
            raise ValueError(f"Відсутній обов'язковий параметр конфігурації: {param}")

    try:
        birthday_greeter = BirthdayGreeter(
            mongo_uri=config['MONGODB_URI'],
            database_name=config['DATABASE_NAME'],
            gemini_key=config['GEMINI_API_KEY'],
            work_group_id=config['WORK_GROUP_ID']
        )

        application.bot_data['birthday_greeter'] = birthday_greeter
        application.add_handler(CommandHandler('test_birthday', test_birthday_command))

        application.job_queue.run_repeating(
            lambda context: context.application.create_task(
                birthday_greeter.birthday_check_loop(context.application.bot)
            ),
            interval=24 * 60 * 60,
            first=0
        )

        birthday_logger.info("Система привітань успішно налаштована")
    except Exception as e:
        birthday_logger.error(f"Помилка налаштування системи привітань: {str(e)}")
        raise
