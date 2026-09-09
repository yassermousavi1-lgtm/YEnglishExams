from flask import Flask, jsonify, request, send_from_directory
import sqlite3
import os
import json
import time
import hmac
import hashlib
import requests
from urllib.parse import parse_qsl
from datetime import datetime


# ============================================================
# YEnglish Exams
# Flask Application
# ============================================================
#
# ARCHITECTURE
# ============================================================
#
#                         Telegram
#                            |
#                            v
#                     Public HTTPS URL
#                         (ngrok)
#                            |
#                            v
#                      Flask :5000
#                       /       \
#                      /         \
#                     v           v
#               Mini App         API
#             /mini_app/      /api/...
#                                 |
#                                 v
#                              exam.db
#
#
# ============================================================
# SECURITY FLOW
# ============================================================
#
# 1. Telegram signs Mini App initData.
# 2. Flask validates initData using the Bot Token.
# 3. Flask extracts Telegram User ID.
# 4. Telegram User ID is mapped to students.telegram_user_id.
# 5. Student.group_id is read from students.
# 6. exam_assignments is checked.
# 7. Only an assigned exam can be opened/submitted.
#
# correct_answer is NEVER sent to the Mini App.
# It is used only on the server during grading.
#
#
# ============================================================
# TEACHER ROLE DETECTION
# ============================================================
#
# If the Telegram User ID matches TEACHER_TELEGRAM_ID,
# the user has access to teacher-only endpoints.
#
# Teacher endpoints:
#     /api/teacher/students
#     /api/teacher/groups
#     /api/teacher/questions
#     /api/teacher/exams
#     /api/teacher/results
#     /api/teacher/assign
#     /api/teacher/send
#
# These endpoints are protected by the is_teacher() check.
# ============================================================


app = Flask(
    __name__,
    static_folder="mini_app",
    static_url_path=""
)


# ============================================================
# PATH CONFIGURATION
# ============================================================

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

DATABASE_PATH = os.path.join(
    BASE_DIR,
    "exam.db"
)


# ============================================================
# TELEGRAM CONFIGURATION
# ============================================================

TELEGRAM_BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN"
)

TEACHER_TELEGRAM_ID = os.environ.get(
    "TEACHER_TELEGRAM_ID"
)

INIT_DATA_MAX_AGE = 3600


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_database_connection():
    """
    Open a connection to exam.db.
    """

    connection = sqlite3.connect(
        DATABASE_PATH
    )

    connection.row_factory = sqlite3.Row

    return connection


# ============================================================
# TELEGRAM INIT DATA VALIDATION
# ============================================================

