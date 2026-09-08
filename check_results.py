import sqlite3

connection = sqlite3.connect("exam.db")

cursor = connection.cursor()

columns = cursor.execute(
    "PRAGMA table_info(results)"
).fetchall()

print()
print("RESULTS TABLE")
print("=" * 60)

for column in columns:
    print(column)

print("=" * 60)

connection.close()