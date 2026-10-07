import sqlite3
from pathlib import Path


# ============================================================
# DATABASE CONFIGURATION
# ============================================================
#
# All application data is stored in one SQLite database.
#
# This file is responsible only for:
# 1. Creating the database structure.
# 2. Opening database connections.
# 3. Running automatic migrations when structure changes.
#
# Business logic (creating exams, importing questions, grading,
# sending exams, etc.) lives in other files.
#
# ARCHITECTURE NOTE:
#   The database supports TWO independent question types:
#     1. MCQ            -> questions, exam_questions
#     2. Word Bank      -> word_bank_questions
#
#   Each exam declares its type via exams.exam_type
#   ('mcq' or 'word_bank'). The two types never share rows.
#   Existing MCQ data is fully preserved.
# ============================================================


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "exam.db"


# ============================================================
# COLOR PALETTE FOR STUDENTS
# ============================================================
#
# Each student gets an automatic color from this cycle.
# Used to visually distinguish students in the weekly schedule.
# ============================================================

STUDENT_COLOR_PALETTE = [
    "#2563eb",  # Blue
    "#10b981",  # Green
    "#f59e0b",  # Amber
    "#ef4444",  # Red
    "#8b5cf6",  # Purple
    "#ec4899",  # Pink
    "#06b6d4",  # Cyan
    "#f97316",  # Orange
]


def pick_color_for_index(index):
    """Return a color from the palette based on the given index."""
    return STUDENT_COLOR_PALETTE[index % len(STUDENT_COLOR_PALETTE)]


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
    connection.execute("PRAGMA foreign_keys = ON")
    connection.row_factory = sqlite3.Row
    return connection


# ============================================================
# DATABASE MIGRATIONS
# ============================================================
#
# This function handles schema upgrades for existing databases.
# Each migration is wrapped in try/except so:
# - If the column/table already exists, the error is ignored.
# - New installations skip migrations that are not needed.
#
# IMPORTANT: Never drop user data as part of a migration.
# ============================================================

