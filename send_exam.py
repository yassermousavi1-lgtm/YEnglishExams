import asyncio
import os

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from database import get_connection


# ============================================================
# SEND EXAM TO TELEGRAM GROUP
# ============================================================
#
# Uses Deep Link to open Mini App with exam_id:
#
#     https://t.me/YEnglsihExamsbot?startapp=exam_2
# ============================================================


# ============================================================
# READ BOT TOKEN FROM ENVIRONMENT
# ============================================================

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

if not BOT_TOKEN:
    print("=" * 60)
    print("ERROR: TELEGRAM_BOT_TOKEN is not set.")
    print("=" * 60)
    print()
    print("Please set the environment variable:")
    print()
    print("  PowerShell:")
    print("  $env:TELEGRAM_BOT_TOKEN = 'YOUR_BOT_TOKEN'")
    print()
    print("=" * 60)
    exit(1)


ASSIGNMENT_ID = 1


# ============================================================
# LOAD ASSIGNMENT
# ============================================================

def get_assignment(assignment_id):

    connection = get_connection()

    try:

        row = connection.execute(
            """
            SELECT
                ea.id AS assignment_id,

                e.id AS exam_id,
                e.title AS exam_title,
                e.time_limit AS time_limit,

                g.id AS group_id,
                g.name AS group_name,
                g.telegram_group_id AS telegram_group_id

            FROM exam_assignments ea

            JOIN exams e
                ON e.id = ea.exam_id

            JOIN groups g
                ON g.id = ea.group_id

            WHERE ea.id = ?
            """,
            (assignment_id,)
        ).fetchone()

        return row

    finally:

        connection.close()


# ============================================================
# COUNT QUESTIONS
# ============================================================

def get_question_count(exam_id):

    connection = get_connection()

    try:

        row = connection.execute(
            """
            SELECT COUNT(*) AS total_questions

            FROM exam_questions

            WHERE exam_id = ?
            """,
            (exam_id,)
        ).fetchone()

        return row["total_questions"]

    finally:

        connection.close()


# ============================================================
# SEND EXAM
# ============================================================

async def send_exam():

    # --------------------------------------------------------
    # Load assignment from database
    # --------------------------------------------------------

    assignment = get_assignment(ASSIGNMENT_ID)

    if assignment is None:

        print("=" * 60)
        print("ERROR")
        print("=" * 60)
        print(f"Assignment not found: {ASSIGNMENT_ID}")

        return

    # --------------------------------------------------------
    # Get number of questions
    # --------------------------------------------------------

    question_count = get_question_count(
        assignment["exam_id"]
    )

    # --------------------------------------------------------
    # Create Start Exam button with Deep Link
    #
    # Deep Link format:
    # https://t.me/BOT_USERNAME?startapp=exam_EXAM_ID
    #
    # This opens the Mini App and passes exam_id to it.
    # --------------------------------------------------------

    bot_username = "YEnglsihExamsbot"
    deep_link = f"https://t.me/{bot_username}?startapp=exam_{assignment['exam_id']}"

    keyboard = [
        [
            InlineKeyboardButton(
                text="📝 Start Exam",
                url=deep_link
            )
        ]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    # --------------------------------------------------------
    # Build announcement
    # --------------------------------------------------------

    message = (
        "📝 EXAM\n\n"
        f"Title: {assignment['exam_title']}\n"
        f"Questions: {question_count}\n"
        f"Time Limit: {assignment['time_limit']} minutes\n\n"
        "When you are ready, press the button below "
        "to start the exam."
    )

    # --------------------------------------------------------
    # Send to Telegram
    # --------------------------------------------------------

    bot = Bot(token=BOT_TOKEN)

    await bot.send_message(
        chat_id=assignment["telegram_group_id"],
        text=message,
        reply_markup=reply_markup
    )

    # --------------------------------------------------------
    # Console confirmation
    # --------------------------------------------------------

    print("=" * 60)
    print("EXAM SENT SUCCESSFULLY")
    print("=" * 60)

    print(f"Assignment ID : {assignment['assignment_id']}")
    print(f"Exam ID       : {assignment['exam_id']}")
    print(f"Exam Title    : {assignment['exam_title']}")
    print(f"Questions     : {question_count}")
    print(f"Time Limit    : {assignment['time_limit']} minutes")
    print(f"Group         : {assignment['group_name']}")
    print(f"Telegram ID   : {assignment['telegram_group_id']}")
    print(f"Deep Link     : {deep_link}")
    print("Start button  : Created with URL")


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    asyncio.run(send_exam())