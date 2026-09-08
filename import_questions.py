import sqlite3
from pathlib import Path

from question_parser import parse_questions


# ============================================================
# Y English Exams - Question Importer
# ============================================================
# وظیفه این فایل:
#
# متن خام سؤال‌ها
#       ↓
# Question Parser
#       ↓
# بررسی خطاها
#       ↓
# ذخیره سؤال‌های صحیح در SQLite
#
# Parser مسئول فهمیدن متن است.
# این فایل مسئول ذخیره کردن نتیجه Parser در Database است.
# ============================================================


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "exam.db"


# ============================================================
# Sample Questions
# ============================================================
# این متن فقط برای تست اولیه است.
# بعداً همین متن از طریق Mini App و Paste دریافت خواهد شد.
# ============================================================

QUESTIONS_TEXT = """
[QUESTION]
She _____ to school every day.
[A] go
[B] goes
[C] going
[D] gone
[ANSWER] B

[QUESTION]
I _____ my homework yesterday.
[A] do
[B] does
[C] did
[D] doing
[ANSWER] C

[QUESTION]
They _____ playing football now.
[A] is
[B] are
[C] was
[D] be
[ANSWER] B
"""


def save_questions(questions):
    """
    ذخیره سؤال‌های معتبر در دیتابیس.
    """

    connection = sqlite3.connect(DATABASE_PATH)
    cursor = connection.cursor()

    saved_count = 0

    for question in questions:

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
                question["question_text"],
                question["option_a"],
                question["option_b"],
                question["option_c"],
                question["option_d"],
                question["correct_answer"]
            )
        )

        saved_count += 1

    connection.commit()
    connection.close()

    return saved_count


def import_questions():

    print("=" * 60)
    print("QUESTION IMPORT")
    print("=" * 60)

    # --------------------------------------------------------
    # مرحله ۱: پردازش متن توسط Parser
    # --------------------------------------------------------

    questions, errors = parse_questions(QUESTIONS_TEXT)

    print(f"Questions found : {len(questions)}")
    print(f"Errors found    : {len(errors)}")
    print()

    # --------------------------------------------------------
    # نمایش خطاها
    # --------------------------------------------------------

    if errors:

        print("ERRORS:")

        for error in errors:
            print(
                f"Question {error['question_number']}: "
                f"{error['error']}"
            )

        print()

    # --------------------------------------------------------
    # ذخیره سؤال‌های صحیح
    # --------------------------------------------------------

    if questions:

        saved_count = save_questions(questions)

        print(f"Questions saved : {saved_count}")

    else:

        print("No valid questions to save.")


if __name__ == "__main__":
    import_questions()