def run_migrations(connection):
    """
    Apply incremental schema changes to an existing database.
    All changes are ADDITIVE — no existing data is modified.
    """

    cursor = connection.cursor()

    # --------------------------------------------------------
    # Migration 1: add category column to exams
    # --------------------------------------------------------
    try:
        cursor.execute("ALTER TABLE exams ADD COLUMN category TEXT DEFAULT 'Uncategorized'")
        connection.commit()
    except sqlite3.OperationalError:
        pass

    # --------------------------------------------------------
    # Migration 2: add is_archived to results
    # --------------------------------------------------------
    try:
        cursor.execute("ALTER TABLE results ADD COLUMN is_archived BOOLEAN DEFAULT 0")
        connection.commit()
    except sqlite3.OperationalError:
        pass

    # --------------------------------------------------------
    # Migration 3: add exam_title_snapshot to results
    # --------------------------------------------------------
    try:
        cursor.execute("ALTER TABLE results ADD COLUMN exam_title_snapshot TEXT")
        connection.commit()
    except sqlite3.OperationalError:
        pass

    # --------------------------------------------------------
    # Migration 4: add color to students (schedule visual)
    # --------------------------------------------------------
    try:
        cursor.execute("ALTER TABLE students ADD COLUMN color TEXT")
        connection.commit()
        # Assign palette colors to any student missing a color
        _assign_missing_colors(cursor)
        connection.commit()
    except sqlite3.OperationalError:
        pass

    # --------------------------------------------------------
    # Migration 5: create attendance table (if missing)
    # --------------------------------------------------------
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                session_number INTEGER NOT NULL,
                extra_minutes INTEGER DEFAULT 0,
                is_makeup BOOLEAN DEFAULT 0,
                created_at TEXT,
                FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
            )
        """)
        connection.commit()
    except sqlite3.OperationalError:
        pass

    # --------------------------------------------------------
    # Migration 6: rebuild class_schedule with student_id
    # --------------------------------------------------------
    _migrate_schedule_table(cursor)
    connection.commit()

    # --------------------------------------------------------
    # Migration 7: drop legacy class_groups table
    # --------------------------------------------------------
    try:
        cursor.execute("DROP TABLE IF EXISTS class_groups")
        connection.commit()
    except sqlite3.OperationalError:
        pass

    # --------------------------------------------------------
    # Migration 8: add exam_type to exams
    #
    # Values: 'mcq' (default, for all existing exams)
    #         'word_bank' (new question type)
    #
    # This is SAFE because:
    # - DEFAULT 'mcq' fills existing rows automatically.
    # - No existing data is modified.
    # --------------------------------------------------------
    try:
        cursor.execute("ALTER TABLE exams ADD COLUMN exam_type TEXT DEFAULT 'mcq'")
        connection.commit()
    except sqlite3.OperationalError:
        pass

    # --------------------------------------------------------
    # Migration 9: create word_bank_questions table
    #
    # One row per Word Bank question (an entire 10-sentence set
    # is treated as ONE question).
    #
    # student_data_json : JSON sent to the student (NO answers).
    # answer_key_json   : JSON with answers + extra_word (server-only).
    # --------------------------------------------------------
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS word_bank_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exam_id INTEGER NOT NULL,
                question_order INTEGER NOT NULL,
                student_data_json TEXT NOT NULL,
                answer_key_json TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (exam_id)
                    REFERENCES exams(id)
                    ON DELETE CASCADE
            )
        """)
        connection.commit()
    except sqlite3.OperationalError:
        pass

    # --------------------------------------------------------
    # Migration 10: create word_bank_answers table
    #
    # One row per completed Word Bank attempt.
    #
    # selected_answers_json : JSON of {sentence_number: chosen_word}
    # details_json          : JSON list of per-sentence results
    # correct_count         : how many sentences were correct
    # total_count           : total sentences (normally 10)
    # --------------------------------------------------------
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS word_bank_answers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                result_id INTEGER NOT NULL,
                exam_id INTEGER NOT NULL,
                selected_answers_json TEXT,
                details_json TEXT,
                correct_count INTEGER DEFAULT 0,
                total_count INTEGER DEFAULT 0,
                FOREIGN KEY (result_id)
                    REFERENCES results(id)
                    ON DELETE CASCADE,
                FOREIGN KEY (exam_id)
                    REFERENCES exams(id)
                    ON DELETE CASCADE
            )
        """)
        connection.commit()
    except sqlite3.OperationalError:
        pass


def _assign_missing_colors(cursor):
    """Assign palette colors to students that don't have a color yet."""
    cursor.execute("SELECT id FROM students WHERE color IS NULL OR color = '' ORDER BY id")
    rows = cursor.fetchall()
    for index, row in enumerate(rows):
        color = pick_color_for_index(index)
        cursor.execute("UPDATE students SET color = ? WHERE id = ?", (color, row["id"]))


def _migrate_schedule_table(cursor):
    """
    Ensure class_schedule uses student_id instead of class_group_id.

    Strategy:
    - Check existing columns via PRAGMA table_info.
    - If student_id column exists, nothing to do.
    - Otherwise: drop old table and recreate with student_id.
      (Safe because MVP schedule was empty.)
    """
    cursor.execute("PRAGMA table_info(class_schedule)")
    columns = [row["name"] for row in cursor.fetchall()]

    if not columns:
        cursor.execute("""
            CREATE TABLE class_schedule (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                day_of_week TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                notes TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_id)
                    REFERENCES students(id)
                    ON DELETE CASCADE
            )
        """)
        return

    if "student_id" in columns:
        return

    cursor.execute("DROP TABLE IF EXISTS class_schedule")
    cursor.execute("""
        CREATE TABLE class_schedule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            day_of_week TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id)
                REFERENCES students(id)
                ON DELETE CASCADE
        )
    """)


# ============================================================
# DATABASE INITIALIZATION
# ============================================================
#
# Creates all base tables if they don't exist.
# Existing data is never deleted.
# ============================================================