def validate_telegram_init_data(init_data):
    """
    Validate Telegram.WebApp.initData.

    Returns a dictionary describing whether the data is valid.
    """

    if not TELEGRAM_BOT_TOKEN:
        return {
            "valid": False,
            "message": "Telegram Bot Token is not configured."
        }

    if not init_data:
        return {
            "valid": False,
            "message": "Telegram initData is missing."
        }

    try:
        parsed_data = dict(
            parse_qsl(
                init_data,
                keep_blank_values=True
            )
        )
    except Exception:
        return {
            "valid": False,
            "message": "Telegram initData could not be parsed."
        }

    received_hash = parsed_data.pop(
        "hash",
        None
    )

    if not received_hash:
        return {
            "valid": False,
            "message": "Telegram authentication hash is missing."
        }

    data_check_string = "\n".join(
        f"{key}={value}"
        for key, value in sorted(
            parsed_data.items()
        )
    )

    secret_key = hmac.new(
        key=b"WebAppData",
        msg=TELEGRAM_BOT_TOKEN.encode("utf-8"),
        digestmod=hashlib.sha256
    ).digest()

    calculated_hash = hmac.new(
        key=secret_key,
        msg=data_check_string.encode("utf-8"),
        digestmod=hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(
        calculated_hash,
        received_hash
    ):
        return {
            "valid": False,
            "message": "Telegram authentication failed."
        }

    try:
        auth_date = int(
            parsed_data.get(
                "auth_date",
                "0"
            )
        )
    except ValueError:
        return {
            "valid": False,
            "message": "Invalid Telegram auth_date."
        }

    current_time = int(
        time.time()
    )

    if (
        auth_date <= 0
        or current_time - auth_date > INIT_DATA_MAX_AGE
    ):
        return {
            "valid": False,
            "message": "Telegram authentication data has expired."
        }

    user_json = parsed_data.get(
        "user"
    )

    if not user_json:
        return {
            "valid": False,
            "message": "Telegram user data is missing."
        }

    try:
        user_data = json.loads(
            user_json
        )
    except json.JSONDecodeError:
        return {
            "valid": False,
            "message": "Telegram user data is invalid."
        }

    telegram_user_id = user_data.get(
        "id"
    )

    if telegram_user_id is None:
        return {
            "valid": False,
            "message": "Telegram user ID is missing."
        }

    return {
        "valid": True,
        "user": user_data,
        "auth_date": auth_date
    }


# ============================================================
# AUTHENTICATED TELEGRAM USER
# ============================================================

def get_authenticated_user():
    """
    Read Telegram initData from the request header and validate it.
    """

    init_data = request.headers.get(
        "X-Telegram-Init-Data"
    )

    return validate_telegram_init_data(
        init_data
    )


# ============================================================
# IS TEACHER
# ============================================================

def is_teacher(telegram_user_id):
    """
    Check if the Telegram user is the teacher.
    """
    if not TEACHER_TELEGRAM_ID:
        return False

    return str(telegram_user_id) == str(TEACHER_TELEGRAM_ID)


# ============================================================
# FIND STUDENT
# ============================================================

def find_student_by_telegram_id(
    telegram_user_id,
    connection
):
    """
    Find the application student linked to a validated
    Telegram user ID.
    """

    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT
            id,
            telegram_user_id,
            first_name,
            last_name,
            username,
            group_id
        FROM students
        WHERE telegram_user_id = ?
        """,
        (
            telegram_user_id,
        )
    )

    return cursor.fetchone()


# ============================================================
# CHECK EXAM ACCESS
# ============================================================

def check_exam_access(
    student_id,
    group_id,
    exam_id,
    connection
):
    """
    Check whether the student's group is assigned the exam.
    """

    if group_id is None:
        return False

    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT
            id
        FROM exam_assignments
        WHERE exam_id = ?
          AND group_id = ?
        LIMIT 1
        """,
        (
            exam_id,
            group_id
        )
    )

    assignment = cursor.fetchone()

    return assignment is not None


# ============================================================
# SEND RESULT TO TEACHER
# ============================================================

def send_result_to_teacher(
    student,
    exam,
    score,
    total_questions,
    completed_at
):
    """
    Send a private Telegram notification to the teacher.

    This function is deliberately isolated from grading and
    database logic.

    Important design rule:
    notification failure must NEVER invalidate a successfully
    saved exam result.
    """

    if not TELEGRAM_BOT_TOKEN:
        print(
            "Teacher notification skipped: "
            "TELEGRAM_BOT_TOKEN is not configured."
        )
        return False

    if not TEACHER_TELEGRAM_ID:
        print(
            "Teacher notification skipped: "
            "TEACHER_TELEGRAM_ID is not configured."
        )
        return False

    # --------------------------------------------------------
    # Student name
    # --------------------------------------------------------

    first_name = (
        student["first_name"]
        or ""
    ).strip()

    last_name = (
        student["last_name"]
        or ""
    ).strip()

    username = (
        student["username"]
        or ""
    ).strip()

    full_name = " ".join(
        part
        for part in [first_name, last_name]
        if part
    )

    if not full_name:
        full_name = "Unknown student"

    if username:
        student_display = (
            f"{full_name} (@{username})"
        )
    else:
        student_display = full_name


    # --------------------------------------------------------
    # Percentage
    # --------------------------------------------------------

    percentage = (
        round(
            (
                score /
                total_questions
            ) * 100
        )
        if total_questions > 0
        else 0
    )


    # --------------------------------------------------------
    # Notification message
    # --------------------------------------------------------

    message = (
        "📝 <b>Exam Completed</b>\n\n"
        f"<b>Student:</b> {student_display}\n"
        f"<b>Exam:</b> {exam['title']}\n"
        f"<b>Score:</b> {score}/{total_questions}\n"
        f"<b>Percentage:</b> {percentage}%\n"
        f"<b>Completed:</b> {completed_at}"
    )


    # --------------------------------------------------------
    # Telegram Bot API
    # --------------------------------------------------------

    telegram_url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TEACHER_TELEGRAM_ID,
        "text": message,
        "parse_mode": "HTML"
    }


    try:

        response = requests.post(
            telegram_url,
            json=payload,
            timeout=10
        )

        response_data = response.json()


        if not response.ok or not response_data.get("ok"):

            print(
                "Teacher notification failed:",
                response_data
            )

            return False


        print(
            "Teacher notification sent successfully."
        )

        return True


    except Exception as error:

        print(
            "Teacher notification error:",
            error
        )

        return False


