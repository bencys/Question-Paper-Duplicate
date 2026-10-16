from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse

from extractor import extract_questions
from matcher import find_matches

app = FastAPI(title="Question Paper Duplicate Finder")
MAX_BYTES = 12 * 1024 * 1024

PAGE = Path(__file__).with_name("index.html").read_text(encoding="utf-8")


@app.get("/", response_class=HTMLResponse)
def home():
    return PAGE


@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    name = (file.filename or "").lower()
    if not name.endswith(".docx"):
        raise HTTPException(
            status_code=400,
            detail="Please upload a Word document (.docx). Older .doc files are not supported.",
        )
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=400, detail="File is too large (max 12 MB).")

    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)
    try:
        questions = extract_questions(tmp_path)
        if not questions:
            raise HTTPException(
                status_code=400,
                detail="No questions were found. Use numbered items such as 1.  2)  Q.3  Question 4.",
            )
        result = find_matches(questions)
        result["filename"] = file.filename
        return result
    finally:
        tmp_path.unlink(missing_ok=True)
