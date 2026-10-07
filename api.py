from flask import Flask, jsonify, request, send_from_directory
import sqlite3
import os
import json
import time
import hmac
import hashlib
import requests
from urllib.parse import parse_qsl
from datetime import datetime, timedelta, timezone


app = Flask(
    __name__,
    static_folder="mini_app",
    static_url_path=""
)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_PATH = os.path.join(BASE_DIR, "exam.db")


TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TEACHER_TELEGRAM_ID = os.environ.get("TEACHER_TELEGRAM_ID")
INIT_DATA_MAX_AGE = 3600


# ============================================================
# COLOR PALETTE FOR STUDENTS
# ============================================================

STUDENT_COLOR_PALETTE = [
    "#2563eb", "#10b981", "#f59e0b", "#ef4444",
    "#8b5cf6", "#ec4899", "#06b6d4", "#f97316",
]


def pick_color_for_index(index):
    return STUDENT_COLOR_PALETTE[index % len(STUDENT_COLOR_PALETTE)]


# ============================================================
# DATABASE CONNECTION + AUTOMATIC MIGRATIONS
# ============================================================
#
# Migrations here mirror database.py so that a fresh deployment
# or a partial checkout can still run without manual step.
# Both files must remain in sync.
# ============================================================

def get_database_connection():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.row_factory = sqlite3.Row
    cursor = connection.cursor()

    # exams.category
    try:
        cursor.execute("ALTER TABLE exams ADD COLUMN category TEXT DEFAULT 'Uncategorized'")
        connection.commit()
    except sqlite3.OperationalError:
        pass

    # results.is_archived
    try:
        cursor.execute("ALTER TABLE results ADD COLUMN is_archived BOOLEAN DEFAULT 0")
        connection.commit()
    except sqlite3.OperationalError:
        pass

    # results.exam_title_snapshot
    try:
        cursor.execute("ALTER TABLE results ADD COLUMN exam_title_snapshot TEXT")
        connection.commit()
    except sqlite3.OperationalError:
        pass

    # students.color
    try:
        cursor.execute("ALTER TABLE students ADD COLUMN color TEXT")
        connection.commit()
    except sqlite3.OperationalError:
        pass

    # attendance table
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

    # class_schedule rebuild (student_id based)
    try:
        cursor.execute("PRAGMA table_info(class_schedule)")
        columns = [row["name"] for row in cursor.fetchall()]
        if columns and "student_id" not in columns:
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
                    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
                )
            """)
            connection.commit()
        elif not columns:
            cursor.execute("""
                CREATE TABLE class_schedule (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_id INTEGER NOT NULL,
                    day_of_week TEXT NOT NULL,
                    start_time TEXT NOT NULL,
                    end_time TEXT NOT NULL,
                    notes TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
                )
            """)
            connection.commit()
    except sqlite3.OperationalError:
        pass

    # makeup_sessions table
    try:
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
                FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
            )
        """)
        connection.commit()
    except sqlite3.OperationalError:
        pass

    # drop legacy class_groups
    try:
        cursor.execute("DROP TABLE IF EXISTS class_groups")
        connection.commit()
    except sqlite3.OperationalError:
        pass

    # exams.exam_type
    try:
        cursor.execute("ALTER TABLE exams ADD COLUMN exam_type TEXT DEFAULT 'mcq'")
        connection.commit()
    except sqlite3.OperationalError:
        pass

    # word_bank_questions table
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS word_bank_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exam_id INTEGER NOT NULL,
                question_order INTEGER NOT NULL,
                student_data_json TEXT NOT NULL,
                answer_key_json TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (exam_id) REFERENCES exams(id) ON DELETE CASCADE
            )
        """)
        connection.commit()
    except sqlite3.OperationalError:
        pass

    # word_bank_answers table
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
                FOREIGN KEY (result_id) REFERENCES results(id) ON DELETE CASCADE,
                FOREIGN KEY (exam_id) REFERENCES exams(id) ON DELETE CASCADE
            )
        """)
        connection.commit()
    except sqlite3.OperationalError:
        pass

    return connection


# ============================================================
# TELEGRAM AUTH
# ============================================================

def validate_telegram_init_data(init_data):
    if not TELEGRAM_BOT_TOKEN:
        return {"valid": False, "message": "Telegram Bot Token is not configured."}
    if not init_data:
        return {"valid": False, "message": "Telegram initData is missing."}
    try:
        parsed_data = dict(parse_qsl(init_data, keep_blank_values=True))
    except Exception:
        return {"valid": False, "message": "Telegram initData could not be parsed."}
    received_hash = parsed_data.pop("hash", None)
    if not received_hash:
        return {"valid": False, "message": "Telegram authentication hash is missing."}
    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(parsed_data.items()))
    secret_key = hmac.new(key=b"WebAppData", msg=TELEGRAM_BOT_TOKEN.encode("utf-8"), digestmod=hashlib.sha256).digest()
    calculated_hash = hmac.new(key=secret_key, msg=data_check_string.encode("utf-8"), digestmod=hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated_hash, received_hash):
        return {"valid": False, "message": "Telegram authentication failed."}
    try:
        auth_date = int(parsed_data.get("auth_date", "0"))
    except ValueError:
        return {"valid": False, "message": "Invalid Telegram auth_date."}
    current_time = int(time.time())
    if auth_date <= 0 or current_time - auth_date > INIT_DATA_MAX_AGE:
        return {"valid": False, "message": "Telegram authentication data has expired."}
    user_json = parsed_data.get("user")
    if not user_json:
        return {"valid": False, "message": "Telegram user data is missing."}
    try:
        user_data = json.loads(user_json)
    except json.JSONDecodeError:
        return {"valid": False, "message": "Telegram user data is invalid."}
    telegram_user_id = user_data.get("id")
    if telegram_user_id is None:
        return {"valid": False, "message": "Telegram user ID is missing."}
    return {"valid": True, "user": user_data, "auth_date": auth_date}


def get_authenticated_user():
    init_data = request.headers.get("X-Telegram-Init-Data")
    return validate_telegram_init_data(init_data)


def is_teacher(telegram_user_id):
    if not TEACHER_TELEGRAM_ID:
        return False
    return str(telegram_user_id) == str(TEACHER_TELEGRAM_ID)


def find_student_by_telegram_id(telegram_user_id, connection):
    cursor = connection.cursor()
    cursor.execute("""
        SELECT id, telegram_user_id, first_name, last_name, username, group_id, color
        FROM students WHERE telegram_user_id = ?
    """, (telegram_user_id,))
    return cursor.fetchone()


def check_exam_access(student_id, group_id, exam_id, connection):
    if group_id is None:
        return False
    cursor = connection.cursor()
    cursor.execute("SELECT id FROM exam_assignments WHERE exam_id = ? AND group_id = ? LIMIT 1", (exam_id, group_id))
    return cursor.fetchone() is not None


def has_student_taken_exam(student_id, exam_id, connection):
    cursor = connection.cursor()
    cursor.execute("SELECT id FROM results WHERE student_id = ? AND exam_id = ? LIMIT 1", (student_id, exam_id))
    return cursor.fetchone() is not None


# ============================================================
# WORD BANK — HELPERS
# ============================================================

def detect_question_type(payload):
    """
    Return 'word_bank' or 'mcq' based on the JSON structure.

    Detection rules:
      - If it has 'word_bank' key -> word_bank
      - Else -> mcq
    """
    if isinstance(payload, dict) and "word_bank" in payload:
        return "word_bank"
    return "mcq"

def validate_word_bank_data(data):
    """
    Validate a Word Bank payload.

    Flexible rules (any number of sentences):
      - word_bank length must equal questions length + 1
        (exactly ONE extra/distractor word).
      - All answers must exist in word_bank and be unique.
      - extra_word must exist in word_bank and NOT be one of the answers.

    Returns (True, None) if valid, else (False, "error message").
    """
    if not isinstance(data, dict):
        return False, "Word Bank data must be an object."

    instruction = data.get("instruction", "").strip()
    word_bank = data.get("word_bank", [])
    questions = data.get("questions", [])
    extra_word = (data.get("extra_word") or "").strip()

    if not instruction:
        return False, "Missing 'instruction'."

    if not isinstance(word_bank, list) or len(word_bank) < 2:
        return False, f"'word_bank' must contain at least 2 words (got {len(word_bank) if isinstance(word_bank, list) else 'N/A'})."

    if not isinstance(questions, list) or len(questions) < 1:
        return False, f"'questions' must contain at least 1 sentence (got {len(questions) if isinstance(questions, list) else 'N/A'})."

    # Rule: word_bank must have EXACTLY one extra word.
    if len(word_bank) != len(questions) + 1:
        return False, (
            f"'word_bank' must contain exactly {len(questions) + 1} words "
            f"when there are {len(questions)} sentences (got {len(word_bank)})."
        )

    if not extra_word:
        return False, "Missing 'extra_word'."

    # Normalize words for comparison
    wb_set = set()
    for w in word_bank:
        if not isinstance(w, str) or not w.strip():
            return False, "Every word in 'word_bank' must be a non-empty string."
        wb_set.add(w.strip().lower())

    if len(wb_set) != len(word_bank):
        return False, "'word_bank' contains duplicate words."

    answers = []
    for idx, q in enumerate(questions, start=1):
        if not isinstance(q, dict):
            return False, f"Question {idx} must be an object."
        sentence = (q.get("sentence") or "").strip()
        answer = (q.get("answer") or "").strip()
        if not sentence:
            return False, f"Question {idx} is missing 'sentence'."
        if not answer:
            return False, f"Question {idx} is missing 'answer'."
        answers.append(answer.lower())

    # All answers must exist in word_bank
    for a in answers:
        if a not in wb_set:
            return False, f"Answer '{a}' is not in 'word_bank'."

    # Answers must be unique
    if len(set(answers)) != len(questions):
        return False, "Answers contain duplicates; each word must be used at most once."

    # Extra word must be in word_bank and NOT among answers
    if extra_word.lower() not in wb_set:
        return False, "'extra_word' is not in 'word_bank'."
    if extra_word.lower() in set(answers):
        return False, "'extra_word' appears as an answer; it must remain unused."

    return True, None