# ============================================================
# MINI APP
# ============================================================

@app.route("/")
def mini_app():
    """
    Serve the Telegram Mini App.
    """

    return send_from_directory(
        app.static_folder,
        "index.html"
    )


# ============================================================
# API HEALTH CHECK
# ============================================================

@app.route("/api")
def api_home():

    return jsonify({
        "status": "ok",
        "message": "YEnglish Exams API is running"
    })


# ============================================================
# CURRENT USER (با پشتیبانی از نقش معلم)
# ============================================================

@app.route("/api/me")
def get_current_user():
    """
    Validate Telegram identity and return the linked student.
    Also detects if the user is the teacher.
    """

    auth_result = get_authenticated_user()

    if not auth_result["valid"]:
        return jsonify({
            "status": "error",
            "message": auth_result["message"]
        }), 401

    telegram_user = auth_result["user"]

    # تشخیص معلم
    teacher = is_teacher(telegram_user["id"])

    connection = get_database_connection()

    try:

        student = find_student_by_telegram_id(
            telegram_user["id"],
            connection
        )

        # اگر معلم است و دانشجو ثبت نشده، باز هم اجازه ورود دارد
        if student is None and not teacher:
            return jsonify({
                "status": "error",
                "message":
                    "Your Telegram account is not registered as a student."
            }), 403

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
                "group_id": student["group_id"]
            }
        else:
            response["student"] = None

        return jsonify(response)

    finally:

        connection.close()


# ============================================================
# GET EXAM
# ============================================================

@app.route(
    "/api/exam/<int:exam_id>"
)
def get_exam(exam_id):

    auth_result = get_authenticated_user()

    if not auth_result["valid"]:

        return jsonify({
            "status": "error",
            "message":
                auth_result["message"]
        }), 401

    telegram_user = auth_result["user"]

    connection = get_database_connection()

    try:

        student = find_student_by_telegram_id(
            telegram_user["id"],
            connection
        )

        if student is None:

            return jsonify({
                "status": "error",
                "message":
                    "Student account is not registered."
            }), 403

        if not check_exam_access(
            student["id"],
            student["group_id"],
            exam_id,
            connection
        ):

            return jsonify({
                "status": "error",
                "message":
                    "You do not have access to this exam."
            }), 403

        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                id,
                title,
                time_limit
            FROM exams
            WHERE id = ?
            """,
            (
                exam_id,
            )
        )

        exam = cursor.fetchone()

        if exam is None:

            return jsonify({
                "status": "error",
                "message":
                    "Exam not found."
            }), 404

        return jsonify({

            "status":
                "success",

            "exam": {

                "id":
                    exam["id"],

                "title":
                    exam["title"],

                "time_limit":
                    exam["time_limit"]
            }
        })

    finally:

        connection.close()


# ============================================================
# GET EXAM QUESTIONS
# ============================================================

@app.route(
    "/api/exam/<int:exam_id>/questions"
)
def get_exam_questions(exam_id):
    """
    Return exam questions to an authorized student.

    correct_answer is never returned.
    """

    auth_result = get_authenticated_user()

    if not auth_result["valid"]:

        return jsonify({
            "status": "error",
            "message":
                auth_result["message"]
        }), 401

    telegram_user = auth_result["user"]

    connection = get_database_connection()

    try:

        student = find_student_by_telegram_id(
            telegram_user["id"],
            connection
        )

        if student is None:

            return jsonify({
                "status": "error",
                "message":
                    "Student account is not registered."
            }), 403

        if not check_exam_access(
            student["id"],
            student["group_id"],
            exam_id,
            connection
        ):

            return jsonify({
                "status": "error",
                "message":
                    "You do not have access to this exam."
            }), 403

        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                id,
                title,
                time_limit
            FROM exams
            WHERE id = ?
            """,
            (
                exam_id,
            )
        )

        exam = cursor.fetchone()

        if exam is None:

            return jsonify({
                "status": "error",
                "message":
                    "Exam not found."
            }), 404

        cursor.execute(
            """
            SELECT
                q.id,
                q.question_text,
                q.option_a,
                q.option_b,
                q.option_c,
                q.option_d,
                eq.question_order

            FROM exam_questions AS eq

            INNER JOIN questions AS q
                ON q.id = eq.question_id

            WHERE eq.exam_id = ?

            ORDER BY eq.question_order ASC
            """,
            (
                exam_id,
            )
        )

        questions = cursor.fetchall()

        question_list = []

        for question in questions:

            question_list.append({

                "id":
                    question["id"],

                "question_text":
                    question["question_text"],

                "options": {

                    "A":
                        question["option_a"],

                    "B":
                        question["option_b"],

                    "C":
                        question["option_c"],

                    "D":
                        question["option_d"]
                },

                "question_order":
                    question["question_order"]
            })

        return jsonify({

            "status":
                "success",

            "exam": {

                "id":
                    exam["id"],

                "title":
                    exam["title"],

                "time_limit":
                    exam["time_limit"]
            },

            "questions":
                question_list,

            "total_questions":
                len(question_list)
        })

    finally:

        connection.close()


