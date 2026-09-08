from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes


BOT_TOKEN = "8909221623:AAE0Y0Joy7w2luQAUncMn6-0Sk9lL4AfVY0"


async def me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش Telegram User ID کاربر."""

    user = update.effective_user

    print("=" * 50)
    print("USER INFORMATION")
    print(f"User ID   : {user.id}")
    print(f"First Name: {user.first_name}")
    print(f"Username  : @{user.username}")
    print("=" * 50)

    await update.message.reply_text(
        f"Your Telegram User ID is:\n{user.id}"
    )


def main():

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(
        CommandHandler("me", me)
    )

    print("Bot is running...")
    print("Send /me to the bot.")

    application.run_polling()


if __name__ == "__main__":
    main()