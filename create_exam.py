import sqlite3
from pathlib import Path


# ============================================================
# Y English Exams - Create Exam
# ============================================================
# این فایل برای تست اولیه ساخت آزمون است.
#
# ساختار:
#
# Exam
#   ↓
# Exam Questions
#   ↓
# Questions
#
# در نسخه نهایی، معلم این کار را از داخل Mini App انجام می‌دهد.
# ============================================================


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "exam.db"


EXAM_TITLE = "Present Simple Test"
TIME_LIMIT = 15


# سؤال‌هایی که می‌خواهیم داخل آزمون قرار دهیم
QUESTION_IDS = [1, 3, 4]


def create_exam():

    connection = sqlite3.connect(DATABASE_PATH)
    cursor = connection.cursor()

    try:

        # ----------------------------------------------------
        # 1. ساخت آزمون
        # ----------------------------------------------------

        cursor.execute(
            """
            INSERT INTO exams (
                title,
                time_limit
            )
            VALUES (?, ?)
            """,
            (
                EXAM_TITLE,
                TIME_LIMIT
            )
        )

        exam_id = cursor.lastrowid

        # ----------------------------------------------------
        # 2. اضافه کردن سؤال‌ها به آزمون
        # ----------------------------------------------------

        for order, question_id in enumerate(QUESTION_IDS, start=1):

            # بررسی وجود سؤال
            cursor.execute(
                """
                SELECT id
                FROM questions
                WHERE id = ?
                """,
                (question_id,)
            )

            question = cursor.fetchone()

            if question is None:
                raise ValueError(
                    f"Question ID {question_id} was not found."
                )

            cursor.execute(
                """
                INSERT INTO exam_questions (
                    exam_id,
                    question_id,
                    question_order
                )
                VALUES (?, ?, ?)
                """,
                (
                    exam_id,
                    question_id,
                    order
                )
            )

        connection.commit()

        print("=" * 60)
        print("EXAM CREATED SUCCESSFULLY")
        print("=" * 60)

        print(f"Exam ID       : {exam_id}")
        print(f"Exam Title    : {EXAM_TITLE}")
        print(f"Questions     : {len(QUESTION_IDS)}")
        print(f"Time Limit    : {TIME_LIMIT} minutes")

    except Exception as error:

        connection.rollback()

        print("ERROR:")
        print(error)

    finally:

        connection.close()


if __name__ == "__main__":
    create_exam()