# ============================================================
# SUBMIT EXAM
# ============================================================

@app.route(
    "/api/exam/submit",
    methods=["POST"]
)
def submit_exam():
    """
    Authenticate the Telegram user, verify exam access,
    grade answers on the server, save the result, then
    notify the teacher.
    """

    # ========================================================
    # AUTHENTICATE TELEGRAM USER
    # ========================================================

    auth_result = get_authenticated_user()

    if not auth_result["valid"]:

        return jsonify({
            "status": "error",
            "message":
                auth_result["message"]
        }), 401

    telegram_user = auth_result["user"]


    # ========================================================
    # READ REQUEST BODY
    # ========================================================

    data = request.get_json(
        silent=True
    )

    if not isinstance(
        data,
        dict
    ):

        return jsonify({
            "status": "error",
            "message":
                "Request body is missing or invalid."
        }), 400


    exam_id = data.get(
        "exam_id"
    )

    answers = data.get(
        "answers"
    )

    started_at = data.get(
        "started_at"
    )


    # ========================================================
    # VALIDATION
    # ========================================================

    if exam_id is None:

        return jsonify({
            "status": "error",
            "message":
                "exam_id is required."
        }), 400


    if not isinstance(
        answers,
        dict
    ):

        return jsonify({
            "status": "error",
            "message":
                "answers must be an object."
        }), 400


    # ========================================================
    # DATABASE
    # ========================================================

    connection = get_database_connection()

    cursor = connection.cursor()


    try:

        # ====================================================
        # FIND STUDENT
        # ====================================================

        student = find_student_by_telegram_id(
            telegram_user["id"],
            connection
        )

        if student is None:

            return jsonify({
                "status": "error",
                "message":
                    "Student account is not registered."
            }), 403


        # ====================================================
        # CHECK EXAM ACCESS
        # ====================================================

        if not check_exam_access(
            student["id"],
            student["group_id"],
            exam_id,
            connection
        ):

            return jsonify({
                "status": "error",
                "message":
                    "You do not have access to this exam."
            }), 403


        # ====================================================
        # VERIFY EXAM
        # ====================================================

        cursor.execute(
            """
            SELECT
                id,
                title
            FROM exams
            WHERE id = ?
            """,
            (
                exam_id,
            )
        )

        exam = cursor.fetchone()


        if exam is None:

            return jsonify({
                "status": "error",
                "message":
                    "Exam not found."
            }), 404


        # ====================================================
        # LOAD ANSWER KEY
        # ====================================================

        cursor.execute(
            """
            SELECT
                q.id,
                q.correct_answer,
                eq.question_order

            FROM exam_questions AS eq

            INNER JOIN questions AS q
                ON q.id = eq.question_id

            WHERE eq.exam_id = ?

            ORDER BY eq.question_order ASC
            """,
            (
                exam_id,
            )
        )

        questions = cursor.fetchall()

        total_questions = len(
            questions
        )


        if total_questions == 0:

            return jsonify({
                "status": "error",
                "message":
                    "This exam has no questions."
            }), 400


        # ====================================================
        # SERVER-SIDE GRADING
        # ====================================================

        score = 0


        for question in questions:

            question_id = str(
                question["id"]
            )

            correct_answer = str(
                question["correct_answer"]
            ).strip().upper()

            submitted_answer = answers.get(
                question_id
            )


            if submitted_answer is None:
                continue


            submitted_answer = str(
                submitted_answer
            ).strip().upper()


            if submitted_answer == correct_answer:

                score += 1


        # ====================================================
        # TIMESTAMPS
        # ====================================================

        completed_at = datetime.now().isoformat(
            timespec="seconds"
        )


        if not started_at:

            started_at = completed_at


        # ====================================================
        # SAVE RESULT
        # ====================================================

        cursor.execute(
            """
            INSERT INTO results (
                student_id,
                exam_id,
                score,
                total_questions,
                started_at,
                completed_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                student["id"],
                exam_id,
                score,
                total_questions,
                started_at,
                completed_at
            )
        )


        result_id = cursor.lastrowid


        # ====================================================
        # COMMIT RESULT FIRST
        # ====================================================
        #
        # The database result becomes authoritative BEFORE
        # sending the teacher notification.
        #
        # If Telegram is temporarily unavailable, the score
        # remains safely stored in exam.db.
        # ====================================================

        connection.commit()


        # ====================================================
        # NOTIFY TEACHER
        # ====================================================

        notification_sent = send_result_to_teacher(
            student=student,
            exam=exam,
            score=score,
            total_questions=total_questions,
            completed_at=completed_at
        )


        # ====================================================
        # RETURN RESULT
        # ====================================================

        return jsonify({

            "status":
                "success",

            "message":
                "Exam submitted successfully.",

            "result": {

                "id":
                    result_id,

                "exam_id":
                    exam_id,

                "student_id":
                    student["id"],

                "score":
                    score,

                "total_questions":
                    total_questions,

                "completed_at":
                    completed_at,

                "teacher_notified":
                    notification_sent
            }
        })


    except Exception as error:

        connection.rollback()

        print(
            "SUBMIT EXAM ERROR:",
            error
        )


        return jsonify({

            "status":
                "error",

            "message":
                "An internal server error occurred."
        }), 500


    finally:

        connection.close()


# ============================================================
# ============================================================
# TEACHER ENDPOINTS
# ============================================================
# ============================================================


# ============================================================
# TEACHER: GET ALL STUDENTS
# ============================================================

@app.route("/api/teacher/students")
def teacher_get_students():
    """
    Get all students with their group information.
    Teacher only.
    """

    auth_result = get_authenticated_user()

    if not auth_result["valid"]:
        return jsonify({
            "status": "error",
            "message": auth_result["message"]
        }), 401

    telegram_user = auth_result["user"]

    if not is_teacher(telegram_user["id"]):
        return jsonify({
            "status": "error",
            "message": "Access denied. Teacher only."
        }), 403

    connection = get_database_connection()

    try:
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                s.id,
                s.telegram_user_id,
                s.first_name,
                s.last_name,
                s.username,
                s.group_id,
                g.name AS group_name,
                g.telegram_group_id
            FROM students s
            JOIN groups g ON g.id = s.group_id
            ORDER BY s.id
            """
        )

        students = cursor.fetchall()

        student_list = []

        for student in students:
            student_list.append({
                "id": student["id"],
                "telegram_user_id": student["telegram_user_id"],
                "first_name": student["first_name"],
                "last_name": student["last_name"],
                "username": student["username"],
                "group_id": student["group_id"],
                "group_name": student["group_name"],
                "telegram_group_id": student["telegram_group_id"]
            })

        return jsonify({
            "status": "success",
            "students": student_list,
            "total": len(student_list)
        })

    finally:
        connection.close()


