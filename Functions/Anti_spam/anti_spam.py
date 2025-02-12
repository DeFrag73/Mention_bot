from collections import defaultdict
from time import time
from pymongo import MongoClient
from typing import Tuple
import os
from dotenv import load_dotenv

load_dotenv()

DB_NAME = os.getenv('MONGO_DATABASE')

class AntiSpam:
    def __init__(self, mongodb_uri: str, messages_limit=5, time_window=5, ban_time=30):
        # Підключення до MongoDB
        self.client = MongoClient(mongodb_uri)
        self.db = self.client[DB_NAME]
        self.spam_collection = self.db['spam_data']
        self.whitelist_collection = self.db['whitelist']

        # Налаштування антиспаму
        self.users_messages = defaultdict(list)
        self.messages_limit = messages_limit
        self.time_window = time_window
        self.ban_time = ban_time
        self.max_warnings = 3

        # Завантаження даних з бази
        self.load_data()

    def load_data(self) -> None:
        """Завантаження даних з MongoDB"""
        try:
            # Завантаження банів та попереджень
            spam_data = self.spam_collection.find_one({'_id': 'spam_data'}) or {}
            self.banned_users = {int(k): v for k, v in spam_data.get('banned_users', {}).items()}
            self.warning_counts = defaultdict(int, {
                int(k): v for k, v in spam_data.get('warning_counts', {}).items()
            })
        except Exception as e:
            print(f"Помилка завантаження даних з MongoDB: {e}")
            self.banned_users = {}
            self.warning_counts = defaultdict(int)

    def save_data(self) -> None:
        """Збереження даних в MongoDB"""
        try:
            spam_data = {
                '_id': 'spam_data',
                'banned_users': {str(k): v for k, v in self.banned_users.items()},
                'warning_counts': {str(k): v for k, v in self.warning_counts.items()}
            }
            self.spam_collection.replace_one(
                {'_id': 'spam_data'},
                spam_data,
                upsert=True
            )
        except Exception as e:
            print(f"Помилка збереження даних в MongoDB: {e}")

    def add_to_whitelist(self, user_id: int) -> None:
        """Додавання користувача до білого списку"""
        try:
            self.whitelist_collection.update_one(
                {'_id': 'whitelist'},
                {'$addToSet': {'users': user_id}},
                upsert=True
            )
        except Exception as e:
            print(f"Помилка додавання до білого списку: {e}")

    def remove_from_whitelist(self, user_id: int) -> None:
        """Видалення користувача з білого списку"""
        try:
            self.whitelist_collection.update_one(
                {'_id': 'whitelist'},
                {'$pull': {'users': user_id}}
            )
        except Exception as e:
            print(f"Помилка видалення з білого списку: {e}")

    def is_whitelisted(self, user_id: int) -> bool:
        """Перевірка чи користувач в білому списку"""
        try:
            whitelist = self.whitelist_collection.find_one({'_id': 'whitelist'})
            return whitelist and user_id in whitelist.get('users', [])
        except Exception as e:
            print(f"Помилка перевірки білого списку: {e}")
            return False

    def is_spam(self, user_id: int) -> Tuple[bool, str]:
        """Перевірка на спам та повернення статусу з повідомленням"""
        if self.is_whitelisted(user_id):
            return False, ""

        current_time = time()

        # Перевірка що бан існує
        if user_id in self.banned_users:
            remaining_ban_time = self.ban_time - (current_time - self.banned_users[user_id])
            if remaining_ban_time > 0:
                return True, f"Ви заблоковані ще на {int(remaining_ban_time)} секунд."
            else:
                del self.banned_users[user_id]
                self.users_messages[user_id].clear()
                self.save_data()

        # Оновлення історії повідомлень
        self.users_messages[user_id].append(current_time)
        self.users_messages[user_id] = [
            msg_time for msg_time in self.users_messages[user_id]
            if current_time - msg_time <= self.time_window
        ]

        # Перевірка кількості повідомлень
        if len(self.users_messages[user_id]) > self.messages_limit:
            self.warning_counts[user_id] += 1

            if self.warning_counts[user_id] >= self.max_warnings:
                self.banned_users[user_id] = current_time
                self.save_data()
                return True, f"Ви заблоковані на {self.ban_time} секунд через надмірний спам."

            return True, (f"Попередження {self.warning_counts[user_id]}/{self.max_warnings}: "
                          f"Сповільніть відправку повідомлень!")

        return False, ""

    def reset_warnings(self, user_id: int) -> None:
        """Скидання попереджень для користувача"""
        if user_id in self.warning_counts:
            del self.warning_counts[user_id]
            self.save_data()

    def __del__(self):
        """Закриття з'єднання з MongoDB при видаленні об'єкта"""
        self.client.close()
