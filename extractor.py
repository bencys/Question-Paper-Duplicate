"""Extract numbered questions from a Word question paper."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from images import data_uri

QUESTION_START = re.compile(
    r"""^\s*
        (?:
            (?:q(?:uest(?:ion)?)?)\s*[.\-:]?\s*
            | sec(?:tion)?\s*[A-Z]\s*[-:.]?\s*
        )?
        (?P<num>\d+[A-Za-z]? (?:\s*[.\-]\s*\d+[A-Za-z]?)?)
        \s*[.)\]:](?!\d)\s*
        (?P<rest>.*)$
    """,
    re.IGNORECASE | re.VERBOSE,
)

BARE_QUESTION = re.compile(
    r"^\s*(?:q(?:uest(?:ion)?)?)\s*[.\-:]?\s*(?P<num>\d+)\s*[.)\]:]?\s*(?P<rest>.*)$",
    re.IGNORECASE,
)

OPTION_LINE = re.compile(
    r"^\s*(?:\(?\s*[a-eA-E]\s*\)|[a-eA-E][.)]|[ivxIVX]{1,4}[.)]|[•\-\*])\s+"
)

MARKS = re.compile(
    r"\s*[\(\[]\s*\d+\s*(?:marks?|m(?:ark)?s?)?\s*[\)\]]\s*$",
    re.IGNORECASE,
)

# Choices are numbered in one of three styles: a) b) c), i) ii) iii), or 1) 2) 3).
CHOICE_STYLES = ("letter", "roman", "number")
ROMAN_CHOICES = ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"]
CHOICE_LABEL_PREFIX = re.compile(r"^\s*(?:\(\s*[A-Za-z0-9]{1,4}\s*\)|[A-Za-z0-9]{1,4}[.)])\s*")
# Lettered choices written on the same line as the question.
INLINE_CHOICE = re.compile(r"(?:^|\s)(?:\(\s*[a-eA-E]\s*\)|[a-eA-E][.)])\s+")
MAX_CHOICE_WORDS = 40          # longer lettered or numbered items are sub-parts of the question, not choices
MAX_UNLABELLED_CHOICES = 6     # lines after a stem that read as unlabelled choices
SHORT_CHOICE_WORDS = 20        # a numbered line this short that follows the numbering can still be a choice
MAX_CHOICE_RUN = 12            # lines looked ahead to tell a numbered choice list from numbered questions
MIN_QUESTION_TABLE_WORDS = 4   # numbered table rows with longer text are questions, shorter ones are items

# Words that open a question, such as "Explain the difference..." — a choice rarely starts with one.
QUESTION_WORDS = {
    "explain", "define", "describe", "what", "which", "how", "why", "list", "state", "write",
    "mention", "discuss", "distinguish", "differentiate", "convert", "compare", "find", "calculate",
    "give", "name", "prove", "derive", "illustrate", "enumerate", "identify", "outline", "justify",
    "classify", "draw", "design", "construct", "show", "sketch", "evaluate", "analyse", "analyze",
    "trace", "solve", "obtain", "compute", "examine", "comment", "interpret", "summarise", "summarize",
}

SECTION_HEADER = re.compile(r"^\s*(?:section|part)\s+[A-Za-z0-9]{1,3}\b", re.IGNORECASE)

# Lines that are not questions. Page-level ones (roll number, name, page numbers, marks headings) are
# skipped; break-level ones (rough work, blank pages, instructions) end the current question and skip
# what follows until the next section or the next expected question number.
PAGE_NOISE = re.compile(
    r"^\s*(?:roll\s*(?:no|number)|reg(?:istration)?\.?\s*(?:no|number)|enrol+ment\s*(?:no|number)|"
    r"seat\s*no|hall\s*ticket|name\s*(?:of\s+(?:the\s+)?(?:candidate|student))?\s*:|candidate'?s?\s+name|"
    r"signature|invigilator|page\s*\d+|\d+\s*(?:of|/)\s*\d+\s*$|-+\s*\d+\s*-+\s*$|"
    r"(?:q\.?\s*p\.?\s*code|paper\s*code|question\s+paper\s*code|subject\s*(?:code|name)?|course\s*code|"
    r"class|semester|branch|department|year|date|max(?:imum)?\.?\s*marks|total\s*marks|"
    r"time(?:\s*allowed)?|duration|set|version)\s*[:\-])",
    re.IGNORECASE,
)
BREAK_NOISE = re.compile(
    r"^\s*(?:"
    r"(?:use\s+this\s+|space\s+for\s+|extra\s+|additional\s+|blank\s+|written\s+)?rough\s+(?:work(?:ing)?|sheet|page|space|area)s?"
    r"(?:\s+(?:page|sheet|space|area))?"
    r"|(?:rough|blank|extra|scribble|scratch|additional|written|answer)\s+(?:work|page|sheet|space|area|paper)s?"
    r"(?:\s+(?:written|blank|work|page|pages|sheet|sheets))*"
    r"|(?:work|working|answer|answers|scribble|written)\s+(?:page|sheet|space|area)s?"
    r"|(?:space|area)\s+for\s+\w+(?:\s+\w+)?"
    r"|blank\s+(?:page|sheet|space|paper)s?(?:\s+(?:written|left))*"
    r"|this\s+page\s+(?:is\s+)?(?:intentionally\s+)?(?:left\s+)?blank"
    r"|page\s+(?:intentionally\s+)?(?:left\s+)?blank"
    r"|end\s+of\s+(?:the\s+)?(?:question\s+)?paper|(?:paper\s+)?ends\s+here"
    r"|(?:general\s+|important\s+|read\s+)?instructions?(?:\s+to\s+(?:the\s+)?candidates?)?"
    r"|(?:answer|attempt)\s+(?:all|any|the)\s+(?:questions?|following)[^?]*"
    r")\s*(?:\([^)]*\)\s*)?[:.!]?\s*$",
    re.IGNORECASE,
)
# A picture that appears this many times is a logo or watermark on every page, not a figure.
REPEATED_PICTURE = 3
# A numbered line with another numbered item inside it ("1. Write neatly. 2. Attempt all") is a list of instructions.
INLINE_ENUM = re.compile(r"\s\d+[.)]\s+[A-Za-z]")

INSTRUCTIONISH = re.compile(
    r"^\s*(answer\s+(any|the)|attempt|section\s+[a-z]|time\s*:|max(?:imum)?\s*marks|"
    r"instructions?|note\s*:|fill\s+in|choose\s+the\s+correct)\b",
    re.IGNORECASE,
)

VML_IMAGEDATA = "{urn:schemas-microsoft-com:vml}imagedata"


@dataclass
class ExtractedQuestion:
    number: str
    text: str          # question stem only; used for matching
    source: str
    options: list[str] = field(default_factory=list)                # MCQ choices, kept for display
    images: list[str] = field(default_factory=list)                 # pictures in the stem, as data URIs
    option_images: list[list[str]] = field(default_factory=list)    # pictures in each choice, aligned with options
    tables: list[list[list[str]]] = field(default_factory=list)     # tables as rows of cell text


@dataclass
class Line:
    """One block of the paper: a text line, a numbered table row, or a whole table."""
    text: str = ""
    images: list[str] = field(default_factory=list)
    table: list[list[str]] | None = None
    numbered: bool = False   # a Word list item: its number comes from the list, not from the text
    heading: bool = False    # a heading or running header: never part of a question
    removed: str = ""        # a block removed as page content, with the reason shown to the user


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


def _images_in(element, part) -> list[str]:
    """Pictures inside a paragraph, table or row, in reading order."""
    ids = [b.get(qn("r:embed")) for b in element.iter(qn("a:blip"))]
    ids += [d.get(qn("r:id")) for d in element.iter(VML_IMAGEDATA)]
    images = []
    for rid in ids:
        image = part.related_parts.get(rid) if rid else None
        if image is not None:
            images.append(data_uri(image.blob, image.content_type))
    return images


def _table_rows(table: Table) -> list[list[str]]:
    rows = []
    for row in table.rows:
        texts, last = [], None
        for cell in row.cells:
            if cell._tc is last:   # merged cell: python-docx repeats it
                continue
            last = cell._tc
            texts.append(_cell_text(cell))
        rows.append(texts)
    return rows


def _starts_question(cell: str) -> bool:
    return cell.strip().isdigit() or bool(QUESTION_START.match(cell))


def _is_question_table(rows: list[list[str]]) -> bool:
    """A table whose numbered rows hold whole questions. Match-the-following items are short."""
    numbered = [r for r in rows if len(r) >= 2 and _starts_question(r[0])]
    if not numbered:
        return False
    words = [len(" ".join(r[1:]).split()) for r in numbered]
    return sum(words) / len(words) >= MIN_QUESTION_TABLE_WORDS


def _question_table_lines(table: Table, part) -> list[Line]:
    lines: list[Line] = []
    started = False   # rows above the first numbered row are a header, such as "No | Question"
    for row in table.rows:
        texts, last = [], None
        for cell in row.cells:
            if cell._tc is last:
                continue
            last = cell._tc
            texts.append(_cell_text(cell))
        # Drop duplicated cells from merged-looking rows
        seen = []
        for c in texts:
            if c and (not seen or c != seen[-1]):
                seen.append(c)
        started = started or bool(seen) and _starts_question(seen[0])
        if not started or (not seen and not _images_in(row._tr, part)):
            continue
        images = _images_in(row._tr, part)
        if len(seen) == 0:
            text = ""
        elif len(seen) == 1:
            text = f"{seen[0]}." if seen[0].isdigit() else seen[0]
        elif _starts_question(seen[0]):
            num = seen[0].strip()
            rest = " ".join(seen[1:]).strip()
            text = f"{num}. {rest}" if not QUESTION_START.match(rest) else rest
        else:
            text = " ".join(seen)
        lines.append(Line(text=text, images=images))
    return lines


DETAIL_CELL = re.compile(
    r"^(?:subject|course|class|semester|branch|department|date|time|duration|max|marks|total|"
    r"code|q\.?\s*p\.?|paper|session|exam|roll|registration|enrol+ment|name|signature|invigilator)\b",
    re.IGNORECASE,
)


def _noise_table(rows: list[list[str]]) -> bool:
    """A table of the paper's details (roll number, name, subject, marks, signature), not of questions."""
    cells = [c.strip() for r in rows for c in r if c and c.strip()]
    if any(PAGE_NOISE.match(c) for c in cells):
        return True
    if sum(1 for c in cells if DETAIL_CELL.match(c)) >= 2:
        return True
    return any(len(c.split()) <= 4 and re.search(r"\b(?:roll|registration|signature|invigilator|candidate)\b", c, re.IGNORECASE)
               for c in cells)