# ============================================================
# TEACHER: GET ALL GROUPS
# ============================================================

@app.route("/api/teacher/groups")
def teacher_get_groups():
    """
    Get all groups.
    Teacher only.
    """

    auth_result = get_authenticated_user()

    if not auth_result["valid"]:
        return jsonify({
            "status": "error",
            "message": auth_result["message"]
        }), 401

    telegram_user = auth_result["user"]

    if not is_teacher(telegram_user["id"]):
        return jsonify({
            "status": "error",
            "message": "Access denied. Teacher only."
        }), 403

    connection = get_database_connection()

    try:
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                id,
                telegram_group_id,
                name,
                created_at
            FROM groups
            ORDER BY name
            """
        )

        groups = cursor.fetchall()

        group_list = []

        for group in groups:
            group_list.append({
                "id": group["id"],
                "telegram_group_id": group["telegram_group_id"],
                "name": group["name"],
                "created_at": group["created_at"]
            })

        return jsonify({
            "status": "success",
            "groups": group_list,
            "total": len(group_list)
        })

    finally:
        connection.close()


# ============================================================
# TEACHER: GET ALL QUESTIONS
# ============================================================

@app.route("/api/teacher/questions")
def teacher_get_questions():
    """
    Get all questions from the question bank.
    Teacher only.
    """

    auth_result = get_authenticated_user()

    if not auth_result["valid"]:
        return jsonify({
            "status": "error",
            "message": auth_result["message"]
        }), 401

    telegram_user = auth_result["user"]

    if not is_teacher(telegram_user["id"]):
        return jsonify({
            "status": "error",
            "message": "Access denied. Teacher only."
        }), 403

    connection = get_database_connection()

    try:
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                id,
                question_text,
                option_a,
                option_b,
                option_c,
                option_d,
                correct_answer,
                created_at
            FROM questions
            ORDER BY id
            """
        )

        questions = cursor.fetchall()

        question_list = []

        for question in questions:
            question_list.append({
                "id": question["id"],
                "question_text": question["question_text"],
                "option_a": question["option_a"],
                "option_b": question["option_b"],
                "option_c": question["option_c"],
                "option_d": question["option_d"],
                "correct_answer": question["correct_answer"],
                "created_at": question["created_at"]
            })

        return jsonify({
            "status": "success",
            "questions": question_list,
            "total": len(question_list)
        })

    finally:
        connection.close()


