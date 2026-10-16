# Question Paper Duplicate Finder

Upload a Word question paper (`.docx`). The app extracts numbered questions and groups:

- **Repeated** questions (same wording, extra spaces, or spelling mistakes)
- **Similar** questions (same meaning, different wording)

Each group shows the question number and the numbers of matching questions.

## Run

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python make_sample.py
uvicorn app:app --reload --port 8000
```

Open http://127.0.0.1:8000 and upload `sample_question_paper.docx` or your own paper.

Numbered items such as `1.`, `2)`, `Q.3`, and `Question 4` are detected. Multiple-choice options (`a)`, `b)`) stay attached to the parent question.
