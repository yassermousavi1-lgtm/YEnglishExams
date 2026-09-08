import sqlite3
from pathlib import Path


# ============================================================
# Add Test Question
# ============================================================
# این فایل فقط برای تست اولیه بانک سؤال است.
# در مراحل بعد، سؤال‌ها را به صورت گروهی از متن AI
# وارد سیستم خواهیم کرد.
# ============================================================


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "exam.db"


QUESTION_TEXT = "She _____ to school every day."

OPTION_A = "go"
OPTION_B = "goes"
OPTION_C = "going"
OPTION_D = "gone"

CORRECT_ANSWER = "B"


def add_question():

    connection = sqlite3.connect(DATABASE_PATH)
    cursor = connection.cursor()

    cursor.execute(
        """
        INSERT INTO questions (
            question_text,
            option_a,
            option_b,
            option_c,
            option_d,
            correct_answer
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            QUESTION_TEXT,
            OPTION_A,
            OPTION_B,
            OPTION_C,
            OPTION_D,
            CORRECT_ANSWER
        )
    )

    connection.commit()

    question_id = cursor.lastrowid

    connection.close()

    print("Question added successfully.")
    print(f"Question ID: {question_id}")
    print(f"Question   : {QUESTION_TEXT}")
    print(f"A          : {OPTION_A}")
    print(f"B          : {OPTION_B}")
    print(f"C          : {OPTION_C}")
    print(f"D          : {OPTION_D}")
    print(f"Answer     : {CORRECT_ANSWER}")


if __name__ == "__main__":
    add_question()