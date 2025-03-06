from telethon.sync import TelegramClient
from telethon.errors import SessionPasswordNeededError
import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
API_ID = os.getenv('TELEGRAM_API_ID')
API_HASH = os.getenv('TELEGRAM_API_HASH')
PHONE_NUMBER = os.getenv('TELEGRAM_PHONE_NUMBER')


api_id = API_ID  # Твій API ID
api_hash = API_HASH  # Твій API Hash
phone_number = PHONE_NUMBER  # Твій номер телефону

client = TelegramClient('session_name', api_id, api_hash)


async def main():
    await client.connect()
    if not await client.is_user_authorized():
        await client.send_code_request(phone_number)
        try:
            code = input('Enter the code: ')
            await client.sign_in(phone_number, code)
        except SessionPasswordNeededError:
            password = input('Enter your password: ')  # Тут вводиться пароль
            await client.sign_in(password=password)

    print("Successfully logged in!")

with client:
    client.loop.run_until_complete(main())
