from database import get_connection


# ============================================================
# TEST ASSIGNMENT
# ============================================================
#
# For this test we assign:
#
# Exam:
#     ID = 2
#
# Group:
#     Telegram Group ID = -5496449839
#
# This file only creates the database relationship.
# It does NOT send anything to Telegram yet.
# ============================================================


EXAM_ID = 2

TELEGRAM_GROUP_ID = -5496449839


def assign_exam():

    connection = get_connection()
    cursor = connection.cursor()

    # --------------------------------------------------------
    # Find the internal database ID of the group
    # --------------------------------------------------------

    group = cursor.execute(
        """
        SELECT id, name
        FROM groups
        WHERE telegram_group_id = ?
        """,
        (TELEGRAM_GROUP_ID,)
    ).fetchone()

    if group is None:
        print("ERROR: Group not found.")
        connection.close()
        return

    # --------------------------------------------------------
    # Check that the exam exists
    # --------------------------------------------------------

    exam = cursor.execute(
        """
        SELECT id, title
        FROM exams
        WHERE id = ?
        """,
        (EXAM_ID,)
    ).fetchone()

    if exam is None:
        print("ERROR: Exam not found.")
        connection.close()
        return

    # --------------------------------------------------------
    # Create the assignment
    #
    # UNIQUE(exam_id, group_id) prevents duplicate assignment.
    # --------------------------------------------------------

    try:

        cursor.execute(
            """
            INSERT INTO exam_assignments
                (exam_id, group_id)
            VALUES
                (?, ?)
            """,
            (EXAM_ID, group["id"])
        )

        connection.commit()

        print("=" * 60)
        print("EXAM ASSIGNED SUCCESSFULLY")
        print("=" * 60)
        print(f"Exam ID       : {exam['id']}")
        print(f"Exam Title    : {exam['title']}")
        print(f"Group ID      : {group['id']}")
        print(f"Group Name    : {group['name']}")
        print(f"Telegram ID   : {TELEGRAM_GROUP_ID}")

    except Exception as error:

        print("=" * 60)
        print("ERROR ASSIGNING EXAM")
        print("=" * 60)
        print(error)

    finally:

        connection.close()


if __name__ == "__main__":
    assign_exam()