def _table_summary(rows: list[list[str]]) -> str:
    cells = [c.strip() for r in rows for c in r if c and c.strip()]
    return "Details table: " + " | ".join(cells)[:120]


def _short_heading(text: str, bold: bool, style: str) -> bool:
    """A short line set as a heading: bold, in a heading style, or in capitals, and not a question."""
    words = text.split()
    if not words or len(words) > 10 or text.rstrip().endswith("?"):
        return False
    return bold or style.lower().startswith(("heading", "title", "subtitle")) or text.isupper()


def _mark_repeated(lines: list[Line]) -> list[Line]:
    """Lines that repeat across the paper, such as a running page header, are not questions."""
    key = lambda t: re.sub(r"[\d\W_]+", " ", t.lower()).strip()
    counts = Counter(key(line.text) for line in lines if line.text and not line.numbered and len(line.text.split()) >= 4)
    for line in lines:
        if line.text and len(line.text.split()) >= 4 and counts[key(line.text)] >= 4:
            line.heading = True
    return lines


def _drop_repeated_pictures(lines: list[Line]) -> list[Line]:
    counts = Counter(uri for line in lines for uri in line.images)
    for line in lines:
        line.images = [uri for uri in line.images if counts[uri] < REPEATED_PICTURE]
    return lines


