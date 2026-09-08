import sqlite3
from pathlib import Path


# ============================================================
# Add Student
# ============================================================
# این فایل فقط برای ثبت زبان‌آموز آزمایشی در دیتابیس است.
# بعداً این کار به صورت خودکار توسط Telegram انجام خواهد شد.
# ============================================================


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "exam.db"


# اطلاعات زبان‌آموز
TELEGRAM_USER_ID = 231716006
FIRST_NAME = "Yasser"
LAST_NAME = ""
USERNAME = ""

# گروهی که زبان‌آموز عضو آن است
GROUP_TELEGRAM_ID = -5496449839


def add_student():

    connection = sqlite3.connect(DATABASE_PATH)
    cursor = connection.cursor()

    try:
        # پیدا کردن گروه
        cursor.execute(
            """
            SELECT id, name
            FROM groups
            WHERE telegram_group_id = ?
            """,
            (GROUP_TELEGRAM_ID,)
        )

        group = cursor.fetchone()

        if group is None:
            print("Error: Group was not found in the database.")
            return

        group_id = group[0]
        group_name = group[1]

        # ثبت زبان‌آموز
        cursor.execute(
            """
            INSERT INTO students (
                telegram_user_id,
                first_name,
                last_name,
                username,
                group_id
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                TELEGRAM_USER_ID,
                FIRST_NAME,
                LAST_NAME,
                USERNAME,
                group_id
            )
        )

        connection.commit()

        print("Student added successfully.")
        print(f"Name     : {FIRST_NAME}")
        print(f"Telegram : {TELEGRAM_USER_ID}")
        print(f"Group    : {group_name}")

    except sqlite3.IntegrityError:
        print("This student is already registered in the database.")

    finally:
        connection.close()


if __name__ == "__main__":
    add_student()