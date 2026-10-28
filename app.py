from __future__ import annotations

import tempfile
import threading
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from extractor import ExtractedQuestion, read_paper
from matcher import find_matches, meaning_model_available
from paper import build_paper
from spelling import check_text, corrected_word, paper_vocabulary, word_frequency

app = FastAPI(title="Question Paper Duplicate Finder")
MAX_BYTES = 12 * 1024 * 1024
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class PaperQuestion(BaseModel):
    text: str = Field(max_length=5000)
    options: list[str] = Field(default_factory=list, max_length=10)
    images: list[str] = Field(default_factory=list, max_length=20)
    option_images: list[list[str]] = Field(default_factory=list, max_length=10)
    tables: list[list[list[str]]] = Field(default_factory=list, max_length=10)


class PaperRequest(BaseModel):
    title: str = Field(default="New question paper", max_length=200)
    questions: list[PaperQuestion] = Field(min_length=1, max_length=500)

# Load the sentence-meaning model in the background so the first upload is not slow.
threading.Thread(target=meaning_model_available, daemon=True).start()


@app.get("/", response_class=HTMLResponse)
def home():
    # Read fresh every time so UI changes are visible without restart
    return Path(__file__).with_name("index.html").read_text(encoding="utf-8")


def _read_paper(data: bytes, name: str) -> tuple[list[ExtractedQuestion], list[str]]:
    """The questions of one uploaded paper, tagged with the paper's name."""
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)

    try:
        try:
            questions, removed = read_paper(tmp_path, source=name)
        except Exception:
            raise HTTPException(status_code=400, detail=f"{name} could not be read as a Word document.")
    finally:
        tmp_path.unlink(missing_ok=True)
    if not questions:
        raise HTTPException(
            status_code=400,
            detail=f"No questions were found in {name}. Use numbered items such as 1.  2)  Q.3  Question 4.",
        )
    return questions, removed


@app.post("/analyze")
async def analyze(files: list[UploadFile] = File(...)):
    """Analyse one or more papers together: questions are compared across all of them."""
    questions: list[ExtractedQuestion] = []
    papers: list[dict] = []
    for file in files:
        name = file.filename or "paper.docx"
        if not name.lower().endswith(".docx"):
            raise HTTPException(
                status_code=400,
                detail=f"{name}: please upload a Word document (.docx). Older .doc files: open in Word and Save As .docx.",
            )
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail=f"{name} is empty.")
        if len(data) > MAX_BYTES:
            raise HTTPException(status_code=400, detail=f"{name} is too large (max 12 MB).")
        paper, removed = _read_paper(data, name)
        papers.append({"file": name, "questions": len(paper), "removed": removed})
        questions += paper

    vocab = paper_vocabulary([q.text for q in questions])
    spelling = {str(i): check_text(q.text, vocab) for i, q in enumerate(questions)}
    spelling = {k: v for k, v in spelling.items() if v}

    result = find_matches(questions, fix_word=corrected_word, word_freq=word_frequency)
    result["papers"] = papers
    result["spelling"] = spelling
    # Every question, so the user can pick any of them, not only repeated ones. The id is the
    # question's position across all papers: numbers repeat between papers, ids never do.
    result["questions"] = [
        {"id": i, "number": q.number, "source": q.source, "text": q.text, "options": q.options,
         "images": q.images, "option_images": q.option_images, "tables": q.tables}
        for i, q in enumerate(questions)
    ]

    def misspelled(idx: int) -> list[str]:
        return [i["word"] for i in spelling.get(str(idx), [])]

    # MCQ choices are shown but never matched on.
    for g in result["duplicate_groups"] + result["similar_groups"]:
        for item, idx in zip(g["questions"], g["member_index"]):
            item["misspelled"] = misspelled(idx)
            item["options"] = questions[idx].options
    return result


@app.post("/paper")
def paper(req: PaperRequest):
    """Word document of the questions the user picked, in the order they are sent."""
    data = build_paper(req.title, [q.model_dump() for q in req.questions])
    return Response(
        content=data,
        media_type=DOCX_TYPE,
        headers={"Content-Disposition": 'attachment; filename="new_question_paper.docx"'},
    )