def _raw_lines(document: Document) -> list[Line]:
    lines: list[Line] = []
    part = document.part
    for block in _iter_block_items(document):
        if isinstance(block, Table):
            rows = _table_rows(block)
            if _noise_table(rows):
                lines.append(Line(removed=_table_summary(rows)))
                continue
            if _is_question_table(rows):
                lines.extend(_question_table_lines(block, part))
            elif any(any(r) for r in rows) or _images_in(block._tbl, part):
                lines.append(Line(images=_images_in(block._tbl, part), table=rows))
            continue
        # A line break inside a paragraph starts a new line: options often sit under one paragraph.
        pieces = [t.strip() for t in (block.text or "").replace("\xa0", " ").split("\n")]
        pieces = [t for t in pieces if t]
        images = _images_in(block._p, part)
        if not pieces and not images:
            continue
        text = pieces[0] if pieces else ""
        runs = [r for r in block.runs if r.text.strip()]
        bold = bool(runs) and all(bool(r.bold) for r in runs)
        style = block.style.name if block.style is not None else ""
        lines.append(Line(text=text, images=images, numbered=_paragraph_has_numbering(block),
                          heading=_short_heading(text, bold, style)))
        lines.extend(Line(text=t, heading=_short_heading(t, bold, style)) for t in pieces[1:])
    return _mark_repeated(_drop_repeated_pictures(lines))


