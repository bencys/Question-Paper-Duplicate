"""Analyse one or more uploaded papers together, in the same shape the web page reads."""

from __future__ import annotations

import tempfile
from pathlib import Path

from extractor import read_paper
from matcher import find_matches
from spelling import check_text, corrected_word, paper_vocabulary, word_frequency

MAX_BYTES = 12 * 1024 * 1024


def analyse(papers_in: list[tuple[str, bytes]]) -> tuple[dict | None, list[str]]:
    """The result for all papers together, and any problems with individual files.

    The result is None when no paper has questions.
    """
    questions, papers, problems = [], [], []
    for name, data in papers_in:
        if not name.lower().endswith(".docx"):
            problems.append(f"{name}: please upload a Word document (.docx).")
            continue
        if not data:
            problems.append(f"{name} is empty.")
            continue
        if len(data) > MAX_BYTES:
            problems.append(f"{name} is too large (max 12 MB).")
            continue
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
            tmp.write(data)
            path = Path(tmp.name)
        try:
            found, removed = read_paper(path, source=name)
        except Exception:
            problems.append(f"{name} could not be read as a Word document.")
            continue
        finally:
            path.unlink(missing_ok=True)
        if not found:
            problems.append(f"No questions were found in {name}.")
            continue
        papers.append({"file": name, "questions": len(found), "removed": removed})
        questions += found

    if not questions:
        return None, problems

    vocab = paper_vocabulary([q.text for q in questions])
    spelling = {str(i): check_text(q.text, vocab) for i, q in enumerate(questions)}
    spelling = {k: v for k, v in spelling.items() if v}

    result = find_matches(questions, fix_word=corrected_word, word_freq=word_frequency)
    result["papers"] = papers
    result["spelling"] = spelling
    # Every question, so the user can pick any of them. The id is the position across all papers.
    result["questions"] = [
        {"id": i, "number": q.number, "source": q.source, "text": q.text, "options": q.options,
         "images": q.images, "option_images": q.option_images, "tables": q.tables}
        for i, q in enumerate(questions)
    ]
    for g in result["duplicate_groups"] + result["similar_groups"]:
        for item, idx in zip(g["questions"], g["member_index"]):
            item["id"] = idx
            item["misspelled"] = [s["word"] for s in spelling.get(str(idx), [])]
            item["options"] = questions[idx].options
    return result, problems
