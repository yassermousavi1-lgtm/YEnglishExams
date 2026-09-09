import sqlite3
from pathlib import Path


# ============================================================
# DATABASE CONFIGURATION
# ============================================================
#
# All application data is stored in one SQLite database.
#
# The database.py file is responsible only for:
# 1. Creating the database structure.
# 2. Opening database connections.
#
# Business logic such as creating exams, importing questions,
# sending exams, grading students, etc. belongs in other files.
#
# This separation keeps the project easier to understand and
# allows us to expand the application without turning this file
# into a large collection of unrelated logic.
# ============================================================


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "exam.db"


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_connection():
    """
    Create and return a connection to the SQLite database.

    Row factory is enabled so database rows can be accessed
    using column names as well as indexes.

    Foreign key support is explicitly enabled because SQLite
    does not enable it automatically for every connection.
    """

    connection = sqlite3.connect(DATABASE_PATH)

    # Enable foreign key constraints.
    connection.execute("PRAGMA foreign_keys = ON")

    # Allow access like:
    # row["question_text"]
    # instead of:
    # row[1]
    connection.row_factory = sqlite3.Row

    return connection


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

def create_database():
    """
    Create all tables required by the application.

    CREATE TABLE IF NOT EXISTS is intentionally used so that
    running this file again does not delete existing data.

    The current MVP database is intentionally simple.
    Additional fields/tables should only be added when the
    application actually needs them.
    """

    connection = get_connection()
    cursor = connection.cursor()

    # ========================================================
    # GROUPS
    # ========================================================
    #
    # Stores Telegram groups/classes managed by the teacher.
    #
    # telegram_group_id:
    # The real Telegram chat ID of the group.
    #
    # Example:
    # -5496449839
    # ========================================================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            telegram_group_id INTEGER UNIQUE NOT NULL,

            name TEXT NOT NULL,

            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ========================================================
    # STUDENTS
    # ========================================================
    #
    # Each student belongs to exactly ONE group in the current
    # MVP architecture.
    #
    # We deliberately do not create a separate group_members
    # table at this stage because it would add unnecessary
    # complexity.
    # ========================================================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            telegram_user_id INTEGER UNIQUE NOT NULL,

            first_name TEXT,

            last_name TEXT,

            username TEXT,

            group_id INTEGER NOT NULL,

            created_at TEXT DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (group_id)
                REFERENCES groups(id)
                ON DELETE CASCADE
        )
    """)

    # ========================================================
    # QUESTIONS
    # ========================================================
    #
    # The question bank.
    #
    # Every question contains:
    # - Question text
    # - Four options
    # - Correct answer
    #
    # AI-generated questions will eventually be pasted in
    # batches and imported into this table automatically.
    # ========================================================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            question_text TEXT NOT NULL,

            option_a TEXT NOT NULL,

            option_b TEXT NOT NULL,

            option_c TEXT NOT NULL,

            option_d TEXT NOT NULL,

            correct_answer TEXT NOT NULL
                CHECK(correct_answer IN ('A', 'B', 'C', 'D')),

            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ========================================================
    # EXAMS
    # ========================================================
    #
    # Stores the basic definition of an exam.
    #
    # An exam does not directly contain question text.
    # Its questions are connected through exam_questions.
    #
    # This separation allows the same question to be reused
    # in multiple exams.
    # ========================================================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS exams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            title TEXT NOT NULL,

            time_limit INTEGER NOT NULL,
	     category TEXT DEFAULT 'Uncategorized',

            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ========================================================
    # EXAM QUESTIONS
    # ========================================================
    #
    # Connects questions to exams.
    #
    # question_order is important because the teacher needs
    # control over the order in which questions appear.
    #
    # Example:
    #
    # Exam 1
    #   1 -> Question 5
    #   2 -> Question 2
    #   3 -> Question 9
    #
    # The same question can therefore be reused in another
    # exam without duplicating its actual content.
    # ========================================================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS exam_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            exam_id INTEGER NOT NULL,

            question_id INTEGER NOT NULL,

            question_order INTEGER NOT NULL,

            FOREIGN KEY (exam_id)
                REFERENCES exams(id)
                ON DELETE CASCADE,

            FOREIGN KEY (question_id)
                REFERENCES questions(id)
                ON DELETE CASCADE,

            UNIQUE(exam_id, question_id)
        )
    """)

    # ========================================================
    # RESULTS
    # ========================================================
    #
    # Stores the result of a student's attempt at an exam.
    #
    # One row represents one completed exam attempt.
    #
    # More detailed answer-by-answer tracking can be added
    # later if the project requires it.
    # ========================================================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            student_id INTEGER NOT NULL,

            exam_id INTEGER NOT NULL,

            score INTEGER NOT NULL,

            total_questions INTEGER NOT NULL,

            started_at TEXT,

            completed_at TEXT,

            FOREIGN KEY (student_id)
                REFERENCES students(id)
                ON DELETE CASCADE,

            FOREIGN KEY (exam_id)
                REFERENCES exams(id)
                ON DELETE CASCADE
        )
    """)

    # ========================================================
    # EXAM ASSIGNMENTS
    # ========================================================
    #
    # This table connects an exam to a Telegram group.
    #
    # It represents the teacher's decision:
    #
    #     "Send Exam X to Group Y"
    #
    # An exam can therefore be assigned to multiple groups.
    #
    # We intentionally keep this table simple in the MVP.
    # We are NOT adding deadline, status, scheduling, etc.
    # until those features are actually required.
    #
    # UNIQUE(exam_id, group_id) prevents accidentally creating
    # the same assignment twice.
    # ========================================================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS exam_assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            exam_id INTEGER NOT NULL,

            group_id INTEGER NOT NULL,

            assigned_at TEXT DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (exam_id)
                REFERENCES exams(id)
                ON DELETE CASCADE,

            FOREIGN KEY (group_id)
                REFERENCES groups(id)
                ON DELETE CASCADE,

            UNIQUE(exam_id, group_id)
        )
    """)

    # ========================================================
    # SAVE CHANGES
    # ========================================================

    connection.commit()

    connection.close()


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    create_database()

    print("=" * 60)
    print("DATABASE CREATED / VERIFIED SUCCESSFULLY")
    print("=" * 60)
    print(f"Database path: {DATABASE_PATH}")