def _looks_like_choices(items: list[str]) -> bool:
    return len(items) >= 2 and all(0 < len(i.split()) <= MAX_CHOICE_WORDS for i in items)


def option_body(choice: str) -> str:
    """A choice without its label: 'b) ROM' -> 'ROM'."""
    return CHOICE_LABEL_PREFIX.sub("", choice, count=1).strip()


def _choice_label(style: str, k: int) -> str | None:
    """The label a paper of this style gives choice k (1-based), or None when there is none."""
    if style == "letter":
        return chr(ord("a") + k - 1) if k <= 26 else None
    if style == "roman":
        return ROMAN_CHOICES[k - 1] if k <= len(ROMAN_CHOICES) else None
    return str(k)


def _numbered_choices_ahead(texts: list[str]) -> bool:
    """True when the lines open with short choices 1), 2), ...: a numbered choice list, not questions."""
    count = 0
    for text in texts:
        if not (re.match(rf"^\s*\(?\s*{count + 1}\s*[.)]", text)
                and len(option_body(text).split()) <= MAX_CHOICE_WORDS):
            break
        count += 1
    return count >= 2


def _choice_style(text: str, k: int, style: str | None, numbered_ahead: bool = False) -> str | None:
    """The style ('letter', 'roman' or 'number') when *text* is choice k of a question, else None.

    Later choices must keep the style of the first. "1)" or "1." usually starts a question,
    so a first numbered choice counts only in brackets, "(1)", or when the lines after it
    are numbered choices too (*numbered_ahead*).
    """
    for candidate in [style] if style else CHOICE_STYLES:
        label = _choice_label(candidate, k)
        if label is None:
            continue
        if candidate == "number" and k == 1 and not numbered_ahead:
            forms = rf"\(\s*{label}\s*\)"
        else:
            forms = rf"\(\s*{label}\s*\)|{label}[.)]"
        if re.match(rf"^\s*(?:{forms})(?:\s+|$)", text, re.IGNORECASE):
            return candidate
    return None