# ============================================================
# TEACHER: GET ALL EXAMS
# ============================================================

@app.route("/api/teacher/exams")
def teacher_get_exams():
    """
    Get all exams.
    Teacher only.
    """

    auth_result = get_authenticated_user()

    if not auth_result["valid"]:
        return jsonify({
            "status": "error",
            "message": auth_result["message"]
        }), 401

    telegram_user = auth_result["user"]

    if not is_teacher(telegram_user["id"]):
        return jsonify({
            "status": "error",
            "message": "Access denied. Teacher only."
        }), 403

    connection = get_database_connection()

    try:
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                e.id,
                e.title,
                e.time_limit,
                e.created_at,
                COUNT(eq.id) AS question_count
            FROM exams e
            LEFT JOIN exam_questions eq ON eq.exam_id = e.id
            GROUP BY e.id
            ORDER BY e.id
            """
        )

        exams = cursor.fetchall()

        exam_list = []

        for exam in exams:
            exam_list.append({
                "id": exam["id"],
                "title": exam["title"],
                "time_limit": exam["time_limit"],
                "question_count": exam["question_count"],
                "created_at": exam["created_at"]
            })

        return jsonify({
            "status": "success",
            "exams": exam_list,
            "total": len(exam_list)
        })

    finally:
        connection.close()


# ============================================================
# TEACHER: GET ASSIGNMENTS
# ============================================================

@app.route("/api/teacher/assignments")
def teacher_get_assignments():
    """
    Get all exam assignments.
    Teacher only.
    """

    auth_result = get_authenticated_user()

    if not auth_result["valid"]:
        return jsonify({
            "status": "error",
            "message": auth_result["message"]
        }), 401

    telegram_user = auth_result["user"]

    if not is_teacher(telegram_user["id"]):
        return jsonify({
            "status": "error",
            "message": "Access denied. Teacher only."
        }), 403

    connection = get_database_connection()

    try:
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                ea.id AS assignment_id,
                ea.assigned_at,
                e.id AS exam_id,
                e.title AS exam_title,
                g.id AS group_id,
                g.name AS group_name,
                g.telegram_group_id
            FROM exam_assignments ea
            JOIN exams e ON e.id = ea.exam_id
            JOIN groups g ON g.id = ea.group_id
            ORDER BY ea.id
            """
        )

        assignments = cursor.fetchall()

        assignment_list = []

        for assignment in assignments:
            assignment_list.append({
                "assignment_id": assignment["assignment_id"],
                "exam_id": assignment["exam_id"],
                "exam_title": assignment["exam_title"],
                "group_id": assignment["group_id"],
                "group_name": assignment["group_name"],
                "telegram_group_id": assignment["telegram_group_id"],
                "assigned_at": assignment["assigned_at"]
            })

        return jsonify({
            "status": "success",
            "assignments": assignment_list,
            "total": len(assignment_list)
        })

    finally:
        connection.close()


