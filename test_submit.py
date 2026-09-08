import requests


# ============================================================
# TEST SERVER-SIDE GRADING
# ============================================================
#
# We intentionally submit:
#
# Question 1 -> B  ✅
# Question 3 -> A  ❌
# Question 4 -> B  ✅
#
# Expected score:
#
# 2 / 3
#
# This test verifies that Flask reads the correct answers
# from the database instead of trusting the submitted data.
# ============================================================


API_URL = "http://127.0.0.1:5000/api/exam/submit"


payload = {
    "exam_id": 2,

    # Temporary test student ID.
    # We will replace this with Telegram-based identification
    # later.
    "student_id": 1,

    "answers": {
        "1": "B",
        "3": "A",
        "4": "B"
    }
}


response = requests.post(
    API_URL,
    json=payload,
    timeout=10
)


print()
print("HTTP STATUS:")
print(response.status_code)

print()

print("SERVER RESPONSE:")
print(response.json())