def _question_like(body: str) -> bool:
    words = body.split()
    first = re.sub(r"[^a-z]", "", words[0].lower()) if words else ""
    return body.rstrip().endswith("?") or first in QUESTION_WORDS


def _imperative(body: str) -> bool:
    """An instruction such as 'Write neatly.' or 'Attempt all questions.', not a question."""
    return bool(re.match(r"^\s*(?:write|attempt|answer|do|read|use|follow|note|fill|mark|check)\b", body, re.IGNORECASE))


def _leading_number(num: str) -> int | None:
    m = re.match(r"\d+", num)
    return int(m.group()) if m else None


def _choices_ok(choices: list[str], images: list[list[str]]) -> bool:
    """Choices with words, or a picture alone (a figure option), within the length limit."""
    labels = [option_body(c) for c in choices]
    return len(choices) >= 2 and all(
        0 < len(label.split()) <= MAX_CHOICE_WORDS or (not label.strip() and pics)
        for label, pics in zip(labels, images)
    )


def _split_inline_choices(text: str) -> tuple[str, list[str]]:
    """'Which is volatile? (a) RAM (b) ROM' -> ('Which is volatile?', ['(a) RAM', '(b) ROM'])."""
    starts = [m.start() for m in INLINE_CHOICE.finditer(text)]
    if len(starts) < 2:
        return text, []
    stem = text[: starts[0]].strip()
    items = [text[a:b].strip() for a, b in zip(starts, starts[1:] + [len(text)])]
    labels = [re.sub(r"^\(?\s*([a-eA-E]).*", r"\1", i).lower() for i in items]
    sequential = labels == [chr(ord("a") + k) for k in range(len(labels))]
    # MCQ stems end in a question mark, colon or blank; "Define (a) stack and (b) queue" does not.
    mcq_stem = stem.endswith(("?", ":", "-", ",")) or "__" in stem or "…" in stem or "..." in stem or len(items) >= 3
    if mcq_stem and sequential and _looks_like_choices([INLINE_CHOICE.sub("", i, count=1) for i in items]):
        return stem, items
    return text, []


def _is_option(line: str) -> bool:
    return bool(OPTION_LINE.match(line))


def _match_start(line: str) -> re.Match | None:
    m = QUESTION_START.match(line)
    if m:
        return m
    return BARE_QUESTION.match(line)


def _next_text(lines: list[Line], idx: int) -> str:
    """The next text line after *idx*, or an empty string."""
    for line in lines[idx + 1: idx + 3]:
        if line.text and line.table is None:
            return line.text
    return ""


def _next_is_choice(lines: list[Line], idx: int) -> bool:
    """The next text line is a choice, so the line before it is a question stem."""
    for line in lines[idx + 1: idx + 3]:
        if line.text and line.table is None:
            typed = _match_start(line.text)
            if typed and _question_like(typed.group("rest") or ""):
                return False   # the next question, not a choice
            return _choice_style(line.text, 1, None, numbered_ahead=True) is not None
    return False


