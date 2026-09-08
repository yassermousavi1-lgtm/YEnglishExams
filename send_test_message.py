from telegram import Bot
import asyncio


# ============================================================
# TELEGRAM TEST MESSAGE
# ============================================================
#
# This is only a connectivity test.
#
# It checks whether our Bot can send a message to the
# registered English class group.
#
# No exam data is involved yet.
# ============================================================


BOT_TOKEN = "8909221623:AAE0Y0Joy7w2luQAUncMn6-0Sk9lL4AfVY0"

TELEGRAM_GROUP_ID = -5496449839


async def send_test_message():

    bot = Bot(token=BOT_TOKEN)

    await bot.send_message(
        chat_id=TELEGRAM_GROUP_ID,
        text="🧪 Test message from YEnglish Exams Bot."
    )

    print("=" * 60)
    print("TEST MESSAGE SENT SUCCESSFULLY")
    print("=" * 60)
    print(f"Telegram Group ID: {TELEGRAM_GROUP_ID}")


if __name__ == "__main__":
    asyncio.run(send_test_message())