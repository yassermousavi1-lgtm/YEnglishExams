from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ContextTypes,
)


# ============================================================
# BUTTON TEST BOT
# ============================================================
#
# This is a temporary test for the Start Exam button.
#
# Current flow:
#
#     Student
#        ↓
#     [ Start Exam ]
#        ↓
#     Telegram Callback
#        ↓
#     Bot
#        ↓
#     Read Exam ID
#
# We are NOT opening the Mini App yet.
# The purpose of this file is only to verify that the Bot can
# receive the button click and correctly identify the exam.
# ============================================================


BOT_TOKEN = "8909221623:AAE0Y0Joy7w2luQAUncMn6-0Sk9lL4AfVY0"


# ============================================================
# START EXAM BUTTON HANDLER
# ============================================================

async def start_exam_button(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    # --------------------------------------------------------
    # Tell Telegram that the button click was received.
    #
    # Without this, Telegram may keep showing a loading
    # indicator on the clicked button.
    # --------------------------------------------------------

    await query.answer()

    # --------------------------------------------------------
    # The callback data was created like this:
    #
    #     start_exam:2
    #
    # Therefore we split it and extract the Exam ID.
    # --------------------------------------------------------

    data = query.data

    if not data.startswith("start_exam:"):

        await query.answer(
            "Unknown button.",
            show_alert=True
        )

        return

    exam_id = data.split(":", 1)[1]

    # --------------------------------------------------------
    # Display the detected Exam ID.
    #
    # This is only a test.
    # Later this section will launch the Mini App.
    # --------------------------------------------------------

    print("=" * 60)
    print("START EXAM BUTTON CLICKED")
    print("=" * 60)
    print(f"Telegram User ID : {query.from_user.id}")
    print(f"First Name       : {query.from_user.first_name}")
    print(f"Exam ID          : {exam_id}")

    # --------------------------------------------------------
    # Temporary response to the student.
    # --------------------------------------------------------

    await query.answer(
        f"Exam {exam_id} detected successfully.",
        show_alert=True
    )


# ============================================================
# MAIN
# ============================================================

def main():

    application = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    # --------------------------------------------------------
    # Listen for all inline button clicks.
    # --------------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(start_exam_button)
    )

    print("=" * 60)
    print("BUTTON TEST BOT IS RUNNING")
    print("=" * 60)
    print("Click the Start Exam button in Telegram.")

    application.run_polling()


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()