def build_word_bank_student_data(data):
    """
    Return the safe version of the Word Bank data (no answers)
    that will be sent to the student.

    IMPORTANT: The sentence stored in the DB contains the full
    sentence WITH the answer word embedded. The student must
    NOT see the answer. Therefore we REPLACE the answer word
    in the sentence with a visible blank marker "_____".

    The frontend can then split on this marker to render a
    proper blank box.
    """
    BLANK_MARKER = "_____"

    safe_questions = []
    for q in data.get("questions", []):
        sentence = q.get("sentence", "")
        answer = (q.get("answer") or "").strip()
        blank_sentence = sentence

        if answer and sentence:
            # Case-insensitive replacement of the FIRST occurrence only.
            lower_sentence = sentence.lower()
            lower_answer = answer.lower()
            idx = lower_sentence.find(lower_answer)
            if idx != -1:
                blank_sentence = (
                    sentence[:idx] +
                    BLANK_MARKER +
                    sentence[idx + len(answer):]
                )

        safe_questions.append({
            "number": q.get("number"),
            "sentence": blank_sentence,
        })

    return {
        "instruction": data.get("instruction", ""),
        "word_bank": data.get("word_bank", []),
        "questions": safe_questions,
    }


def build_word_bank_answer_key(data):
    """
    Return the server-only answer key.
    """
    answers = []
    for q in data.get("questions", []):
        answers.append({
            "number": q.get("number"),
            "answer": (q.get("answer") or "").strip(),
        })
    return {
        "answers": answers,
        "extra_word": (data.get("extra_word") or "").strip(),
    }


def grade_word_bank_submission(student_data, answer_key, submitted_answers):
    """
    Grade a Word Bank submission.

    student_data: dict with 'questions' (each has 'number','sentence')
    answer_key:   dict with 'answers' (list of {number, answer}) and 'extra_word'
    submitted_answers: dict mapping sentence number (as string) to submitted word

    Returns (score, total, details)
      - score: number of correct sentences
      - total: total sentences (usually 10)
      - details: list of dicts with per-sentence info
    """
    answers_map = {}
    for a in answer_key.get("answers", []):
        answers_map[str(a.get("number"))] = (a.get("answer") or "").strip().lower()

    total = len(answers_map)
    score = 0
    details = []

    for q in student_data.get("questions", []):
        num = str(q.get("number"))
        correct = answers_map.get(num, "")
        submitted_raw = submitted_answers.get(num) if isinstance(submitted_answers, dict) else None
        submitted = (submitted_raw or "").strip().lower()
        is_correct = (submitted == correct and correct != "")
        if is_correct:
            score += 1
        details.append({
            "number": q.get("number"),
            "sentence": q.get("sentence"),
            "submitted": submitted_raw if submitted_raw else None,
            "correct_answer": correct,
            "is_correct": is_correct,
        })

    return score, total, details


# ============================================================
# TEACHER NOTIFICATION
# ============================================================

def send_result_to_teacher(student, exam, score, total_questions, completed_at):
    if not TELEGRAM_BOT_TOKEN or not TEACHER_TELEGRAM_ID:
        return False
    first_name = (student["first_name"] or "").strip()
    last_name = (student["last_name"] or "").strip()
    username = (student["username"] or "").strip()
    full_name = " ".join(part for part in [first_name, last_name] if part) or "Unknown student"
    student_display = f"{full_name} (@{username})" if username else full_name
    percentage = round((score / total_questions) * 100) if total_questions > 0 else 0
    message = (
        "📝 <b>Exam Completed</b>\n\n"
        f"<b>Student:</b> {student_display}\n"
        f"<b>Exam:</b> {exam['title']}\n"
        f"<b>Score:</b> {score}/{total_questions}\n"
        f"<b>Percentage:</b> {percentage}%\n"
        f"<b>Completed:</b> {completed_at}"
    )
    telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TEACHER_TELEGRAM_ID, "text": message, "parse_mode": "HTML"}
    try:
        response = requests.post(telegram_url, json=payload, timeout=10)
        if response.ok and response.json().get("ok"):
            return True
        return False
    except Exception as error:
        print("Teacher notification error:", error)
        return False


# ============================================================
# CORE ROUTES
# ============================================================

@app.route("/")
def mini_app():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api")
def api_home():
    return jsonify({"status": "ok", "message": "YEnglish Exams API is running"})


@app.route("/api/me")
def get_current_user():
    auth_result = get_authenticated_user()
    if not auth_result["valid"]:
        return jsonify({"status": "error", "message": auth_result["message"]}), 401
    telegram_user = auth_result["user"]
    teacher = is_teacher(telegram_user["id"])
    connection = get_database_connection()
    try:
        student = find_student_by_telegram_id(telegram_user["id"], connection)
        if student is None and not teacher:
            return jsonify({"status": "error", "message": "Your Telegram account is not registered as a student."}), 403
        response = {
            "status": "success",
            "telegram_user": {
                "id": telegram_user["id"],
                "first_name": telegram_user.get("first_name"),
                "last_name": telegram_user.get("last_name"),
                "username": telegram_user.get("username")
            },
            "is_teacher": teacher,
            "role": "teacher" if teacher else "student"
        }
        if student:
            response["student"] = {
                "id": student["id"],
                "first_name": student["first_name"],
                "last_name": student["last_name"],
                "username": student["username"],
                "group_id": student["group_id"],
                "color": student["color"]
            }
        else:
            response["student"] = None
        return jsonify(response)
    finally:
        connection.close()


# ============================================================
# STUDENT: EXAM ACCESS
# ============================================================

@app.route("/api/exam/<int:exam_id>")
def get_exam(exam_id):
    auth_result = get_authenticated_user()
    if not auth_result["valid"]:
        return jsonify({"status": "error", "message": auth_result["message"]}), 401
    telegram_user = auth_result["user"]
    connection = get_database_connection()
    try:
        student = find_student_by_telegram_id(telegram_user["id"], connection)
        if student is None:
            return jsonify({"status": "error", "message": "Student account is not registered."}), 403
        if has_student_taken_exam(student["id"], exam_id, connection):
            return jsonify({"status": "error", "message": "You have already taken this exam."}), 403
        if not check_exam_access(student["id"], student["group_id"], exam_id, connection):
            return jsonify({"status": "error", "message": "You do not have access to this exam."}), 403
        cursor = connection.cursor()
        cursor.execute("SELECT id, title, time_limit, exam_type FROM exams WHERE id = ?", (exam_id,))
        exam = cursor.fetchone()
        if exam is None:
            return jsonify({"status": "error", "message": "Exam not found."}), 404
        return jsonify({
            "status": "success",
            "exam": {
                "id": exam["id"],
                "title": exam["title"],
                "time_limit": exam["time_limit"],
                "exam_type": exam["exam_type"] or "mcq"
            }
        })
    finally:
        connection.close()


