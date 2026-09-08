import re


# ============================================================
# Y English Exams - Question Parser
# ============================================================
# وظیفه این فایل:
#
# دریافت متن خامی که از AI کپی شده
#        ↓
# تشخیص سؤال‌ها
#        ↓
# استخراج Question / A / B / C / D / Answer
#        ↓
# برگرداندن یک لیست آماده برای ذخیره در دیتابیس
#
# این بخش عمداً از Database جدا شده است.
# دلیل:
# Parser فقط مسئول "فهمیدن متن" است.
# Database فقط مسئول "ذخیره کردن اطلاعات" خواهد بود.
#
# این جداسازی باعث می‌شود بعداً بتوانیم Parser را تغییر دهیم
# بدون اینکه ساختار دیتابیس یا Mini App را تغییر بدهیم.
# ============================================================


def parse_questions(text):
    """
    متن خروجی AI را دریافت می‌کند و سؤال‌ها را استخراج می‌کند.

    خروجی:
        [
            {
                "question_text": "...",
                "option_a": "...",
                "option_b": "...",
                "option_c": "...",
                "option_d": "...",
                "correct_answer": "B"
            }
        ]
    """

    # یکسان‌سازی پایان خطوط
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()

    # پیدا کردن هر بلوک سؤال
    blocks = re.split(
        r"\[QUESTION\]",
        text,
        flags=re.IGNORECASE
    )

    questions = []
    errors = []

    for number, block in enumerate(blocks[1:], start=1):

        block = block.strip()

        try:
            question_match = re.search(
                r"^(.*?)(?=\n\s*\[A\])",
                block,
                flags=re.IGNORECASE | re.DOTALL
            )

            option_a_match = re.search(
                r"\[A\]\s*(.*?)(?=\n\s*\[B\])",
                block,
                flags=re.IGNORECASE | re.DOTALL
            )

            option_b_match = re.search(
                r"\[B\]\s*(.*?)(?=\n\s*\[C\])",
                block,
                flags=re.IGNORECASE | re.DOTALL
            )

            option_c_match = re.search(
                r"\[C\]\s*(.*?)(?=\n\s*\[D\])",
                block,
                flags=re.IGNORECASE | re.DOTALL
            )

            option_d_match = re.search(
                r"\[D\]\s*(.*?)(?=\n\s*\[ANSWER\])",
                block,
                flags=re.IGNORECASE | re.DOTALL
            )

            answer_match = re.search(
                r"\[ANSWER\]\s*([ABCD])",
                block,
                flags=re.IGNORECASE
            )

            # بررسی کامل بودن سؤال
            if not all([
                question_match,
                option_a_match,
                option_b_match,
                option_c_match,
                option_d_match,
                answer_match
            ]):
                raise ValueError("Question format is incomplete.")

            question = {
                "question_text": question_match.group(1).strip(),
                "option_a": option_a_match.group(1).strip(),
                "option_b": option_b_match.group(1).strip(),
                "option_c": option_c_match.group(1).strip(),
                "option_d": option_d_match.group(1).strip(),
                "correct_answer": answer_match.group(1).upper()
            }

            questions.append(question)

        except Exception as error:
            errors.append({
                "question_number": number,
                "error": str(error)
            })

    return questions, errors


# ============================================================
# Test
# ============================================================

if __name__ == "__main__":

    test_text = """
[QUESTION]
She _____ to school every day.
[A] go
[B] goes
[C] going
[D] gone
[ANSWER] B

[QUESTION]
I _____ my homework yesterday.
[A] do
[B] does
[C] did
[D] doing
[ANSWER] C

[QUESTION]
They _____ playing football now.
[A] is
[B] are
[C] was
[D] be
[ANSWER] B
"""

    questions, errors = parse_questions(test_text)

    print("=" * 60)
    print("PARSER TEST")
    print("=" * 60)

    print(f"Questions found : {len(questions)}")
    print(f"Errors found    : {len(errors)}")

    print()

    for number, question in enumerate(questions, start=1):

        print(f"Question {number}")
        print(f"Question : {question['question_text']}")
        print(f"A        : {question['option_a']}")
        print(f"B        : {question['option_b']}")
        print(f"C        : {question['option_c']}")
        print(f"D        : {question['option_d']}")
        print(f"Answer   : {question['correct_answer']}")
        print("-" * 60)

    if errors:
        print("ERRORS:")

        for error in errors:
            print(
                f"Question {error['question_number']}: "
                f"{error['error']}"
            )