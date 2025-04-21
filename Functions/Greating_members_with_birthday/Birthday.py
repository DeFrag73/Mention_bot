import os
from datetime import datetime, timedelta, time
import asyncio
from typing import Optional, List, Dict
import pytz
from telegram import Bot
from telegram.ext import Application, CommandHandler
from pymongo import MongoClient
import google.generativeai as genai

from Functions.Anti_spam.antispam_handlers import admin_only
from Functions.Logger.Logger_config import logger

# Константи
TIMEZONE = pytz.timezone('Europe/Kiev')
CHECK_HOUR = 9
CHECK_MINUTE = 0


class BirthdayGreeter:
    """Клас для привітання учасників комісії з днем народження"""
    def __init__(self, mongo_uri: str, database_name: str, gemini_key: str, work_group_id: str):
        self.client = MongoClient(mongo_uri)
        self.db = self.client[database_name]
        self.members_collection = self.db['INFO-Members']
        self.work_group_id = work_group_id

        # Налаштування Gemini
        genai.configure(api_key=gemini_key)
        self.model = genai.GenerativeModel('gemini-2.0-flash')

        logger.info("BirthdayGreeter успішно ініціалізовано")

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
            logger.error(f"Помилка генерації привітання: {str(e)}")
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
        logger.info(f"Пошук іменинників для дати: {today_format}")

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
            logger.info(f"Знайдено {len(result)} іменинників")
            if result:
                logger.info(f"Знайдені іменинники: {[person.get('full_name') for person in result]}")
            return result

        except Exception as e:
            logger.error(f"Помилка при пошуку іменинників: {str(e)}")
            return []

    async def send_birthday_greetings(self, bot: Bot) -> None:
        """Надсилає привітання іменинникам"""
        try:
            birthday_people = await self.get_birthday_people()
            if not birthday_people:
                logger.info("Сьогодні немає іменинників")
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
                    logger.info(f"Надіслано привітання для {first_name}")
                except Exception as e:
                    logger.error(f"Помилка надсилання привітання: {str(e)}")
        except Exception as e:
            logger.error(f"Помилка обробки привітань: {str(e)}")

    async def birthday_check_loop(self, bot: Bot):
        """Запускає цикл перевірки днів народження"""
        logger.info(f"Запуск циклу перевірки з налаштуваннями: TIMEZONE={TIMEZONE}, CHECK_HOUR={CHECK_HOUR}")

        # Виводимо поточний час на початку роботи
        now = datetime.now(TIMEZONE)
        logger.info(f"Поточний час на початку циклу: {now} (Година: {now.hour}, Хвилина: {now.minute})")
        logger.info(f"Цільовий час перевірки: {CHECK_HOUR}:{CHECK_MINUTE}")

        # Зберігаємо дату останнього привітання
        last_greetings_date = None

        while True:
            try:
                now = datetime.now(TIMEZONE)
                today_date = now.date()

                # Виводимо поточний час у кожній ітерації
                logger.info(f"Поточний час: {now} (Година: {now.hour}, Хвилина: {now.minute})")

                # Надсилаємо привітання, якщо зараз потрібний час і ми ще не вітали сьогодні
                if (now.hour == CHECK_HOUR and
                        now.minute >= CHECK_MINUTE and
                        last_greetings_date != today_date):

                    logger.info(f"Умова виконана! Час для привітань: {now}")
                    await self.send_birthday_greetings(bot)
                    last_greetings_date = today_date
                    logger.info(f"Привітання надіслані {now}. Наступна перевірка завтра.")

                    # Розраховуємо час до наступної перевірки (до завтра)
                    tomorrow = (now + timedelta(days=1)).replace(
                        hour=CHECK_HOUR, minute=CHECK_MINUTE, second=0)
                    seconds_until_tomorrow = (tomorrow - now).total_seconds()
                    logger.info(f"Наступна перевірка через {seconds_until_tomorrow / 3600:.1f} годин")
                    await asyncio.sleep(seconds_until_tomorrow)
                else:
                    # Виводимо причину чому умова не виконана
                    if now.hour != CHECK_HOUR:
                        logger.info(f"Умова не виконана: поточна година {now.hour} != {CHECK_HOUR}")
                    elif now.minute < CHECK_MINUTE:
                        logger.info(f"Умова не виконана: поточна хвилина {now.minute} < {CHECK_MINUTE}")
                    elif last_greetings_date == today_date:
                        logger.info(f"Умова не виконана: привітання вже надіслані сьогодні")

                    # Розраховуємо час до наступної перевірки
                    if now.hour < CHECK_HOUR or (now.hour == CHECK_HOUR and now.minute < CHECK_MINUTE):
                        # Сьогодні ще не було перевірки
                        next_check = now.replace(hour=CHECK_HOUR, minute=CHECK_MINUTE, second=0)
                        logger.info(f"Наступна перевірка сьогодні о {CHECK_HOUR}:{CHECK_MINUTE}")
                    else:
                        # Перевірка сьогодні вже була або час минув, чекаємо до завтра
                        tomorrow = (now + timedelta(days=1))
                        next_check = tomorrow.replace(hour=CHECK_HOUR, minute=CHECK_MINUTE, second=0)
                        logger.info(f"Наступна перевірка завтра о {CHECK_HOUR}:{CHECK_MINUTE}")

                    wait_seconds = (next_check - now).total_seconds()
                    wait_seconds = max(60, min(wait_seconds, 3600))  # Чекаємо від 1 хв до 1 години
                    logger.info(f"Очікуємо наступну перевірку. Сон на {wait_seconds / 60:.1f} хвилин")
                    await asyncio.sleep(wait_seconds)

            except Exception as e:
                logger.error(f"Помилка в циклі перевірки: {str(e)}")
                await asyncio.sleep(300)  # Чекаємо 5 хвилин при помилці


