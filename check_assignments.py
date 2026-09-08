import sqlite3


# ============================================================
# CHECK EXAM ASSIGNMENTS
# ============================================================
#
# This script ONLY reads the database.
# It does not modify anything.
# ============================================================


connection = sqlite3.connect(
    "exam.db"
)

cursor = connection.cursor()


print()
print("=" * 70)
print("EXAM ASSIGNMENTS TABLE STRUCTURE")
print("=" * 70)

columns = cursor.execute(
    "PRAGMA table_info(exam_assignments)"
).fetchall()

for column in columns:
    print(column)


print()
print("=" * 70)
print("CURRENT EXAM ASSIGNMENTS")
print("=" * 70)

rows = cursor.execute(
    """
    SELECT *
    FROM exam_assignments
    ORDER BY id
    """
).fetchall()

for row in rows:
    print(row)


print()
print("=" * 70)
print("EXAM 2 ASSIGNMENTS")
print("=" * 70)

rows = cursor.execute(
    """
    SELECT *
    FROM exam_assignments
    WHERE exam_id = 2
    """
).fetchall()

for row in rows:
    print(row)


print()
print("=" * 70)


connection.close()