# ============================================================
# TEACHER: GET RESULTS
# ============================================================

@app.route("/api/teacher/results")
def teacher_get_results():
    """
    Get all exam results.
    Teacher only.
    """

    auth_result = get_authenticated_user()

    if not auth_result["valid"]:
        return jsonify({
            "status": "error",
            "message": auth_result["message"]
        }), 401

    telegram_user = auth_result["user"]

    if not is_teacher(telegram_user["id"]):
        return jsonify({
            "status": "error",
            "message": "Access denied. Teacher only."
        }), 403

    connection = get_database_connection()

    try:
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                r.id,
                r.score,
                r.total_questions,
                r.started_at,
                r.completed_at,
                s.first_name,
                s.last_name,
                s.username,
                s.telegram_user_id,
                e.title AS exam_title,
                e.id AS exam_id,
                g.name AS group_name
            FROM results r
            JOIN students s ON s.id = r.student_id
            JOIN exams e ON e.id = r.exam_id
            JOIN groups g ON g.id = s.group_id
            ORDER BY r.completed_at DESC
            """
        )

        results = cursor.fetchall()

        result_list = []

        for result in results:
            percentage = 0
            if result["total_questions"] > 0:
                percentage = round((result["score"] / result["total_questions"]) * 100)

            result_list.append({
                "id": result["id"],
                "student_name": f"{result['first_name']} {result['last_name'] or ''}".strip(),
                "student_username": result["username"],
                "telegram_user_id": result["telegram_user_id"],
                "exam_title": result["exam_title"],
                "exam_id": result["exam_id"],
                "score": result["score"],
                "total_questions": result["total_questions"],
                "percentage": percentage,
                "group_name": result["group_name"],
                "started_at": result["started_at"],
                "completed_at": result["completed_at"]
            })

        return jsonify({
            "status": "success",
            "results": result_list,
            "total": len(result_list)
        })

    finally:
        connection.close()


# ============================================================
# TEACHER: ADD STUDENT
# ============================================================

@app.route("/api/teacher/students", methods=["POST"])
def teacher_add_student():
    """
    Add a new student.
    Teacher only.
    """

    auth_result = get_authenticated_user()

    if not auth_result["valid"]:
        return jsonify({
            "status": "error",
            "message": auth_result["message"]
        }), 401

    telegram_user = auth_result["user"]

    if not is_teacher(telegram_user["id"]):
        return jsonify({
            "status": "error",
            "message": "Access denied. Teacher only."
        }), 403

    data = request.get_json(silent=True)

    if not data:
        return jsonify({
            "status": "error",
            "message": "Request body is missing or invalid."
        }), 400

    telegram_user_id = data.get("telegram_user_id")
    first_name = data.get("first_name", "").strip()
    last_name = data.get("last_name", "").strip()
    username = data.get("username", "").strip()
    group_id = data.get("group_id")

    if not telegram_user_id:
        return jsonify({
            "status": "error",
            "message": "telegram_user_id is required."
        }), 400

    if not first_name:
        return jsonify({
            "status": "error",
            "message": "first_name is required."
        }), 400

    if not group_id:
        return jsonify({
            "status": "error",
            "message": "group_id is required."
        }), 400

    connection = get_database_connection()

    try:
        cursor = connection.cursor()

        # بررسی وجود گروه
        cursor.execute(
            "SELECT id FROM groups WHERE id = ?",
            (group_id,)
        )

        if not cursor.fetchone():
            return jsonify({
                "status": "error",
                "message": "Group not found."
            }), 404

        # ثبت دانشجو
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
            (telegram_user_id, first_name, last_name, username, group_id)
        )

        connection.commit()

        student_id = cursor.lastrowid

        return jsonify({
            "status": "success",
            "message": "Student added successfully.",
            "student_id": student_id
        })

    except sqlite3.IntegrityError:
        return jsonify({
            "status": "error",
            "message": "This student is already registered."
        }), 400

    except Exception as error:
        connection.rollback()
        return jsonify({
            "status": "error",
            "message": str(error)
        }), 500

    finally:
        connection.close()


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    print()
    print("========================================")
    print("        YEnglish Exams")
    print("========================================")
    print()

    print("Database:")
    print(DATABASE_PATH)

    print()

    print("Telegram authentication:")
    print(
        "CONFIGURED"
        if TELEGRAM_BOT_TOKEN
        else
        "NOT CONFIGURED"
    )

    print()

    print("Teacher notifications:")
    print(
        "CONFIGURED"
        if (
            TELEGRAM_BOT_TOKEN
            and
            TEACHER_TELEGRAM_ID
        )
        else
        "NOT CONFIGURED"
    )

    print()

    print("Teacher ID:")
    print(TEACHER_TELEGRAM_ID or "NOT CONFIGURED")

    print()

    print("Mini App:")
    print("http://127.0.0.1:5000/")

    print()

    print("API:")
    print("http://127.0.0.1:5000/api")

    print()

    print("Current user:")
    print("http://127.0.0.1:5000/api/me")

    print()

    print("Submit endpoint:")
    print("http://127.0.0.1:5000/api/exam/submit")

    print()

    print("Teacher endpoints:")
    print("  /api/teacher/students")
    print("  /api/teacher/groups")
    print("  /api/teacher/questions")
    print("  /api/teacher/exams")
    print("  /api/teacher/assignments")
    print("  /api/teacher/results")

    print()
    print("========================================")
    print()


    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False
    )


# ============================================================
# TEACHER: CREATE EXAM WITH QUESTIONS (JSON)
# ============================================================

@app.route("/api/teacher/exams_with_questions", methods=["POST"])
def teacher_create_exam_with_questions():
    """
    Create a new exam and save all questions from JSON.
    Teacher only.
    """

    auth_result = get_authenticated_user()
    if not auth_result["valid"]:
        return jsonify({
            "status": "error",
            "message": auth_result["message"]
        }), 401

    telegram_user = auth_result["user"]
    if not is_teacher(telegram_user["id"]):
        return jsonify({
            "status": "error",
            "message": "Access denied. Teacher only."
        }), 403

    data = request.get_json(silent=True)
    if not data:
        return jsonify({
            "status": "error",
            "message": "Request body is missing or invalid."
        }), 400

    title = data.get("title", "").strip()
    time_limit = data.get("time_limit")
    questions_data = data.get("questions", [])

    if not title:
        return jsonify({
            "status": "error",
            "message": "title is required."
        }), 400

    if not time_limit or time_limit <= 0:
        return jsonify({
            "status": "error",
            "message": "time_limit must be a positive number."
        }), 400

    if not questions_data or not isinstance(questions_data, list):
        return jsonify({
            "status": "error",
            "message": "questions must be a non-empty array."
        }), 400

    connection = get_database_connection()
    cursor = connection.cursor()

    try:
        # 1. Create the exam
        cursor.execute(
            """
            INSERT INTO exams (title, time_limit)
            VALUES (?, ?)
            """,
            (title, time_limit)
        )
        exam_id = cursor.lastrowid

        # 2. Save each question and link to exam
        question_ids = []
        for q in questions_data:
            question_text = q.get("question_text", "").strip()
            option_a = q.get("option_a", "").strip()
            option_b = q.get("option_b", "").strip()
            option_c = q.get("option_c", "").strip()
            option_d = q.get("option_d", "").strip()
            correct_answer = q.get("correct_answer", "").strip().upper()

            if not all([question_text, option_a, option_b, option_c, option_d, correct_answer]):
                raise ValueError("Each question must have all fields: question_text, option_a, option_b, option_c, option_d, correct_answer")

            if correct_answer not in ["A", "B", "C", "D"]:
                raise ValueError(f"correct_answer must be A, B, C, or D. Got: {correct_answer}")

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
                (question_text, option_a, option_b, option_c, option_d, correct_answer)
            )
            question_id = cursor.lastrowid
            question_ids.append(question_id)

        # 3. Link questions to exam
        for order, qid in enumerate(question_ids, start=1):
            cursor.execute(
                """
                INSERT INTO exam_questions (exam_id, question_id, question_order)
                VALUES (?, ?, ?)
                """,
                (exam_id, qid, order)
            )

        connection.commit()

        return jsonify({
            "status": "success",
            "message": "Exam and questions created successfully.",
            "exam_id": exam_id,
            "total_questions": len(question_ids)
        })

    except ValueError as error:
        connection.rollback()
        return jsonify({
            "status": "error",
            "message": str(error)
        }), 400

    except Exception as error:
        connection.rollback()
        print("CREATE EXAM ERROR:", error)
        return jsonify({
            "status": "error",
            "message": "An internal server error occurred."
        }), 500

    finally:
        connection.close()