def create_database():
    """
    Create all tables required by the application.
    CREATE TABLE IF NOT EXISTS is used so running this file
    again does not delete existing data.
    """

    connection = get_connection()
    cursor = connection.cursor()

    # --------------------------------------------------------
    # GROUPS (Telegram groups / classes for exams)
    # --------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_group_id INTEGER UNIQUE NOT NULL,
            name TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # --------------------------------------------------------
    # STUDENTS
    #
    # Each student belongs to exactly one group (for exams).
    # color is used for schedule visualization.
    # --------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_user_id INTEGER UNIQUE NOT NULL,
            first_name TEXT,
            last_name TEXT,
            username TEXT,
            group_id INTEGER NOT NULL,
            color TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (group_id)
                REFERENCES groups(id)
                ON DELETE CASCADE
        )
    """)

    # --------------------------------------------------------
    # QUESTIONS (MCQ question bank)
    # --------------------------------------------------------
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

    # --------------------------------------------------------
    # EXAMS
    #
    # exam_type: 'mcq' (default) or 'word_bank'
    # --------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS exams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            time_limit INTEGER NOT NULL,
            category TEXT DEFAULT 'Uncategorized',
            exam_type TEXT DEFAULT 'mcq',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # --------------------------------------------------------
    # EXAM QUESTIONS (links MCQ questions to exams)
    # --------------------------------------------------------
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

    # --------------------------------------------------------
    # RESULTS (one row per completed exam attempt)
    # --------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            exam_id INTEGER NOT NULL,
            score INTEGER NOT NULL,
            total_questions INTEGER NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            is_archived BOOLEAN DEFAULT 0,
            exam_title_snapshot TEXT,
            FOREIGN KEY (student_id)
                REFERENCES students(id)
                ON DELETE CASCADE,
            FOREIGN KEY (exam_id)
                REFERENCES exams(id)
                ON DELETE CASCADE
        )
    """)

    # --------------------------------------------------------
    # STUDENT ANSWERS (per-question MCQ answers)
    # --------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS student_answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            result_id INTEGER NOT NULL,
            question_id INTEGER NOT NULL,
            selected_answer TEXT,
            is_correct BOOLEAN NOT NULL,
            FOREIGN KEY (result_id) REFERENCES results(id) ON DELETE CASCADE,
            FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE
        )
    """)

    # --------------------------------------------------------
    # EXAM ASSIGNMENTS (exam -> group)
    # --------------------------------------------------------
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

    # --------------------------------------------------------
    # ATTENDANCE (session tracking per student)
    # --------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            session_number INTEGER NOT NULL,
            extra_minutes INTEGER DEFAULT 0,
            is_makeup BOOLEAN DEFAULT 0,
            created_at TEXT,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
        )
    """)

    # --------------------------------------------------------
    # CLASS SCHEDULE (weekly private class sessions)
    # --------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS class_schedule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            day_of_week TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id)
                REFERENCES students(id)
                ON DELETE CASCADE
        )
    """)

    # --------------------------------------------------------
    # MAKEUP SESSIONS
    #
    # One-off extra sessions for a specific date (not weekly).
    # These are separate from the weekly class_schedule.
    # --------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS makeup_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            session_date TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            title TEXT,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id)
                REFERENCES students(id)
                ON DELETE CASCADE
        )
    """)
    # --------------------------------------------------------
    # WORD BANK QUESTIONS
    #
    # One row = one complete Word Bank set (10 sentences).
    # Kept entirely separate from the MCQ questions table.
    # --------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS word_bank_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_id INTEGER NOT NULL,
            question_order INTEGER NOT NULL,
            student_data_json TEXT NOT NULL,
            answer_key_json TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (exam_id)
                REFERENCES exams(id)
                ON DELETE CASCADE
        )
    """)

    # --------------------------------------------------------
    # WORD BANK ANSWERS
    #
    # One row per completed Word Bank attempt.
    # --------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS word_bank_answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            result_id INTEGER NOT NULL,
            exam_id INTEGER NOT NULL,
            selected_answers_json TEXT,
            details_json TEXT,
            correct_count INTEGER DEFAULT 0,
            total_count INTEGER DEFAULT 0,
            FOREIGN KEY (result_id)
                REFERENCES results(id)
                ON DELETE CASCADE,
            FOREIGN KEY (exam_id)
                REFERENCES exams(id)
                ON DELETE CASCADE
        )
    """)

    connection.commit()

    # Apply migrations for existing databases.
    run_migrations(connection)

    connection.close()


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    create_database()

    print("=" * 60)
    print("DATABASE CREATED / MIGRATED SUCCESSFULLY")
    print("=" * 60)
    print(f"Database path: {DATABASE_PATH}")
    print()
    print("Schema now includes:")
    print("  - exams.exam_type        (new, default 'mcq')")
    print("  - word_bank_questions    (new table)")
    print("  - word_bank_answers      (new table)")
    print()
    print("Existing MCQ data is untouched.")