import sqlite3
from pathlib import Path


# مسیر دیتابیس پروژه
BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "exam.db"


# اطلاعات گروهی که می‌خواهیم ثبت کنیم
GROUP_NAME = "Test's English class"
TELEGRAM_GROUP_ID = -5496449839


def add_group():
    connection = sqlite3.connect(DATABASE_PATH)
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            INSERT INTO groups (telegram_group_id, name)
            VALUES (?, ?)
            """,
            (TELEGRAM_GROUP_ID, GROUP_NAME)
        )

        connection.commit()

        print("Group added successfully.")
        print(f"Group Name: {GROUP_NAME}")
        print(f"Group ID  : {TELEGRAM_GROUP_ID}")

    except sqlite3.IntegrityError:
        print("This group is already registered in the database.")

    finally:
        connection.close()


if __name__ == "__main__":
    add_group()