@app.route("/api/exam/<int:exam_id>/questions")
def get_exam_questions(exam_id):
    auth_result = get_authenticated_user()
    if not auth_result["valid"]:
        return jsonify({"status": "error", "message": auth_result["message"]}), 401
    telegram_user = auth_result["user"]
    connection = get_database_connection()
    try:
        student = find_student_by_telegram_id(telegram_user["id"], connection)
        if student is None:
            return jsonify({"status": "error", "message": "Student account is not registered."}), 403
        if has_student_taken_exam(student["id"], exam_id, connection):
            return jsonify({"status": "error", "message": "You have already taken this exam."}), 403
        if not check_exam_access(student["id"], student["group_id"], exam_id, connection):
            return jsonify({"status": "error", "message": "You do not have access to this exam."}), 403

        cursor = connection.cursor()
        cursor.execute("SELECT id, title, time_limit, exam_type FROM exams WHERE id = ?", (exam_id,))
        exam = cursor.fetchone()
        if exam is None:
            return jsonify({"status": "error", "message": "Exam not found."}), 404

        exam_type = exam["exam_type"] or "mcq"

        # ---------------- Word Bank ----------------
        if exam_type == "word_bank":
            cursor.execute("""
                SELECT id, question_order, student_data_json
                FROM word_bank_questions
                WHERE exam_id = ?
                ORDER BY question_order ASC
            """, (exam_id,))
            rows = cursor.fetchall()

            word_bank_questions = []
            for r in rows:
                try:
                    payload = json.loads(r["student_data_json"])
                except Exception:
                    continue
                word_bank_questions.append({
                    "id": r["id"],
                    "question_order": r["question_order"],
                    "instruction": payload.get("instruction", ""),
                    "word_bank": payload.get("word_bank", []),
                    "questions": payload.get("questions", []),
                })

            total_questions = len(word_bank_questions)

            return jsonify({
                "status": "success",
                "exam": {
                    "id": exam["id"],
                    "title": exam["title"],
                    "time_limit": exam["time_limit"],
                    "exam_type": "word_bank"
                },
                "word_bank_questions": word_bank_questions,
                "total_questions": total_questions
            })

        # ---------------- MCQ (existing behavior) ----------------
        cursor.execute("""
            SELECT q.id, q.question_text, q.option_a, q.option_b, q.option_c, q.option_d, eq.question_order
            FROM exam_questions AS eq
            INNER JOIN questions AS q ON q.id = eq.question_id
            WHERE eq.exam_id = ?
            ORDER BY eq.question_order ASC
        """, (exam_id,))
        questions = cursor.fetchall()
        question_list = []
        for question in questions:
            options = {}
            if question["option_a"]:
                options["A"] = question["option_a"]
            if question["option_b"]:
                options["B"] = question["option_b"]
            if question["option_c"]:
                options["C"] = question["option_c"]
            if question["option_d"]:
                options["D"] = question["option_d"]
            question_list.append({
                "id": question["id"],
                "question_text": question["question_text"],
                "options": options,
                "question_order": question["question_order"]
            })
        return jsonify({
            "status": "success",
            "exam": {
                "id": exam["id"],
                "title": exam["title"],
                "time_limit": exam["time_limit"],
                "exam_type": "mcq"
            },
            "questions": question_list,
            "total_questions": len(question_list)
        })
    finally:
        connection.close()


@app.route("/api/teacher/preview_exam/<int:exam_id>")
def teacher_preview_exam(exam_id):
    auth_result = get_authenticated_user()
    if not auth_result["valid"]:
        return jsonify({"status": "error", "message": auth_result["message"]}), 401
    telegram_user = auth_result["user"]
    if not is_teacher(telegram_user["id"]):
        return jsonify({"status": "error", "message": "Access denied."}), 403
    connection = get_database_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT id, title, time_limit, exam_type FROM exams WHERE id = ?", (exam_id,))
        exam = cursor.fetchone()
        if exam is None:
            return jsonify({"status": "error", "message": "Exam not found."}), 404

        exam_type = exam["exam_type"] or "mcq"

        # ---------------- Word Bank ----------------
        if exam_type == "word_bank":
            cursor.execute("""
                SELECT id, question_order, student_data_json
                FROM word_bank_questions
                WHERE exam_id = ?
                ORDER BY question_order ASC
            """, (exam_id,))
            rows = cursor.fetchall()
            word_bank_questions = []
            for r in rows:
                try:
                    payload = json.loads(r["student_data_json"])
                except Exception:
                    continue
                word_bank_questions.append({
                    "id": r["id"],
                    "question_order": r["question_order"],
                    "instruction": payload.get("instruction", ""),
                    "word_bank": payload.get("word_bank", []),
                    "questions": payload.get("questions", []),
                })
            return jsonify({
                "status": "success",
                "exam": {
                    "id": exam["id"],
                    "title": exam["title"],
                    "time_limit": exam["time_limit"],
                    "exam_type": "word_bank"
                },
                "word_bank_questions": word_bank_questions,
                "total_questions": len(word_bank_questions)
            })

        # ---------------- MCQ ----------------
        cursor.execute("""
            SELECT q.id, q.question_text, q.option_a, q.option_b, q.option_c, q.option_d, eq.question_order
            FROM exam_questions AS eq
            INNER JOIN questions AS q ON q.id = eq.question_id
            WHERE eq.exam_id = ?
            ORDER BY eq.question_order ASC
        """, (exam_id,))
        questions = cursor.fetchall()
        question_list = []
        for question in questions:
            options = {}
            if question["option_a"]:
                options["A"] = question["option_a"]
            if question["option_b"]:
                options["B"] = question["option_b"]
            if question["option_c"]:
                options["C"] = question["option_c"]
            if question["option_d"]:
                options["D"] = question["option_d"]
            question_list.append({
                "id": question["id"],
                "question_text": question["question_text"],
                "options": options,
                "question_order": question["question_order"]
            })
        return jsonify({
            "status": "success",
            "exam": {
                "id": exam["id"],
                "title": exam["title"],
                "time_limit": exam["time_limit"],
                "exam_type": "mcq"
            },
            "questions": question_list,
            "total_questions": len(question_list)
        })
    finally:
        connection.close()


