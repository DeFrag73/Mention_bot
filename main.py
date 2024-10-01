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

# Dictionary to track interacted users per chat
interacted_users_per_chat = {}

# File where the users who interacted will be stored
INTERACTED_USERS_FILE = 'interacted_users_per_chat.json'

# Function to load interacted users from the file on startup
def load_interacted_users():
    global interacted_users_per_chat
    try:
        with open(INTERACTED_USERS_FILE, 'r', encoding='utf-8') as file:
            interacted_users_per_chat = json.load(file)
            logging.info(f"Loaded interacted users per chat: {interacted_users_per_chat}")
    except FileNotFoundError:
        logging.info(f"{INTERACTED_USERS_FILE} not found, starting fresh.")
    except json.JSONDecodeError as e:
        logging.error(f"Error reading {INTERACTED_USERS_FILE}: {e}")

# Function to save interacted users to the file
def save_interacted_users():
    with open(INTERACTED_USERS_FILE, 'w', encoding='utf-8') as file:
        json.dump(interacted_users_per_chat, file, ensure_ascii=False, indent=4)
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
    chat_id = str(query.message.chat.id)  # Ensure chat_id is stored as a string

    # Check if the chat_id exists in the dictionary
    if chat_id not in interacted_users_per_chat:
        interacted_users_per_chat[chat_id] = {}  # Initialize empty dictionary for the chat

    # Add the user to the interacted users list for this specific chat
    if user.id not in interacted_users_per_chat[chat_id]:
        interacted_users_per_chat[chat_id][user.id] = user.first_name  # Store user info for the chat
        save_interacted_users()  # Save the updated list to the file
        # Notify the user of successful interaction
        confirmation_message = await query.message.reply_text(f"Дякую, {user.first_name}! Тепер вас згадуватимуть у цьому чаті.", reply_to_message_id=query.message.message_id)
    else:
        # Inform the user they have already interacted
        confirmation_message = await query.message.reply_text(f"{user.first_name}, ви вже взаємодіяли з ботом у цьому чаті.", reply_to_message_id=query.message.message_id)

    # Delete confirmation message after 10 seconds
    await asyncio.sleep(10)
    await context.bot.delete_message(chat_id=confirmation_message.chat_id, message_id=confirmation_message.message_id)

# Welcome message for new users joining the chat
async def welcome_new_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for user in update.message.new_chat_members:
        # Create the interaction button for the new user
        keyboard = [[InlineKeyboardButton("Натисніть, щоб дозволити згадку", callback_data='interact')]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Send a welcome message with the button
        await update.message.reply_text(f"Ласкаво просимо, {user.first_name}! Натисніть кнопку нижче, щоб взаємодіяти з ботом.", reply_markup=reply_markup)

# Command function to mention all users who interacted with the bot and are in the current chat
async def mention_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)  # Convert chat_id to string

    # Check if the bot has any interacted users stored for this chat
    if chat_id not in interacted_users_per_chat or not interacted_users_per_chat[chat_id]:
        await update.message.reply_text("Немає користувачів, які взаємодіяли з ботом у цьому чаті.")
        return

    interacted_users = interacted_users_per_chat[chat_id]
    current_chat_members = []

    # Fetch all current chat members and store their IDs
    try:
        members_count = await context.bot.get_chat_member_count(chat_id)

        # Get all chat members info
        for user_id in range(1, members_count + 1):
            try:
                member = await context.bot.get_chat_member(chat_id, user_id)
                current_chat_members.append(member.user.id)  # Add user ID to current chat members list
            except TelegramError:
                continue  # Ignore if user info couldn't be fetched

    except TelegramError as e:
        logging.error(f"Error fetching chat members: {e}")
        await update.message.reply_text("Не вдалося отримати список учасників чату.")
        return

    # Find users who have interacted and are still in the chat
    users_to_mention = [
        f'[{name}](tg://user?id={user_id})'
        for user_id, name in interacted_users.items()
        #if int(user_id) in current_chat_members  # Make sure the user is still in the chat
    ]

    if not users_to_mention:
        await update.message.reply_text(
            "Немає користувачів для згадки, які взаємодіяли з ботом і перебувають у цьому чаті.")
        return

    # Batch mentions and avoid hitting Telegram's flood control limits
    for i in range(0, len(users_to_mention), 5):
        mention_text = "Увага: " + ", ".join(users_to_mention[i:i + 5])
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
    app.add_handler(CommandHandler('mention_all_password', mention_all))
    app.add_handler(CommandHandler('start', request_interaction))  # Request users to interact with the bot
    app.add_handler(CallbackQueryHandler(button_click))  # Handle button clicks
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_user))  # Handle new chat members

    # Run the bot
    app.run_polling()

if __name__ == '__main__':
    main()