def _extract(lines: list[Line], source: str, options_per_question: int) -> tuple[list[ExtractedQuestion], list[str]]:
    """Questions in reading order, and the text removed as page content.

    Typed numbers ("4.") start a question. Word-numbered items are its choices until it has
    *options_per_question* of them; the next numbered item is then the next question.
    """
    questions: list[ExtractedQuestion] = []
    removed: list[str] = []
    current_num: str | None = None
    current_parts: list[str] = []
    current_choices: list[str] = []
    current_choice_images: list[list[str]] = []
    current_style: str | None = None
    current_images: list[str] = []
    current_tables: list[list[list[str]]] = []
    # Pictures and tables above a question number belong to that question.
    pending_images: list[str] = []
    pending_tables: list[list[list[str]]] = []
    # The question number the paper gives next. None at the start and after a section header.
    expected: int | None = None
    # Rough work, blank pages and instructions are skipped until the next section or question.
    skipping = False

    def note(text: str) -> None:
        if text and len(removed) < 500:
            removed.append(text[:120])

    def flush():
        nonlocal current_num, current_parts, current_choices, current_choice_images, current_style
        nonlocal current_images, current_tables
        if current_num is None:
            current_parts, current_choices, current_choice_images = [], [], []
            current_style = None
            return
        choices, choice_images, images = current_choices, current_choice_images, current_images
        if choices and not _choices_ok(choices, choice_images):
            current_parts += choices      # long lettered items are sub-questions, not choices
            for pics in choice_images:
                images += pics
            choices, choice_images = [], []
        text = re.sub(r"\s+", " ", " ".join(p for p in current_parts if p)).strip()
        text = MARKS.sub("", text).strip()
        if not choices and 2 <= len(current_parts) - 1 <= MAX_UNLABELLED_CHOICES:
            # Answers typed without a label, one per line after the stem.
            tail = [t for t in current_parts[1:] if t]
            if len(tail) == len(current_parts) - 1 and all(len(t.split()) <= MAX_CHOICE_WORDS for t in tail):
                text = current_parts[0]
                choices = tail
                choice_images = [[] for _ in choices]
        if not choices:
            text, choices = _split_inline_choices(text)
            choice_images = [[] for _ in choices]
        if (len(text) > 8 or images or current_tables) and not (INSTRUCTIONISH.match(text) and len(text) < 60):
            questions.append(ExtractedQuestion(
                number=current_num, text=text, source=source,
                options=[MARKS.sub("", c).strip() for c in choices],
                images=images,
                option_images=choice_images if choices else [],
                tables=current_tables,
            ))
        current_num = None
        current_parts, current_choices, current_choice_images = [], [], []
        current_style = None
        current_images, current_tables = [], []

    for idx, line in enumerate(lines):
        if line.removed:
            note(line.removed)
            continue
        if skipping and line.table is not None:
            note(_table_summary(line.table))
            continue
        if line.table is not None:
            if current_num is None:
                pending_tables.append(line.table)
                pending_images += line.images
            else:
                current_tables.append(line.table)
                current_images += line.images
            continue
        text = line.text
        if PAGE_NOISE.match(text) and len(text.split()) <= 12:
            note(text)
            continue
        if BREAK_NOISE.match(text) and len(text.split()) <= 12:
            flush()
            skipping = True
            note(text)
            continue
        if skipping:
            typed = _match_start(text)
            resumes = (
                (SECTION_HEADER.match(text) and len(text.split()) <= 12)
                or (typed and typed.group("num").isdigit() and not INLINE_ENUM.search(text)
                    and (int(typed.group("num")) == expected if expected is not None
                         else _question_like(typed.group("rest") or "") and not _imperative(typed.group("rest") or "")))
                or (expected is None and line.numbered and bool(text))
            )
            if not resumes:
                note(text)
                continue
            skipping = False
        if SECTION_HEADER.match(text) and len(text.split()) <= 12:
            flush()
            expected = None
            pending_images += line.images
            note(text)
            continue
        if INSTRUCTIONISH.match(text) and current_num is None:
            pending_images += line.images
            note(text)
            continue
        started = _match_start(text)
        # A bare label such as "Q3" marks a question only when a question or its choices follow.
        if re.match(r"^\s*q\.?\s*\d+\s*[.:]?\s*$", text, re.IGNORECASE):
            if not (_question_like(_next_text(lines, idx)) or _next_is_choice(lines, idx)):
                note(text)
                continue
        # A numbered line is a question when it carries the expected number, reads like a question,
        # or has its choices under it. "Q2 Circles must be darkened..." in the instructions is none of these.
        if started and not (
                (expected is not None and started.group("num").isdigit() and int(started.group("num")) == expected)
                or (_question_like(started.group("rest") or "") and not _imperative(started.group("rest") or ""))
                or _next_is_choice(lines, idx)):
            started = None
        if current_num is not None and text:
            ahead = _numbered_choices_ahead([l.text for l in lines[idx:idx + MAX_CHOICE_RUN]])
            style = _choice_style(text, len(current_choices) + 1, current_style, numbered_ahead=ahead)
            body = option_body(text)
            # A typed number that carries the next question number is a question, even when it looks like a choice.
            is_question = bool(started) and (
                expected is None or not started.group("num").isdigit()
                or int(started.group("num")) == expected)
            if style and not (is_question and (len(body.split()) > SHORT_CHOICE_WORDS or _question_like(body))):
                current_style = style
                current_choices.append(text)
                current_choice_images.append(list(line.images))
                continue
        if started:
            flush()
            current_num = re.sub(r"\s+", "", started.group("num"))
            number = _leading_number(current_num)
            expected = number + 1 if number is not None else None
            rest = (started.group("rest") or "").strip()
            current_parts = [rest] if rest else []
            current_images = pending_images + line.images
            current_tables = pending_tables
            pending_images, pending_tables = [], []
            continue
        if line.heading and not line.numbered:
            note(text)
            continue
        if line.numbered and text:
            # A Word-numbered item: the next question once the current one has its choices, else a choice.
            full = bool(options_per_question) and len(current_choices) >= options_per_question
            if current_num is None or full or not options_per_question:
                flush()
                auto = expected or 1
                current_num = str(auto)
                expected = auto + 1
                current_parts = [text]
                current_images = pending_images + line.images
                current_tables = pending_tables
                pending_images, pending_tables = [], []
                continue
            current_choices.append(text)
            current_choice_images.append(list(line.images))
            continue
        if current_num is None:
            pending_images += line.images
            note(text)
            continue
        if not text:
            # A picture on its own: a choice's picture if choices have started, else part of the stem.
            if current_choice_images:
                current_choice_images[-1] += line.images
            else:
                current_images += line.images
            continue
        if current_choices:
            # A choice that wraps onto the next line continues it; other text after the choices is page content.
            if not re.search(r"[.?!;:]\s*$", current_choices[-1]):
                current_choices[-1] += " " + text
            else:
                note(text)
            continue
        current_parts.append(text)
        current_images += line.images

    flush()
    return questions, removed