@app.route("/api/exam/submit", methods=["POST"])
def submit_exam():
    auth_result = get_authenticated_user()
    if not auth_result["valid"]:
        return jsonify({"status": "error", "message": auth_result["message"]}), 401
    telegram_user = auth_result["user"]
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"status": "error", "message": "Request body is missing or invalid."}), 400
    exam_id = data.get("exam_id")
    if exam_id is None:
        return jsonify({"status": "error", "message": "exam_id is required."}), 400
    started_at = data.get("started_at")

    connection = get_database_connection()
    cursor = connection.cursor()
    try:
        student = find_student_by_telegram_id(telegram_user["id"], connection)
        if student is None:
            return jsonify({"status": "error", "message": "Student account is not registered."}), 403
        if has_student_taken_exam(student["id"], exam_id, connection):
            return jsonify({"status": "error", "message": "You have already taken this exam."}), 403
        if not check_exam_access(student["id"], student["group_id"], exam_id, connection):
            return jsonify({"status": "error", "message": "You do not have access to this exam."}), 403

        cursor.execute("SELECT id, title, exam_type FROM exams WHERE id = ?", (exam_id,))
        exam = cursor.fetchone()
        if exam is None:
            return jsonify({"status": "error", "message": "Exam not found."}), 404

        exam_type = exam["exam_type"] or "mcq"
        completed_at = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=3, minutes=30))).strftime("%Y-%m-%d %H:%M:%S")
        if not started_at:
            started_at = completed_at

        # ---------------- Word Bank submission ----------------
        if exam_type == "word_bank":
            answers = data.get("word_bank_answers")
            if not isinstance(answers, dict):
                return jsonify({"status": "error", "message": "word_bank_answers must be an object."}), 400

            cursor.execute("""
                SELECT id, question_order, student_data_json, answer_key_json
                FROM word_bank_questions
                WHERE exam_id = ?
                ORDER BY question_order ASC
            """, (exam_id,))
            wb_rows = cursor.fetchall()
            if not wb_rows:
                return jsonify({"status": "error", "message": "This exam has no Word Bank questions."}), 400

            total_score = 0
            total_questions = 0
            all_details = []
            for row in wb_rows:
                try:
                    student_data = json.loads(row["student_data_json"])
                    answer_key = json.loads(row["answer_key_json"])
                except Exception:
                    continue
                # The frontend sends answers keyed per Word Bank question id,
                # OR flat per sentence number. We support both:
                qid_str = str(row["id"])
                if qid_str in answers:
                    submitted = answers[qid_str]
                else:
                    submitted = answers  # fallback: flat map

                score, total, details = grade_word_bank_submission(student_data, answer_key, submitted)
                total_score += score
                total_questions += total
                all_details.extend(details)

            if total_questions == 0:
                return jsonify({"status": "error", "message": "Could not grade Word Bank."}), 400

            cursor.execute("""
                INSERT INTO results (student_id, exam_id, score, total_questions, started_at, completed_at, is_archived, exam_title_snapshot)
                VALUES (?, ?, ?, ?, ?, ?, 0, ?)
            """, (student["id"], exam_id, total_score, total_questions, started_at, completed_at, exam["title"]))
            result_id = cursor.lastrowid

            cursor.execute("""
                INSERT INTO word_bank_answers (result_id, exam_id, selected_answers_json, details_json, correct_count, total_count)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                result_id,
                exam_id,
                json.dumps(answers),
                json.dumps(all_details),
                total_score,
                total_questions
            ))

            connection.commit()
            send_result_to_teacher(student, exam, total_score, total_questions, completed_at)

            return jsonify({
                "status": "success",
                "message": "Exam submitted successfully.",
                "result": {
                    "id": result_id,
                    "exam_id": exam_id,
                    "student_id": student["id"],
                    "score": total_score,
                    "total_questions": total_questions,
                    "completed_at": completed_at,
                    "exam_type": "word_bank",
                    "teacher_notified": True
                }
            })

        # ---------------- MCQ submission (existing behavior) ----------------
        answers = data.get("answers")
        if not isinstance(answers, dict):
            return jsonify({"status": "error", "message": "answers must be an object."}), 400

        cursor.execute("""
            SELECT q.id, q.correct_answer, eq.question_order
            FROM exam_questions AS eq
            INNER JOIN questions AS q ON q.id = eq.question_id
            WHERE eq.exam_id = ?
            ORDER BY eq.question_order ASC
        """, (exam_id,))
        questions = cursor.fetchall()
        total_questions = len(questions)
        if total_questions == 0:
            return jsonify({"status": "error", "message": "This exam has no questions."}), 400

        score = 0
        for question in questions:
            question_id = str(question["id"])
            correct_answer = str(question["correct_answer"]).strip().upper()
            submitted_answer = answers.get(question_id)
            if submitted_answer is None:
                continue
            submitted_answer = str(submitted_answer).strip().upper()
            if submitted_answer == correct_answer:
                score += 1

        cursor.execute("""
            INSERT INTO results (student_id, exam_id, score, total_questions, started_at, completed_at, is_archived, exam_title_snapshot)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?)
        """, (student["id"], exam_id, score, total_questions, started_at, completed_at, exam["title"]))
        result_id = cursor.lastrowid

        for question in questions:
            question_id = str(question["id"])
            correct_answer = str(question["correct_answer"]).strip().upper()
            submitted_answer = answers.get(question_id)
            if submitted_answer is None:
                submitted_answer = None
                is_correct = False
            else:
                submitted_answer = str(submitted_answer).strip().upper()
                is_correct = (submitted_answer == correct_answer)
            cursor.execute("""
                INSERT INTO student_answers (result_id, question_id, selected_answer, is_correct)
                VALUES (?, ?, ?, ?)
            """, (result_id, question_id, submitted_answer, is_correct))

        connection.commit()
        send_result_to_teacher(student, exam, score, total_questions, completed_at)

        return jsonify({
            "status": "success",
            "message": "Exam submitted successfully.",
            "result": {
                "id": result_id,
                "exam_id": exam_id,
                "student_id": student["id"],
                "score": score,
                "total_questions": total_questions,
                "completed_at": completed_at,
                "exam_type": "mcq",
                "teacher_notified": True
            }
        })
    except Exception as error:
        connection.rollback()
        print("SUBMIT EXAM ERROR:", error)
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": "An internal server error occurred."}), 500
    finally:
        connection.close()


# ============================================================
# TEACHER ENDPOINTS
# ============================================================

@app.route("/api/teacher/students")
def teacher_get_students():
    auth_result = get_authenticated_user()
    if not auth_result["valid"]:
        return jsonify({"status": "error", "message": auth_result["message"]}), 401
    telegram_user = auth_result["user"]
    if not is_teacher(telegram_user["id"]):
        return jsonify({"status": "error", "message": "Access denied."}), 403
    connection = get_database_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("""
            SELECT s.id, s.telegram_user_id, s.first_name, s.last_name, s.username, s.group_id, s.color,
                   g.name AS group_name, g.telegram_group_id
            FROM students s JOIN groups g ON g.id = s.group_id ORDER BY s.id
        """)
        students = cursor.fetchall()
        return jsonify({"status": "success", "students": [{"id": s["id"], "telegram_user_id": s["telegram_user_id"], "first_name": s["first_name"], "last_name": s["last_name"], "username": s["username"], "group_id": s["group_id"], "group_name": s["group_name"], "telegram_group_id": s["telegram_group_id"], "color": s["color"]} for s in students], "total": len(students)})
    finally:
        connection.close()


@app.route("/api/teacher/students", methods=["POST"])
def teacher_add_student():
    auth_result = get_authenticated_user()
    if not auth_result["valid"]:
        return jsonify({"status": "error", "message": auth_result["message"]}), 401
    telegram_user = auth_result["user"]
    if not is_teacher(telegram_user["id"]):
        return jsonify({"status": "error", "message": "Access denied."}), 403
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "Request body is missing."}), 400
    telegram_user_id = data.get("telegram_user_id")
    first_name = data.get("first_name", "").strip()
    last_name = data.get("last_name", "").strip()
    username = data.get("username", "").strip()
    group_id = data.get("group_id")
    if not telegram_user_id or not first_name or not group_id:
        return jsonify({"status": "error", "message": "telegram_user_id, first_name, and group_id are required."}), 400
    connection = get_database_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT id FROM groups WHERE id = ?", (group_id,))
        if not cursor.fetchone():
            return jsonify({"status": "error", "message": "Group not found."}), 404
        cursor.execute("SELECT COUNT(*) FROM students")
        count = cursor.fetchone()[0]
        color = pick_color_for_index(count)
        cursor.execute("INSERT INTO students (telegram_user_id, first_name, last_name, username, group_id, color) VALUES (?, ?, ?, ?, ?, ?)", (telegram_user_id, first_name, last_name, username, group_id, color))
        connection.commit()
        return jsonify({"status": "success", "message": "Student added successfully.", "student_id": cursor.lastrowid, "color": color})
    except sqlite3.IntegrityError:
        return jsonify({"status": "error", "message": "This student is already registered."}), 400
    except Exception as error:
        connection.rollback()
        return jsonify({"status": "error", "message": str(error)}), 500
    finally:
        connection.close()


@app.route("/api/teacher/students", methods=["DELETE"])
def teacher_delete_student():
    auth_result = get_authenticated_user()
    if not auth_result["valid"]:
        return jsonify({"status": "error", "message": auth_result["message"]}), 401
    telegram_user = auth_result["user"]
    if not is_teacher(telegram_user["id"]):
        return jsonify({"status": "error", "message": "Access denied."}), 403
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "Invalid request."}), 400
    student_id = data.get("student_id")
    if not student_id:
        return jsonify({"status": "error", "message": "student_id is required."}), 400
    connection = get_database_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("DELETE FROM students WHERE id = ?", (student_id,))
        connection.commit()
        if cursor.rowcount == 0:
            return jsonify({"status": "error", "message": "Student not found."}), 404
        return jsonify({"status": "success", "message": "Student deleted successfully."})
    except Exception as error:
        connection.rollback()
        return jsonify({"status": "error", "message": str(error)}), 500
    finally:
        connection.close()


@app.route("/api/teacher/student/<int:student_id>")
def teacher_get_student_profile(student_id):
    auth_result = get_authenticated_user()
    if not auth_result["valid"]:
        return jsonify({"status": "error", "message": auth_result["message"]}), 401
    telegram_user = auth_result["user"]
    if not is_teacher(telegram_user["id"]):
        return jsonify({"status": "error", "message": "Access denied."}), 403
    connection = get_database_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("""
            SELECT s.id, s.telegram_user_id, s.first_name, s.last_name, s.username, s.group_id, s.color,
                   g.name AS group_name, g.telegram_group_id
            FROM students s JOIN groups g ON g.id = s.group_id WHERE s.id = ?
        """, (student_id,))
        student = cursor.fetchone()
        if not student:
            return jsonify({"status": "error", "message": "Student not found."}), 404
        cursor.execute("""
            SELECT r.id, r.score, r.total_questions, r.started_at, r.completed_at, r.is_archived,
                   r.exam_title_snapshot, r.exam_id
            FROM results r
            WHERE r.student_id = ? AND r.is_archived = 1
            ORDER BY r.completed_at DESC
        """, (student_id,))
        results = cursor.fetchall()
        result_list = []
        for r in results:
            percentage = round((r["score"] / r["total_questions"]) * 100) if r["total_questions"] > 0 else 0
            result_list.append({
                "id": r["id"],
                "exam_title": r["exam_title_snapshot"] or "Deleted Exam",
                "exam_id": r["exam_id"],
                "score": r["score"],
                "total_questions": r["total_questions"],
                "percentage": percentage,
                "completed_at": r["completed_at"]
            })
        cursor.execute("""
            SELECT id, session_number, extra_minutes, is_makeup, created_at
            FROM attendance
            WHERE student_id = ?
            ORDER BY session_number DESC, created_at DESC
        """, (student_id,))
        attendance = cursor.fetchall()
        attendance_list = []
        for a in attendance:
            attendance_list.append({
                "id": a["id"],
                "session_number": a["session_number"],
                "extra_minutes": a["extra_minutes"],
                "is_makeup": bool(a["is_makeup"]),
                "created_at": a["created_at"]
            })
        return jsonify({
            "status": "success",
            "student": {
                "id": student["id"], "telegram_user_id": student["telegram_user_id"],
                "first_name": student["first_name"], "last_name": student["last_name"],
                "username": student["username"], "group_id": student["group_id"],
                "group_name": student["group_name"], "telegram_group_id": student["telegram_group_id"],
                "color": student["color"]
            },
            "results": result_list,
            "total_results": len(result_list),
            "attendance": attendance_list,
            "total_attendance": len(attendance_list)
        })
    finally:
        connection.close()


@app.route("/api/teacher/student/<int:student_id>/color", methods=["PUT"])
def teacher_update_student_color(student_id):
    auth_result = get_authenticated_user()
    if not auth_result["valid"]:
        return jsonify({"status": "error", "message": auth_result["message"]}), 401
    telegram_user = auth_result["user"]
    if not is_teacher(telegram_user["id"]):
        return jsonify({"status": "error", "message": "Access denied."}), 403
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "Invalid request."}), 400
    color = (data.get("color") or "").strip()
    if not color:
        return jsonify({"status": "error", "message": "color is required."}), 400
    connection = get_database_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("UPDATE students SET color = ? WHERE id = ?", (color, student_id))
        connection.commit()
        if cursor.rowcount == 0:
            return jsonify({"status": "error", "message": "Student not found."}), 404
        return jsonify({"status": "success", "message": "Student color updated."})
    finally:
        connection.close()


# ============================================================
# ATTENDANCE
# ============================================================

@app.route("/api/teacher/attendance", methods=["POST"])
def teacher_add_attendance():
    auth_result = get_authenticated_user()
    if not auth_result["valid"]:
        return jsonify({"status": "error", "message": auth_result["message"]}), 401
    telegram_user = auth_result["user"]
    if not is_teacher(telegram_user["id"]):
        return jsonify({"status": "error", "message": "Access denied."}), 403
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "Invalid request."}), 400
    student_id = data.get("student_id")
    session_number = data.get("session_number")
    if not student_id:
        return jsonify({"status": "error", "message": "student_id is required."}), 400
    connection = get_database_connection()
    cursor = connection.cursor()
    try:
        if session_number is None:
            cursor.execute("SELECT MAX(session_number) as max_session FROM attendance WHERE student_id = ? AND is_makeup = 0", (student_id,))
            row = cursor.fetchone()
            if row and row["max_session"]:
                session_number = row["max_session"] + 1
            else:
                return jsonify({"status": "error", "message": "First session number is required.", "need_first_session": True}), 400
        created_at = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=3, minutes=30))).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("INSERT INTO attendance (student_id, session_number, extra_minutes, is_makeup, created_at) VALUES (?, ?, 0, 0, ?)", (student_id, session_number, created_at))
        connection.commit()
        return jsonify({"status": "success", "message": "Session recorded successfully.", "attendance": {"id": cursor.lastrowid, "session_number": session_number, "extra_minutes": 0, "is_makeup": False, "created_at": created_at}})
    except Exception as error:
        connection.rollback()
        return jsonify({"status": "error", "message": str(error)}), 500
    finally:
        connection.close()


@app.route("/api/teacher/attendance/<int:attendance_id>", methods=["PUT"])
def teacher_update_attendance(attendance_id):
    auth_result = get_authenticated_user()
    if not auth_result["valid"]:
        return jsonify({"status": "error", "message": auth_result["message"]}), 401
    telegram_user = auth_result["user"]
    if not is_teacher(telegram_user["id"]):
        return jsonify({"status": "error", "message": "Access denied."}), 403
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "Invalid request."}), 400
    connection = get_database_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("SELECT id FROM attendance WHERE id = ?", (attendance_id,))
        if not cursor.fetchone():
            return jsonify({"status": "error", "message": "Attendance not found."}), 404
        if "extra_minutes" in data:
            cursor.execute("UPDATE attendance SET extra_minutes = ? WHERE id = ?", (data["extra_minutes"], attendance_id))
        if "is_makeup" in data:
            cursor.execute("UPDATE attendance SET is_makeup = ? WHERE id = ?", (1 if data["is_makeup"] else 0, attendance_id))
        if "toggle_makeup" in data:
            cursor.execute("SELECT is_makeup FROM attendance WHERE id = ?", (attendance_id,))
            current = cursor.fetchone()
            if current:
                new_value = 0 if current["is_makeup"] else 1
                cursor.execute("UPDATE attendance SET is_makeup = ? WHERE id = ?", (new_value, attendance_id))
        connection.commit()
        return jsonify({"status": "success", "message": "Attendance updated successfully."})
    except Exception as error:
        connection.rollback()
        return jsonify({"status": "error", "message": str(error)}), 500
    finally:
        connection.close()


# ============================================================
# GROUPS
# ============================================================

@app.route("/api/teacher/groups")
def teacher_get_groups():
    auth_result = get_authenticated_user()
    if not auth_result["valid"]:
        return jsonify({"status": "error", "message": auth_result["message"]}), 401
    telegram_user = auth_result["user"]
    if not is_teacher(telegram_user["id"]):
        return jsonify({"status": "error", "message": "Access denied."}), 403
    connection = get_database_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT id, telegram_group_id, name, created_at FROM groups ORDER BY name")
        groups = cursor.fetchall()
        return jsonify({"status": "success", "groups": [{"id": g["id"], "telegram_group_id": g["telegram_group_id"], "name": g["name"], "created_at": g["created_at"]} for g in groups], "total": len(groups)})
    finally:
        connection.close()


@app.route("/api/teacher/groups", methods=["POST"])
def teacher_add_group():
    auth_result = get_authenticated_user()
    if not auth_result["valid"]:
        return jsonify({"status": "error", "message": auth_result["message"]}), 401
    telegram_user = auth_result["user"]
    if not is_teacher(telegram_user["id"]):
        return jsonify({"status": "error", "message": "Access denied."}), 403
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "Request body is missing."}), 400
    name = data.get("name", "").strip()
    telegram_group_id = data.get("telegram_group_id")
    if not name or not telegram_group_id:
        return jsonify({"status": "error", "message": "name and telegram_group_id are required."}), 400
    connection = get_database_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("INSERT INTO groups (name, telegram_group_id) VALUES (?, ?)", (name, telegram_group_id))
        connection.commit()
        return jsonify({"status": "success", "message": "Group added successfully.", "group_id": cursor.lastrowid})
    except sqlite3.IntegrityError:
        return jsonify({"status": "error", "message": "This group is already registered."}), 400
    except Exception as error:
        connection.rollback()
        return jsonify({"status": "error", "message": str(error)}), 500
    finally:
        connection.close()


# ============================================================
# QUESTIONS (MCQ question bank)
# ============================================================

@app.route("/api/teacher/questions")
def teacher_get_questions():
    auth_result = get_authenticated_user()
    if not auth_result["valid"]:
        return jsonify({"status": "error", "message": auth_result["message"]}), 401
    telegram_user = auth_result["user"]
    if not is_teacher(telegram_user["id"]):
        return jsonify({"status": "error", "message": "Access denied."}), 403
    connection = get_database_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT id, question_text, option_a, option_b, option_c, option_d, correct_answer, created_at FROM questions ORDER BY id")
        questions = cursor.fetchall()
        return jsonify({"status": "success", "questions": [{"id": q["id"], "question_text": q["question_text"], "option_a": q["option_a"], "option_b": q["option_b"], "option_c": q["option_c"], "option_d": q["option_d"], "correct_answer": q["correct_answer"], "created_at": q["created_at"]} for q in questions], "total": len(questions)})
    finally:
        connection.close()


# ============================================================
# EXAMS (list / edit / delete)
# ============================================================

@app.route("/api/teacher/exams")
def teacher_get_exams():
    auth_result = get_authenticated_user()
    if not auth_result["valid"]:
        return jsonify({"status": "error", "message": auth_result["message"]}), 401
    telegram_user = auth_result["user"]
    if not is_teacher(telegram_user["id"]):
        return jsonify({"status": "error", "message": "Access denied."}), 403
    connection = get_database_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("""
            SELECT e.id, e.title, e.time_limit, e.category, e.exam_type, e.created_at,
                   (SELECT COUNT(*) FROM exam_questions eq WHERE eq.exam_id = e.id) AS mcq_count,
                   (SELECT COUNT(*) FROM word_bank_questions wb WHERE wb.exam_id = e.id) AS wb_count
            FROM exams e
            ORDER BY e.id
        """)
        exams = cursor.fetchall()
        result_list = []
        for e in exams:
            exam_type = e["exam_type"] or "mcq"
            if exam_type == "word_bank":
                question_count = e["wb_count"]
            else:
                question_count = e["mcq_count"]
            result_list.append({
                "id": e["id"],
                "title": e["title"],
                "time_limit": e["time_limit"],
                "category": e["category"] or "Uncategorized",
                "exam_type": exam_type,
                "question_count": question_count,
                "created_at": e["created_at"]
            })
        return jsonify({"status": "success", "exams": result_list, "total": len(result_list)})
    finally:
        connection.close()


@app.route("/api/teacher/exams", methods=["DELETE"])
def teacher_delete_exam():
    auth_result = get_authenticated_user()
    if not auth_result["valid"]:
        return jsonify({"status": "error", "message": auth_result["message"]}), 401
    telegram_user = auth_result["user"]
    if not is_teacher(telegram_user["id"]):
        return jsonify({"status": "error", "message": "Access denied."}), 403
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "Invalid request."}), 400
    exam_id = data.get("exam_id")
    connection = get_database_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("DELETE FROM exam_questions WHERE exam_id = ?", (exam_id,))
        cursor.execute("DELETE FROM word_bank_questions WHERE exam_id = ?", (exam_id,))
        cursor.execute("DELETE FROM exam_assignments WHERE exam_id = ?", (exam_id,))
        cursor.execute("DELETE FROM exams WHERE id = ?", (exam_id,))
        connection.commit()
        return jsonify({"status": "success", "message": "Exam deleted. Results are preserved."})
    except Exception as error:
        connection.rollback()
        return jsonify({"status": "error", "message": str(error)}), 500
    finally:
        connection.close()


@app.route("/api/teacher/exams", methods=["PUT"])
def teacher_update_exam():
    auth_result = get_authenticated_user()
    if not auth_result["valid"]:
        return jsonify({"status": "error", "message": auth_result["message"]}), 401
    telegram_user = auth_result["user"]
    if not is_teacher(telegram_user["id"]):
        return jsonify({"status": "error", "message": "Access denied."}), 403
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "Invalid request."}), 400
    exam_id = data.get("exam_id")
    title = data.get("title", "").strip()
    time_limit = data.get("time_limit")
    category = data.get("category", "").strip()
    if not exam_id or not title or not time_limit:
        return jsonify({"status": "error", "message": "exam_id, title, and time_limit are required."}), 400
    connection = get_database_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("UPDATE exams SET title = ?, time_limit = ?, category = ? WHERE id = ?", (title, time_limit, category, exam_id))
        connection.commit()
        if cursor.rowcount == 0:
            return jsonify({"status": "error", "message": "Exam not found."}), 404
        return jsonify({"status": "success", "message": "Exam updated successfully."})
    except Exception as error:
        connection.rollback()
        return jsonify({"status": "error", "message": str(error)}), 500
    finally:
        connection.close()


# ============================================================
# ASSIGNMENTS
# ============================================================

@app.route("/api/teacher/assignments")
def teacher_get_assignments():
    auth_result = get_authenticated_user()
    if not auth_result["valid"]:
        return jsonify({"status": "error", "message": auth_result["message"]}), 401
    telegram_user = auth_result["user"]
    if not is_teacher(telegram_user["id"]):
        return jsonify({"status": "error", "message": "Access denied."}), 403
    connection = get_database_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("""
            SELECT ea.id AS assignment_id, ea.assigned_at, e.id AS exam_id, e.title AS exam_title,
                   g.id AS group_id, g.name AS group_name, g.telegram_group_id
            FROM exam_assignments ea
            JOIN exams e ON e.id = ea.exam_id
            JOIN groups g ON g.id = ea.group_id
            ORDER BY ea.id
        """)
        assignments = cursor.fetchall()
        return jsonify({"status": "success", "assignments": [{"assignment_id": a["assignment_id"], "exam_id": a["exam_id"], "exam_title": a["exam_title"], "group_id": a["group_id"], "group_name": a["group_name"], "telegram_group_id": a["telegram_group_id"], "assigned_at": a["assigned_at"]} for a in assignments], "total": len(assignments)})
    finally:
        connection.close()


@app.route("/api/teacher/assign_exam", methods=["POST"])
def teacher_assign_exam():
    auth_result = get_authenticated_user()
    if not auth_result["valid"]:
        return jsonify({"status": "error", "message": auth_result["message"]}), 401
    telegram_user = auth_result["user"]
    if not is_teacher(telegram_user["id"]):
        return jsonify({"status": "error", "message": "Access denied."}), 403
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "Invalid request."}), 400
    exam_id = data.get("exam_id")
    group_ids = data.get("group_ids")
    if not exam_id or not group_ids:
        return jsonify({"status": "error", "message": "exam_id and group_ids are required."}), 400
    if not isinstance(group_ids, list):
        return jsonify({"status": "error", "message": "group_ids must be a list."}), 400
    connection = get_database_connection()
    cursor = connection.cursor()
    try:
        assigned_count = 0
        for group_id in group_ids:
            try:
                cursor.execute("INSERT INTO exam_assignments (exam_id, group_id) VALUES (?, ?)", (exam_id, group_id))
                assigned_count += 1
            except sqlite3.IntegrityError:
                pass
        connection.commit()
        return jsonify({"status": "success", "message": f"Exam assigned to {assigned_count} group(s)."})
    except Exception as error:
        connection.rollback()
        return jsonify({"status": "error", "message": str(error)}), 500
    finally:
        connection.close()

@app.route("/api/teacher/unassign_exam", methods=["POST"])
def teacher_unassign_exam():
    auth_result = get_authenticated_user()
    if not auth_result["valid"]:
        return jsonify({"status": "error", "message": auth_result["message"]}), 401
    telegram_user = auth_result["user"]
    if not is_teacher(telegram_user["id"]):
        return jsonify({"status": "error", "message": "Access denied."}), 403
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "Invalid request."}), 400
    exam_id = data.get("exam_id")
    group_id = data.get("group_id")  # optional: if provided, remove only this pair

    if not exam_id:
        return jsonify({"status": "error", "message": "exam_id required."}), 400

    connection = get_database_connection()
    cursor = connection.cursor()
    try:
        if group_id is not None:
            # Remove only this exam-group pair
            cursor.execute(
                "DELETE FROM exam_assignments WHERE exam_id = ? AND group_id = ?",
                (exam_id, group_id)
            )
            message = "Exam unassigned from this group. Results are preserved."
        else:
            # Remove all assignments for this exam
            cursor.execute("DELETE FROM exam_assignments WHERE exam_id = ?", (exam_id,))
            message = "Exam unassigned from all groups. Results are preserved."
        connection.commit()
        return jsonify({"status": "success", "message": message})
    except Exception as error:
        connection.rollback()
        return jsonify({"status": "error", "message": str(error)}), 500
    finally:
        connection.close()



@app.route("/api/teacher/send_exam_by_exam_id", methods=["POST"])
def teacher_send_exam_by_exam_id():
    auth_result = get_authenticated_user()
    if not auth_result["valid"]:
        return jsonify({"status": "error", "message": auth_result["message"]}), 401
    telegram_user = auth_result["user"]
    if not is_teacher(telegram_user["id"]):
        return jsonify({"status": "error", "message": "Access denied."}), 403
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "Invalid request."}), 400
    exam_id = data.get("exam_id")
    group_ids = data.get("group_ids")
    if not exam_id or not group_ids:
        return jsonify({"status": "error", "message": "exam_id and group_ids are required."}), 400
    if not isinstance(group_ids, list):
        return jsonify({"status": "error", "message": "group_ids must be a list."}), 400
    connection = get_database_connection()
    cursor = connection.cursor()
    try:
        exam = cursor.execute("SELECT id, title, time_limit, exam_type FROM exams WHERE id = ?", (exam_id,)).fetchone()
        if not exam:
            return jsonify({"status": "error", "message": "Exam not found."}), 404

        exam_type = exam["exam_type"] or "mcq"
        if exam_type == "word_bank":
            question_count = cursor.execute("SELECT COUNT(*) FROM word_bank_questions WHERE exam_id = ?", (exam_id,)).fetchone()[0]
        else:
            question_count = cursor.execute("SELECT COUNT(*) FROM exam_questions WHERE exam_id = ?", (exam_id,)).fetchone()[0]

        bot_username = "YEnglsihExamsbot"
        deep_link = f"https://t.me/{bot_username}?startapp=exam_{exam_id}"
        import asyncio
        from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        message = (f"📝 EXAM\n\nTitle: {exam['title']}\nQuestions: {question_count}\nTime Limit: {exam['time_limit']} minutes\n\nWhen you are ready, press the button below to start the exam.")
        keyboard = [[InlineKeyboardButton("📝 Start Exam", url=deep_link)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        sent_count = 0
        for group_id in group_ids:
            try:
                group = cursor.execute("SELECT telegram_group_id, name FROM groups WHERE id = ?", (group_id,)).fetchone()
                if not group:
                    continue
                asyncio.run(bot.send_message(
                    chat_id=group["telegram_group_id"],
                    text=message,
                    reply_markup=reply_markup
                ))
                sent_count += 1
            except Exception as e:
                print(f"Error sending to group {group_id}: {e}")
        return jsonify({"status": "success", "message": f"Exam sent to {sent_count} group(s)."})
    except Exception as error:
        print("SEND EXAM ERROR:", error)
        return jsonify({"status": "error", "message": str(error)}), 500
    finally:
        connection.close()


# ============================================================
# RESULTS
# ============================================================

@app.route("/api/teacher/results")
def teacher_get_results():
    auth_result = get_authenticated_user()
    if not auth_result["valid"]:
        return jsonify({"status": "error", "message": auth_result["message"]}), 401
    telegram_user = auth_result["user"]
    if not is_teacher(telegram_user["id"]):
        return jsonify({"status": "error", "message": "Access denied."}), 403
    connection = get_database_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("""
            SELECT r.id, r.score, r.total_questions, r.started_at, r.completed_at, r.is_archived,
                   r.exam_title_snapshot, r.exam_id,
                   s.first_name, s.last_name, s.username, s.telegram_user_id,
                   g.name AS group_name,
                   COALESCE(e.exam_type, 'mcq') AS exam_type
            FROM results r
            JOIN students s ON s.id = r.student_id
            JOIN groups g ON g.id = s.group_id
            LEFT JOIN exams e ON e.id = r.exam_id
            WHERE r.is_archived = 0
            ORDER BY r.completed_at DESC
        """)
        results = cursor.fetchall()
        result_list = []
        for r in results:
            percentage = round((r["score"] / r["total_questions"]) * 100) if r["total_questions"] > 0 else 0
            result_list.append({
                "id": r["id"], "student_name": f"{r['first_name']} {r['last_name'] or ''}".strip(),
                "student_username": r["username"], "telegram_user_id": r["telegram_user_id"],
                "exam_title": r["exam_title_snapshot"] or "Deleted Exam",
                "exam_id": r["exam_id"], "score": r["score"],
                "total_questions": r["total_questions"], "percentage": percentage,
                "group_name": r["group_name"], "started_at": r["started_at"], "completed_at": r["completed_at"],
                "exam_type": r["exam_type"]
            })
        return jsonify({"status": "success", "results": result_list, "total": len(result_list)})
    finally:
        connection.close()


@app.route("/api/teacher/results", methods=["DELETE"])
def teacher_delete_result():
    auth_result = get_authenticated_user()
    if not auth_result["valid"]:
        return jsonify({"status": "error", "message": auth_result["message"]}), 401
    telegram_user = auth_result["user"]
    if not is_teacher(telegram_user["id"]):
        return jsonify({"status": "error", "message": "Access denied."}), 403
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "Invalid request."}), 400
    result_id = data.get("result_id")
    if not result_id:
        return jsonify({"status": "error", "message": "result_id is required."}), 400
    connection = get_database_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("UPDATE results SET is_archived = 1 WHERE id = ?", (result_id,))
        connection.commit()
        if cursor.rowcount == 0:
            return jsonify({"status": "error", "message": "Result not found."}), 404
        return jsonify({"status": "success", "message": "Result archived (not deleted)."})
    except Exception as error:
        connection.rollback()
        return jsonify({"status": "error", "message": str(error)}), 500
    finally:
        connection.close()


@app.route("/api/teacher/archive_result", methods=["POST"])
def teacher_archive_result():
    auth_result = get_authenticated_user()
    if not auth_result["valid"]:
        return jsonify({"status": "error", "message": auth_result["message"]}), 401
    telegram_user = auth_result["user"]
    if not is_teacher(telegram_user["id"]):
        return jsonify({"status": "error", "message": "Access denied."}), 403
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "Invalid request."}), 400
    result_id = data.get("result_id")
    if not result_id:
        return jsonify({"status": "error", "message": "result_id is required."}), 400
    connection = get_database_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("UPDATE results SET is_archived = 1 WHERE id = ?", (result_id,))
        connection.commit()
        if cursor.rowcount == 0:
            return jsonify({"status": "error", "message": "Result not found."}), 404
        return jsonify({"status": "success", "message": "Result archived successfully."})
    except Exception as error:
        connection.rollback()
        return jsonify({"status": "error", "message": str(error)}), 500
    finally:
        connection.close()


@app.route("/api/teacher/unarchive_result", methods=["POST"])
def teacher_unarchive_result():
    auth_result = get_authenticated_user()
    if not auth_result["valid"]:
        return jsonify({"status": "error", "message": auth_result["message"]}), 401
    telegram_user = auth_result["user"]
    if not is_teacher(telegram_user["id"]):
        return jsonify({"status": "error", "message": "Access denied."}), 403
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "Invalid request."}), 400
    result_id = data.get("result_id")
    if not result_id:
        return jsonify({"status": "error", "message": "result_id is required."}), 400
    connection = get_database_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("UPDATE results SET is_archived = 0 WHERE id = ?", (result_id,))
        connection.commit()
        if cursor.rowcount == 0:
            return jsonify({"status": "error", "message": "Result not found."}), 404
        return jsonify({"status": "success", "message": "Result unarchived successfully."})
    except Exception as error:
        connection.rollback()
        return jsonify({"status": "error", "message": str(error)}), 500
    finally:
        connection.close()


@app.route("/api/teacher/result_details/<int:result_id>")
def teacher_result_details(result_id):
    auth_result = get_authenticated_user()
    if not auth_result["valid"]:
        return jsonify({"status": "error", "message": auth_result["message"]}), 401
    telegram_user = auth_result["user"]
    if not is_teacher(telegram_user["id"]):
        return jsonify({"status": "error", "message": "Access denied."}), 403
    connection = get_database_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("""
            SELECT r.id, r.score, r.total_questions, r.started_at, r.completed_at,
                   r.exam_title_snapshot, r.exam_id,
                   COALESCE(e.exam_type, 'mcq') AS exam_type,
                   s.first_name, s.last_name, s.telegram_user_id
            FROM results r
            JOIN students s ON s.id = r.student_id
            LEFT JOIN exams e ON e.id = r.exam_id
            WHERE r.id = ?
        """, (result_id,))
        result = cursor.fetchone()
        if not result:
            return jsonify({"status": "error", "message": "Result not found."}), 404

        exam_type = result["exam_type"] or "mcq"

        # ---------------- Word Bank details ----------------
        if exam_type == "word_bank":
            cursor.execute("""
                SELECT selected_answers_json, details_json
                FROM word_bank_answers
                WHERE result_id = ?
                LIMIT 1
            """, (result_id,))
            wb = cursor.fetchone()

            details = []
            if wb and wb["details_json"]:
                try:
                    details = json.loads(wb["details_json"])
                except Exception:
                    details = []

            wrong_list = []
            for d in details:
                if not d.get("is_correct"):
                    wrong_list.append({
                        "question_text": d.get("sentence", ""),
                        "selected_answer": d.get("submitted") or "No answer",
                        "correct_answer": d.get("correct_answer", "")
                    })

            return jsonify({
                "status": "success",
                "result": {
                    "id": result["id"],
                    "student_name": f"{result['first_name']} {result['last_name'] or ''}".strip(),
                    "exam_title": result["exam_title_snapshot"] or "Deleted Exam",
                    "score": result["score"],
                    "total_questions": result["total_questions"],
                    "completed_at": result["completed_at"],
                    "exam_type": "word_bank",
                    "wrong_answers": wrong_list
                }
            })

        # ---------------- MCQ details (existing) ----------------
        cursor.execute("""
            SELECT q.id, q.question_text, q.option_a, q.option_b, q.option_c, q.option_d, q.correct_answer,
                   sa.selected_answer, sa.is_correct
            FROM student_answers sa
            JOIN questions q ON q.id = sa.question_id
            WHERE sa.result_id = ? AND sa.is_correct = 0
            ORDER BY q.id
        """, (result_id,))
        wrong_answers = cursor.fetchall()
        wrong_list = []
        for w in wrong_answers:
            options = {
                "A": w["option_a"],
                "B": w["option_b"],
                "C": w["option_c"],
                "D": w["option_d"]
            }
            selected_text = options.get(w["selected_answer"], w["selected_answer"]) if w["selected_answer"] else "No answer"
            wrong_list.append({
                "question_text": w["question_text"],
                "selected_answer": f"{w['selected_answer']}) {selected_text}" if w['selected_answer'] else "No answer",
                "correct_answer": f"{w['correct_answer']}) {options.get(w['correct_answer'], w['correct_answer'])}"
            })
        return jsonify({
            "status": "success",
            "result": {
                "id": result["id"],
                "student_name": f"{result['first_name']} {result['last_name'] or ''}".strip(),
                "exam_title": result["exam_title_snapshot"] or "Deleted Exam",
                "score": result["score"],
                "total_questions": result["total_questions"],
                "completed_at": result["completed_at"],
                "exam_type": "mcq",
                "wrong_answers": wrong_list
            }
        })
    finally:
        connection.close()


# ============================================================
# CREATE EXAM (auto-detect MCQ vs Word Bank)
# ============================================================

@app.route("/api/teacher/exams_with_questions", methods=["POST"])
def teacher_create_exam_with_questions():
    """
    Accepts two formats:

      MCQ:        { title, category, time_limit, questions: [ {question_text, option_a..d, correct_answer}, ... ] }

      Word Bank:  { title, category, time_limit, word_bank_question: { instruction, word_bank, questions, extra_word } }

    The presence of 'word_bank_question' determines the exam type.
    Otherwise it defaults to MCQ.
    """
    auth_result = get_authenticated_user()
    if not auth_result["valid"]:
        return jsonify({"status": "error", "message": auth_result["message"]}), 401
    telegram_user = auth_result["user"]
    if not is_teacher(telegram_user["id"]):
        return jsonify({"status": "error", "message": "Access denied."}), 403
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "Request body is missing."}), 400

    title = data.get("title", "").strip()
    category = data.get("category", "Uncategorized").strip()
    time_limit = data.get("time_limit")
    if not title or not time_limit:
        return jsonify({"status": "error", "message": "title and time_limit are required."}), 400

    # --------------------------------------------------------
    # Word Bank path
    # --------------------------------------------------------
    word_bank_payload = data.get("word_bank_question")
    if word_bank_payload is not None:
        valid, err = validate_word_bank_data(word_bank_payload)
        if not valid:
            return jsonify({"status": "error", "message": err}), 400

        student_data = build_word_bank_student_data(word_bank_payload)
        answer_key = build_word_bank_answer_key(word_bank_payload)

        connection = get_database_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                "INSERT INTO exams (title, time_limit, category, exam_type) VALUES (?, ?, ?, ?)",
                (title, time_limit, category, "word_bank")
            )
            exam_id = cursor.lastrowid
            cursor.execute("""
                INSERT INTO word_bank_questions (exam_id, question_order, student_data_json, answer_key_json)
                VALUES (?, ?, ?, ?)
            """, (
                exam_id,
                1,
                json.dumps(student_data),
                json.dumps(answer_key)
            ))
            connection.commit()
            return jsonify({
                "status": "success",
                "message": "Word Bank exam created successfully.",
                "exam_id": exam_id,
                "exam_type": "word_bank",
                "total_questions": 1
            })
        except Exception as error:
            connection.rollback()
            print("WORD BANK CREATE ERROR:", error)
            return jsonify({"status": "error", "message": "An internal server error occurred."}), 500
        finally:
            connection.close()

    # --------------------------------------------------------
    # MCQ path (existing behavior)
    # --------------------------------------------------------
    questions_data = data.get("questions", [])
    if not questions_data:
        return jsonify({"status": "error", "message": "questions are required."}), 400

    connection = get_database_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("INSERT INTO exams (title, time_limit, category, exam_type) VALUES (?, ?, ?, ?)", (title, time_limit, category, "mcq"))
        exam_id = cursor.lastrowid
        question_ids = []
        for q in questions_data:
            question_text = q.get("question_text", "").strip()
            option_a = q.get("option_a", "").strip()
            option_b = q.get("option_b", "").strip()
            option_c = q.get("option_c", "").strip()
            option_d = q.get("option_d", "").strip()
            correct_answer = q.get("correct_answer", "").strip().upper()
            if not question_text or not correct_answer or correct_answer not in ["A", "B", "C", "D"]:
                raise ValueError(f"Invalid question data: {question_text[:50]}...")
            if correct_answer == "A" and not option_a:
                raise ValueError("Correct answer is A but option_a is empty.")
            if correct_answer == "B" and not option_b:
                raise ValueError("Correct answer is B but option_b is empty.")
            if correct_answer == "C" and not option_c:
                raise ValueError("Correct answer is C but option_c is empty.")
            if correct_answer == "D" and not option_d:
                raise ValueError("Correct answer is D but option_d is empty.")
            cursor.execute("INSERT INTO questions (question_text, option_a, option_b, option_c, option_d, correct_answer) VALUES (?, ?, ?, ?, ?, ?)", (question_text, option_a, option_b, option_c, option_d, correct_answer))
            question_id = cursor.lastrowid
            question_ids.append(question_id)
        for order, qid in enumerate(question_ids, start=1):
            cursor.execute("INSERT INTO exam_questions (exam_id, question_id, question_order) VALUES (?, ?, ?)", (exam_id, qid, order))
        connection.commit()
        return jsonify({"status": "success", "message": "Exam created successfully.", "exam_id": exam_id, "exam_type": "mcq", "total_questions": len(question_ids)})
    except ValueError as error:
        connection.rollback()
        return jsonify({"status": "error", "message": str(error)}), 400
    except Exception as error:
        connection.rollback()
        return jsonify({"status": "error", "message": "An internal server error occurred."}), 500
    finally:
        connection.close()


# ============================================================
# CLASS SCHEDULE (student-based)
# ============================================================

@app.route("/api/teacher/schedule", methods=["GET"])
def teacher_get_schedule():
    auth_result = get_authenticated_user()
    if not auth_result["valid"]:
        return jsonify({"status": "error", "message": auth_result["message"]}), 401
    telegram_user = auth_result["user"]
    if not is_teacher(telegram_user["id"]):
        return jsonify({"status": "error", "message": "Access denied."}), 403
    connection = get_database_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("""
            SELECT
                cs.id,
                cs.student_id,
                cs.day_of_week,
                cs.start_time,
                cs.end_time,
                cs.notes,
                cs.created_at,
                s.first_name,
                s.last_name,
                s.color AS student_color
            FROM class_schedule cs
            JOIN students s ON s.id = cs.student_id
            ORDER BY
                CASE cs.day_of_week
                    WHEN 'Monday' THEN 1
                    WHEN 'Tuesday' THEN 2
                    WHEN 'Wednesday' THEN 3
                    WHEN 'Thursday' THEN 4
                    WHEN 'Friday' THEN 5
                    WHEN 'Saturday' THEN 6
                    WHEN 'Sunday' THEN 7
                END,
                cs.start_time ASC
        """)
        rows = cursor.fetchall()
        schedule_list = []
        for r in rows:
            full_name = f"{r['first_name'] or ''} {r['last_name'] or ''}".strip()
            schedule_list.append({
                "id": r["id"],
                "student_id": r["student_id"],
                "student_name": full_name,
                "student_color": r["student_color"] or "#2563eb",
                "day_of_week": r["day_of_week"],
                "start_time": r["start_time"],
                "end_time": r["end_time"],
                "notes": r["notes"],
                "created_at": r["created_at"]
            })
        return jsonify({"status": "success", "schedule": schedule_list, "total": len(schedule_list)})
    finally:
        connection.close()


@app.route("/api/teacher/schedule", methods=["POST"])
def teacher_add_schedule():
    auth_result = get_authenticated_user()
    if not auth_result["valid"]:
        return jsonify({"status": "error", "message": auth_result["message"]}), 401
    telegram_user = auth_result["user"]
    if not is_teacher(telegram_user["id"]):
        return jsonify({"status": "error", "message": "Access denied."}), 403
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "Invalid request."}), 400
    student_id = data.get("student_id")
    day_of_week = data.get("day_of_week", "").strip()
    start_time = data.get("start_time", "").strip()
    end_time = data.get("end_time", "").strip()
    notes = data.get("notes", "").strip()
    if not student_id or not day_of_week or not start_time or not end_time:
        return jsonify({"status": "error", "message": "All required fields must be filled."}), 400
    valid_days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    if day_of_week not in valid_days:
        return jsonify({"status": "error", "message": "Invalid day of week."}), 400
    connection = get_database_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("SELECT id FROM students WHERE id = ?", (student_id,))
        if not cursor.fetchone():
            return jsonify({"status": "error", "message": "Student not found."}), 404
        cursor.execute("""
            INSERT INTO class_schedule (student_id, day_of_week, start_time, end_time, notes)
            VALUES (?, ?, ?, ?, ?)
        """, (student_id, day_of_week, start_time, end_time, notes))
        connection.commit()
        return jsonify({"status": "success", "message": "Session added successfully.", "id": cursor.lastrowid})
    except Exception as error:
        connection.rollback()
        return jsonify({"status": "error", "message": str(error)}), 500
    finally:
        connection.close()


@app.route("/api/teacher/schedule/<int:schedule_id>", methods=["PUT"])
def teacher_update_schedule(schedule_id):
    auth_result = get_authenticated_user()
    if not auth_result["valid"]:
        return jsonify({"status": "error", "message": auth_result["message"]}), 401
    telegram_user = auth_result["user"]
    if not is_teacher(telegram_user["id"]):
        return jsonify({"status": "error", "message": "Access denied."}), 403
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "Invalid request."}), 400
    student_id = data.get("student_id")
    day_of_week = data.get("day_of_week", "").strip()
    start_time = data.get("start_time", "").strip()
    end_time = data.get("end_time", "").strip()
    notes = data.get("notes", "").strip()
    if not student_id or not day_of_week or not start_time or not end_time:
        return jsonify({"status": "error", "message": "All required fields must be filled."}), 400
    connection = get_database_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("""
            UPDATE class_schedule
            SET student_id = ?, day_of_week = ?, start_time = ?, end_time = ?, notes = ?
            WHERE id = ?
        """, (student_id, day_of_week, start_time, end_time, notes, schedule_id))
        connection.commit()
        if cursor.rowcount == 0:
            return jsonify({"status": "error", "message": "Session not found."}), 404
        return jsonify({"status": "success", "message": "Session updated successfully."})
    except Exception as error:
        connection.rollback()
        return jsonify({"status": "error", "message": str(error)}), 500
    finally:
        connection.close()


@app.route("/api/teacher/schedule/<int:schedule_id>", methods=["DELETE"])
def teacher_delete_schedule(schedule_id):
    auth_result = get_authenticated_user()
    if not auth_result["valid"]:
        return jsonify({"status": "error", "message": auth_result["message"]}), 401
    telegram_user = auth_result["user"]
    if not is_teacher(telegram_user["id"]):
        return jsonify({"status": "error", "message": "Access denied."}), 403
    connection = get_database_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("DELETE FROM class_schedule WHERE id = ?", (schedule_id,))
        connection.commit()
        if cursor.rowcount == 0:
            return jsonify({"status": "error", "message": "Session not found."}), 404
        return jsonify({"status": "success", "message": "Session deleted successfully."})
    except Exception as error:
        connection.rollback()
        return jsonify({"status": "error", "message": str(error)}), 500
    finally:
        connection.close()


if __name__ == "__main__":
    print()
    print("========================================")
    print("        YEnglish Exams")
    print("========================================")
    print()
    print("Database:", DATABASE_PATH)
    print()
    print("Telegram authentication:", "CONFIGURED" if TELEGRAM_BOT_TOKEN else "NOT CONFIGURED")
    print()
    print("Teacher notifications:", "CONFIGURED" if (TELEGRAM_BOT_TOKEN and TEACHER_TELEGRAM_ID) else "NOT CONFIGURED")
    print()
    print("Mini App:", "http://127.0.0.1:5000/")
    print()
    print("API:", "http://127.0.0.1:5000/api")
    print()
    print("========================================")
    print()
    app.run(host="127.0.0.1", port=5000, debug=False)