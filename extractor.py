"""Extract numbered questions from a Word question paper."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

QUESTION_START = re.compile(
    r"""^\s*
        (?:
            (?:q(?:uest(?:ion)?)?)\s*[.\-:]?\s*
            | sec(?:tion)?\s*[A-Z]\s*[-:.]?\s*
        )?
        (?P<num>\d+[A-Za-z]? (?:\s*[.\-]\s*\d+[A-Za-z]?)?)
        \s*[.)\]:]\s*
        (?P<rest>.*)$
    """,
    re.IGNORECASE | re.VERBOSE,
)

BARE_QUESTION = re.compile(
    r"^\s*(?:q(?:uest(?:ion)?)?)\s*[.\-:]?\s*(?P<num>\d+)\s*[.)\]:]?\s*(?P<rest>.*)$",
    re.IGNORECASE,
)

OPTION_LINE = re.compile(
    r"^\s*(?:\(?\s*[a-eA-E]\s*\)|[a-eA-E][.)]|[ivxIVX]{1,4}[.)]|[\u2022\-\*])\s+"
)

MARKS = re.compile(
    r"\s*[\(\[]\s*\d+\s*(?:marks?|m(?:ark)?s?)?\s*[\)\]]\s*$",
    re.IGNORECASE,
)

INSTRUCTIONISH = re.compile(
    r"^\s*(answer\s+(any|the)|attempt|section\s+[a-z]|time\s*:|max(?:imum)?\s*marks|"
    r"instructions?|note\s*:|fill\s+in|choose\s+the\s+correct)\b",
    re.IGNORECASE,
)


@dataclass
class ExtractedQuestion:
    number: str
    text: str
    source: str


def _paragraph_has_numbering(paragraph: Paragraph) -> bool:
    ppr = paragraph._p.pPr
    if ppr is None:
        return False
    return ppr.numPr is not None


def _iter_block_items(document: Document):
    body = document.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, document)
        elif child.tag == qn("w:tbl"):
            yield Table(child, document)


def _cell_text(cell) -> str:
    return "\n".join(p.text for p in cell.paragraphs).strip()


def _table_lines(table: Table) -> list[str]:
    lines: list[str] = []
    for row in table.rows:
        cells = [_cell_text(c) for c in row.cells]
        # Drop duplicated cells from merged-looking rows
        seen = []
        for c in cells:
            if c and (not seen or c != seen[-1]):
                seen.append(c)
        if not seen:
            continue
        if len(seen) == 1:
            lines.append(seen[0])
        elif seen[0].strip().isdigit() or QUESTION_START.match(seen[0]):
            num = seen[0].strip()
            rest = " ".join(seen[1:]).strip()
            lines.append(f"{num}. {rest}" if not QUESTION_START.match(rest) else rest)
        else:
            lines.append(" ".join(seen))
    return lines


def _raw_lines(document: Document) -> list[str]:
    lines: list[str] = []
    auto_n = 0
    for block in _iter_block_items(document):
        if isinstance(block, Table):
            lines.extend(_table_lines(block))
            continue
        text = (block.text or "").replace("\xa0", " ").strip()
        if not text:
            continue
        if _paragraph_has_numbering(block) and not QUESTION_START.match(text) and not OPTION_LINE.match(text):
            auto_n += 1
            lines.append(f"{auto_n}. {text}")
        else:
            lines.append(text)
    return lines


def _is_option(line: str) -> bool:
    return bool(OPTION_LINE.match(line))


def _match_start(line: str) -> re.Match | None:
    m = QUESTION_START.match(line)
    if m:
        return m
    return BARE_QUESTION.match(line)


def extract_questions(path: str | Path) -> list[ExtractedQuestion]:
    document = Document(str(path))
    lines = _raw_lines(document)
    questions: list[ExtractedQuestion] = []
    current_num: str | None = None
    current_parts: list[str] = []
    source = Path(path).name

    def flush():
        nonlocal current_num, current_parts
        if current_num is None:
            current_parts = []
            return
        text = " ".join(p for p in current_parts if p).strip()
        text = re.sub(r"\s+", " ", text)
        text = MARKS.sub("", text).strip()
        if text and not INSTRUCTIONISH.match(text) and len(text) > 8:
            questions.append(ExtractedQuestion(number=current_num, text=text, source=source))
        current_num = None
        current_parts = []

    for line in lines:
        if INSTRUCTIONISH.match(line) and current_num is None:
            continue
        started = _match_start(line)
        if started:
            flush()
            current_num = re.sub(r"\s+", "", started.group("num"))
            rest = (started.group("rest") or "").strip()
            current_parts = [rest] if rest else []
            continue
        if current_num is not None:
            if _is_option(line):
                current_parts.append(line)
            else:
                current_parts.append(line)

    flush()

    if len(questions) < 2:
        # Fallback: treat each substantial paragraph as a question.
        fallback: list[ExtractedQuestion] = []
        n = 0
        for line in lines:
            if INSTRUCTIONISH.match(line) or _is_option(line) or len(line) < 12:
                continue
            n += 1
            fallback.append(ExtractedQuestion(number=str(n), text=re.sub(r"\s+", " ", line), source=source))
        if len(fallback) > len(questions):
            return fallback

    # Ensure unique display numbers if the paper reused numbers by section
    seen: dict[str, int] = {}
    for q in questions:
        seen[q.number] = seen.get(q.number, 0) + 1
        if seen[q.number] > 1:
            q.number = f"{q.number} ({seen[q.number]})"
    return questions