def read_paper(path: str | Path, source: str | None = None) -> tuple[list[ExtractedQuestion], list[str]]:
    """Questions of one paper, and the page content removed from it. *source* is the paper's name."""
    document = Document(str(path))
    lines = _raw_lines(document)
    source = source or Path(path).name
    # First read without assuming an option count; the usual count then groups Word-numbered choices.
    first, first_removed = _extract(lines, source, 0)
    counts = Counter(len(q.options) for q in first if len(q.options) >= 2)
    per_question = counts.most_common(1)[0][0] if counts else 0
    questions, removed = _extract(lines, source, per_question) if per_question else (first, first_removed)

    if len(questions) < 2:
        # Fallback: treat each substantial paragraph as a question.
        fallback: list[ExtractedQuestion] = []
        n = 0
        for line in lines:
            text = line.text
            if line.table is not None or not text:
                continue
            if INSTRUCTIONISH.match(text) or _is_option(text) or len(text) < 12:
                continue
            n += 1
            fallback.append(ExtractedQuestion(number=str(n), text=re.sub(r"\s+", " ", text), source=source))
        if len(fallback) > len(questions):
            return fallback, removed

    # Ensure unique display numbers if the paper reused numbers by section
    seen: dict[str, int] = {}
    for q in questions:
        seen[q.number] = seen.get(q.number, 0) + 1
        if seen[q.number] > 1:
            q.number = f"{q.number} ({seen[q.number]})"
    return questions, removed


def extract_questions(path: str | Path, source: str | None = None) -> list[ExtractedQuestion]:
    """Questions of one paper. *source* is the paper's name for display; default is the file name."""
    return read_paper(path, source)[0]
