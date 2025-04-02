from telegram import Update, ChatPermissions
from telegram.error import TimedOut
from telegram.ext import CommandHandler, ContextTypes
import asyncio
from Functions.Anti_spam.anti_spam import AntiSpam
import functools
from time import time
import os
from dotenv import load_dotenv

from Functions.Logger.Logger_config import logger

load_dotenv()


def check_spam_decorator(func):
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if not update.effective_user:
            return await func(update, context, *args, **kwargs)

        # Отримуємо обробник спаму зі словника bot_data
        spam_handlers = context.bot_data['spam_handlers']

        # Перевіряємо на спам
        if await spam_handlers.check_spam(update):
            return

        return await func(update, context, *args, **kwargs)

    return wrapper


def admin_only(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        # Визначаємо, чи це метод класу чи звичайна функція
        if len(args) >= 2 and isinstance(args[1], Update):
            # Це метод класу (self, update, context, ...)
            update = args[1]
            context = args[2]
        elif len(args) >= 1 and isinstance(args[0], Update):
            # Це звичайна функція (update, context, ...)
            update = args[0]
            context = args[1]
        else:
            logger.error("Неправильні аргументи для декоратора admin_only")
            return

        if not update.effective_user:
            await update.message.reply_text("Користувача не знайдено.")
            return

        admin_id = int(os.getenv('ADMIN_ID'))

        if update.effective_user.id != admin_id:
            await update.message.reply_text("Ця команда доступна тільки адміністратору.")
            return

        return await func(*args, **kwargs)

    return wrapper


class SpamHandlers:
    def __init__(self, mongodb_uri: str, admin_id: int):
        self.anti_spam = AntiSpam(
            mongodb_uri=mongodb_uri,
            messages_limit=5,
            time_window=5,
            ban_time=360
        )
        self.admin_id = admin_id
        self.muted_users = {}

    async def check_spam(self, update: Update) -> bool:
        """Перевірка на спам з мутом користувача"""
        if update.effective_user and update.effective_chat:
            user_id = update.effective_user.id
            is_spam, message = self.anti_spam.is_spam(user_id)

            if is_spam:
                try:
                    current_time = time()

                    # Перевіряємо, чи користувач вже замучений
                    if user_id in self.muted_users:
                        # Якщо вже замучений, не надсилаємо повторне повідомлення
                        return True

                    # Встановлюємо обмеження для користувача
                    await update.effective_chat.restrict_member(
                        user_id,
                        permissions=ChatPermissions(
                            can_send_messages=False,
                            can_send_polls=False,
                            can_send_other_messages=False,
                            can_add_web_page_previews=False,
                            can_invite_users=False
                        ),
                        until_date=current_time + self.anti_spam.ban_time
                    )

                    # Зберігаємо інформацію про мут
                    self.muted_users[user_id] = current_time

                    # Надсилаємо повідомлення про мут
                    await update.message.reply_text(
                        f"Вас замучено на {self.anti_spam.ban_time} секунд через спам.\n"
                        f"Після закінчення терміну мута ви зможете знову писати повідомлення."
                    )

                    # Запускаємо таймер для розмуту
                    asyncio.create_task(self._unmute_user(update, user_id))

                    return True

                except TimedOut:
                    logger.error("Помилка таймауту при встановленні мута")
                    return False
                except Exception as e:
                    logger.error(f"Помилка при встановленні мута: {e}")
                    return False

        return False

    async def _unmute_user(self, update: Update, user_id: int):
        """Автоматичний розмут користувача після закінчення терміну"""
        await asyncio.sleep(self.anti_spam.ban_time)

        try:
            # Знімаємо обмеження
            await update.effective_chat.restrict_member(
                user_id,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_polls=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True,
                    can_invite_users=True
                )
            )

            # Видаляємо користувача з списку замучених
            if user_id in self.muted_users:
                del self.muted_users[user_id]

        except Exception as e:
            logger.error(f"Помилка при знятті мута: {e}")

    @admin_only
    async def whitelist_add(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Додавання до білого списку"""
        if update.effective_user.id == self.admin_id:
            try:
                user_id = int(context.args[0])
                self.anti_spam.add_to_whitelist(user_id)
                await update.message.reply_text(f"Користувач {user_id} доданий до білого списку")
            except:
                await update.message.reply_text("Використання: /whitelist_add user_id")

    @admin_only
    async def whitelist_remove(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Видалення з білого списку"""
        if update.effective_user.id == self.admin_id:
            try:
                user_id = int(context.args[0])
                self.anti_spam.remove_from_whitelist(user_id)
                await update.message.reply_text(f"Користувач {user_id} видалений з білого списку")
            except:
                await update.message.reply_text("Використання: /whitelist_remove user_id")

    async def reset_warnings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Скидання попереджень"""
        if update.effective_user.id == self.admin_id:
            try:
                user_id = int(context.args[0])
                self.anti_spam.reset_warnings(user_id)
                await update.message.reply_text(f"Попередження скинуті для користувача {user_id}")
            except:
                await update.message.reply_text("Використання: /reset_warnings user_id")

    def get_handlers(self):
        """Повертає всі обробники антиспаму"""
        return [
            CommandHandler("whitelist_add", self.whitelist_add),
            CommandHandler("whitelist_remove", self.whitelist_remove),
            CommandHandler("reset_warnings", self.reset_warnings)
        ]
