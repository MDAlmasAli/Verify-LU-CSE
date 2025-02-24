import logging
import time
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update, error  # Import the error module
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
import asyncio

# Google Sheets Setup
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name('Register_student.json', scope)
client = gspread.authorize(creds)
sheet = client.open("Register Student").sheet1  # Replace with your Google Sheet name

# Telegram Bot Token
TOKEN = '7727326947:AAHo94hMyPVvnD2rRnSu7wtpnJE9supZits'

# Channel Info
CHANNEL_USERNAME = '@ResourcesForCseStudent'
ADMIN_IDS = ['7064750926', '1858522053', '1676112331']  # Admin Telegram IDs

# Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Dictionary to track active invite links
active_invite_links = {}

# Function to load valid student IDs from a file
def load_valid_ids():
    with open('E:/RegisterStudentBOT/valid_ids.txt', 'r') as file:  # Full path added
        return [line.strip() for line in file]

# Function to check if the student ID is valid
def is_valid_student_id(student_id):
    valid_ids = load_valid_ids()  # Load valid IDs from the file
    return student_id in valid_ids

# Function to generate a unique identifier (simulated IMEI)
def generate_unique_id(user_id):
    # Simulate an IMEI-like number using the user's Telegram ID
    return f"IMEI_{user_id}"

# Command to start the bot
async def start(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text("Welcome! Please provide your details in the following format:\n\n"
                                    "Name, Batch, Section, Student ID, Mobile Number\n\n"
                                    "Example: MD Almas Ali, 62, B, 0182320012101068, 123456789")

# Function to handle user input
async def handle_message(update: Update, context: CallbackContext) -> None:
    # Check if the update contains a message with text
    if not update.message or not update.message.text:
        return  # Skip processing if no text message is present

    user_input = update.message.text
    user_id = update.message.from_user.id

    try:
        # Parse user input
        name, batch, section, student_id, mobile_number = map(str.strip, user_input.split(','))

        # Check if the student ID is valid
        if not is_valid_student_id(student_id):
            await update.message.reply_text("Student ID is not in the list. Please provide a valid Student ID. If you think your student ID is valid, contact your CR to add your section to the database. Thank you.")
            return

        # Generate a unique identifier (simulated IMEI)
        imei_number = generate_unique_id(user_id)

        # Check for uniqueness before storing in the sheet
        existing_data = sheet.get_all_records()
        for row in existing_data:
            # Check for duplicate Telegram ID, Student ID, and Mobile Number
            if ((str(user_id) == str(row.get('Telegram ID', '')).strip())) or \
               ((student_id == str(row.get('Student ID', '')).strip())) or \
               ((mobile_number == str(row.get('Mobile Number', '')).strip())):
                # Log the duplicate case for debugging purposes
                logger.warning(f"Duplicate detected: Telegram ID={user_id}, Student ID={student_id}, Mobile Number={mobile_number}")
                await update.message.reply_text("Duplicate entry detected. Please ensure all details are unique.")
                return

        # Check if batch is 64
        if batch == '64':
            await update.message.reply_text("You are restricted from using this channel.")
            return

        # Store data in Google Sheet
        sheet.append_row([name, user_id, imei_number, batch, section, student_id, mobile_number])

        # Generate invite link
        expire_date = int(time.time()) + 10  # Link expires in 10 seconds
        invite_link = await context.bot.create_chat_invite_link(
            CHANNEL_USERNAME,
            member_limit=1,
            expire_date=expire_date
        )
        await update.message.reply_text(f"Registration complete! Please join the channel within 5 seconds using this link: {invite_link.invite_link}")

        # Track the invite link
        active_invite_links[invite_link.invite_link] = {
            'user_id': user_id,
            'expire_date': expire_date
        }

        # Schedule the link to be revoked after 10 seconds
        context.job_queue.run_once(revoke_link, 10, data=invite_link.invite_link)

    except ValueError:
        await update.message.reply_text("Invalid format. Please provide your details in the following format:\n\n"
                                        "Name, Batch, Section, Student ID, Mobile Number\n\n"
                                        "Example: MD Almas Ali, 62, B, 0182320012101068, 1234567890")

# Retry logic to revoke invite link after multiple attempts if there's a timeout
async def revoke_link(context: CallbackContext) -> None:
    invite_link = context.job.data
    retries = 3
    while retries > 0:
        try:
            if invite_link in active_invite_links:
                await context.bot.revoke_chat_invite_link(CHANNEL_USERNAME, invite_link)
                del active_invite_links[invite_link]
            break
        except error.TimedOut:  # Use error.TimedOut instead of telegram.error.TimedOut
            retries -= 1
            if retries > 0:
                logger.warning(f"Timed out while trying to revoke the invite link. Retrying... {retries} attempts left.")
                await asyncio.sleep(5)  # Wait before retrying
            else:
                logger.error(f"Failed to revoke the invite link after multiple attempts: {invite_link}")

# Function to handle new members joining the channel
async def handle_new_member(update: Update, context: CallbackContext) -> None:
    for member in update.message.new_chat_members:
        # Check if the member is an admin or was added by an admin
        if str(member.id) in ADMIN_IDS or str(update.message.from_user.id) in ADMIN_IDS:
            await update.message.reply_text(f"{member.first_name} was added by an admin. Welcome!")
        else:
            # Check if the member used a valid invite link
            if not any(member.id == active_invite_links[link]['user_id'] for link in active_invite_links):
                await context.bot.ban_chat_member(CHANNEL_USERNAME, member.id)
                await context.bot.unban_chat_member(CHANNEL_USERNAME, member.id)
                await update.message.reply_text(f"{member.first_name} was kicked for joining without a valid invite link.")
            else:
                # Revoke the invite link after the member joins
                for link in active_invite_links:
                    if active_invite_links[link]['user_id'] == member.id:
                        await context.bot.revoke_chat_invite_link(CHANNEL_USERNAME, link)
                        del active_invite_links[link]
                        break

# Function to clean up expired invite links
async def cleanup_expired_links(context: CallbackContext) -> None:
    current_time = int(time.time())
    expired_links = [link for link in active_invite_links if active_invite_links[link]['expire_date'] < current_time]
    for link in expired_links:
        await context.bot.revoke_chat_invite_link(CHANNEL_USERNAME, link)
        del active_invite_links[link]

# Main function
def main() -> None:
    # Build the application
    application = Application.builder().token(TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.ChatType.GROUPS | filters.ChatType.SUPERGROUP, handle_new_member))

    # Schedule cleanup of expired links every minute
    application.job_queue.run_repeating(cleanup_expired_links, interval=60, first=0)

    # Start the bot
    application.run_polling()

if __name__ == '__main__':
    main()
