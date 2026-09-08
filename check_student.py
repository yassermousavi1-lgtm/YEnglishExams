import sqlite3


connection = sqlite3.connect("exam.db")
cursor = connection.cursor()


print()
print("=" * 70)
print("CURRENT STUDENTS")
print("=" * 70)


rows = cursor.execute(
    """
    SELECT
        id,
        telegram_user_id,
        first_name,
        last_name,
        username,
        group_id
    FROM students
    ORDER BY id
    """
).fetchall()


for row in rows:
    print(row)


print()
print("=" * 70)
print("GROUPS")
print("=" * 70)


rows = cursor.execute(
    """
    SELECT
        id,
        telegram_group_id,
        name
    FROM groups
    ORDER BY id
    """
).fetchall()


for row in rows:
    print(row)


print()
print("=" * 70)


connection.close()