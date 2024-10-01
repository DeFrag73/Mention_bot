import logging
import asyncio
import json
import os
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode
from telegram.error import TelegramError, RetryAfter

# Logging setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# A dictionary to keep track of users who have interacted with the bot
interacted_users = {}

# File where the users who interacted will be stored
INTERACTED_USERS_FILE = 'interacted_users.json'

# Function to load interacted users from the file on startup
def load_interacted_users():
    global interacted_users
    try:
        with open(INTERACTED_USERS_FILE, 'r', encoding='utf-8') as file:
            interacted_users = json.load(file)
            logging.info(f"Loaded interacted users: {interacted_users}")
    except FileNotFoundError:
        logging.info(f"{INTERACTED_USERS_FILE} not found, starting fresh.")
    except json.JSONDecodeError as e:
        logging.error(f"Error reading {INTERACTED_USERS_FILE}: {e}")

# Function to save interacted users to the file
def save_interacted_users():
    with open(INTERACTED_USERS_FILE, 'w', encoding='utf-8') as file:
        json.dump(interacted_users, file, ensure_ascii=False, indent=4)
        logging.info("Interacted users saved to file.")

# Function to request users to interact with the bot
async def request_interaction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Create a button for users to click
    keyboard = [[InlineKeyboardButton("Натисніть, щоб взаємодіяти", callback_data='interact')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Send a message with the interaction request and keep it editable for all users
    await update.message.reply_text("Щоб вас згадали, натисніть кнопку нижче:", reply_markup=reply_markup)

# Callback function for the interaction button
async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()  # Acknowledge the callback

    user = query.from_user
    if user.id not in interacted_users:
        interacted_users[user.id] = user.first_name  # Store user info
        save_interacted_users()  # Save the updated list to the file

        # Send confirmation and delete after 10 seconds
        confirmation_message = await query.message.reply_text(f"Дякую, {user.first_name}! Тепер вас згадуватимуть у наступних згадках.", reply_to_message_id=query.message.message_id)
        await asyncio.sleep(10)  # Wait 10 seconds
        await context.bot.delete_message(chat_id=confirmation_message.chat_id, message_id=confirmation_message.message_id)
    else:
        # Inform the user they have already interacted and delete message after 10 seconds
        already_interacted_message = await query.message.reply_text(f"{user.first_name}, ви вже взаємодіяли з ботом.", reply_to_message_id=query.message.message_id)
        await asyncio.sleep(10)  # Wait 10 seconds
        await context.bot.delete_message(chat_id=already_interacted_message.chat_id, message_id=already_interacted_message.message_id)


# Welcome message for new users joining the chat
async def welcome_new_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for user in update.message.new_chat_members:
        # Create the interaction button for the new user
        keyboard = [[InlineKeyboardButton("Натисніть, щоб дозволити згадку", callback_data='interact')]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Send a welcome message with the button and keep the button intact
        await update.message.reply_text(f"Ласкаво просимо, {user.first_name}! Натисніть кнопку нижче, щоб взаємодіяти з ботом.", reply_markup=reply_markup)

# Command function to mention all users who interacted with the bot
async def mention_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == 'private':
        await update.message.reply_text("Ця команда працює лише в групах.")
        return

    if interacted_users:
        user_list = [f'[{name}](tg://user?id={user_id})' for user_id, name in interacted_users.items()]
    else:
        await update.message.reply_text("Жоден користувач ще не взаємодіяв із ботом.")
        return

    # Batch mentions and avoid hitting Telegram's flood control limits
    for i in range(0, len(user_list), 5):
        mention_text = "Запрошую всіх до чату: " + ", ".join(user_list[i:i + 5])
        try:
            await update.message.reply_text(mention_text, parse_mode=ParseMode.MARKDOWN)
            await asyncio.sleep(1)  # Pause to avoid flood control
        except RetryAfter as e:
            logging.warning(f"Flood control: retrying after {e.retry_after} seconds.")
            await asyncio.sleep(e.retry_after)
            await update.message.reply_text(mention_text, parse_mode=ParseMode.MARKDOWN)

# Main function to run the bot
def main():
    # Load previously interacted users from the file
    load_interacted_users()

    load_dotenv()

    TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

    app = ApplicationBuilder().token(TOKEN).build()

    # Handlers for different commands and button clicks
    app.add_handler(CommandHandler('mention_all', mention_all))
    app.add_handler(CommandHandler('start', request_interaction))  # Request users to interact with the bot
    app.add_handler(CallbackQueryHandler(button_click))  # Handle button clicks
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_user))  # Handle new chat members

    # Run the bot
    app.run_polling()

if __name__ == '__main__':
    main()