@admin_only
async def test_birthday_command(update, context):
    """Обробник команди /test_birthday"""
    logger.info(f"Отримано команду /test_birthday від користувача {update.effective_user.id}")

    birthday_greeter = context.bot_data.get('birthday_greeter')
    if not birthday_greeter:
        error_msg = "❌ Система привітань не ініціалізована"
        logger.error(error_msg)
        await update.message.reply_text(error_msg)
        return

    try:
        # Перевіряємо підключення до MongoDB
        logger.info("Перевірка підключення до бази даних...")
        await update.message.reply_text("🔄 Перевіряю наявність іменинників...")

        birthday_people = await birthday_greeter.get_birthday_people()
        logger.info(f"Знайдено {len(birthday_people)} іменинників")

        if not birthday_people:
            msg = "📝 Сьогодні немає іменинників"
            logger.info(msg)
            await update.message.reply_text(msg)
            return

        # Якщо є іменинники, надсилаємо привітання
        logger.info("Надсилаю привітання...")
        await birthday_greeter.send_birthday_greetings(context.bot)
        await update.message.reply_text("✅ Тестове привітання надіслано!")

    except Exception as e:
        error_msg = f"❌ Помилка при виконанні тесту: {str(e)}"
        logger.error(error_msg, exc_info=True)
        await update.message.reply_text(error_msg)


def setup_birthday_handler(application: Application, config: dict) -> None:
    # Додаємо вивід поточного часу на початку налаштування
    now = datetime.now(TIMEZONE)
    logger.info(f"Налаштування системи привітань. Поточний час: {now} (Година: {now.hour}, Хвилина: {now.minute})")
    logger.info(f"Система буде перевіряти іменинників о {CHECK_HOUR}:{CHECK_MINUTE}")

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

        # Запускаємо щоденну перевірку в певний час (можна залишити, якщо потрібно)
        application.job_queue.run_daily(
            test_birthday_command,
            time=time(hour=CHECK_HOUR, minute=CHECK_MINUTE),
            days=(0, 1, 2, 3, 4, 5, 6)
        )

        logger.info("Система привітань успішно налаштована")
    except Exception as e:
        logger.error(f"Помилка налаштування системи привітань: {str(e)}")
        raise
