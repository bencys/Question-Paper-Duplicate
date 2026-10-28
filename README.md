# Question Paper Duplicate Finder

Add one or more Word question papers (pick them together, or add more picks; they stay in the list until you analyse them) (`.docx`). Several papers are compared together, so a
question repeated across papers is found. Each question shows the paper it came from. The app shows two lists:

- **Duplicate questions**: the same question asked more than once, even with spelling
  mistakes, rearranged words, synonyms (merits / advantages) or different instruction
  words (explain / describe / write a note on)
- **Similar meaning**: different questions that ask something alike, with a match
  percentage for every pair

Each pair also shows why it matched (spelling, word order, short form, reworded).

**New question paper:** the paper starts with one question per meaning cluster: one from each
set of duplicates or similar questions, plus every question that matches nothing. Open the
**New question paper** tab to see it. Tick questions in the other tabs (or **Select group**)
to add more from the duplicate and similar-meaning groups; untick to remove. **Download Word
(.docx)** saves the paper, numbered 1, 2, 3 with MCQ options kept. **Reset to unique
questions** goes back to the starting set. **All questions** lists the whole paper.

Study terms and short forms are understood: OS = operating system, DBMS = database
management system, T.C.P/I.P = TCP/IP, 2nd = second, adv = advantages, and so on.
Short forms the paper spells out itself, such as "Open Systems Interconnection (OSI)",
are learned automatically. Questions that differ only by an ordinal ("second law" vs
"third law") are never matched; questions that differ only by numbers ("convert 1011"
vs "convert 1101") are shown as similar, not duplicate.

Only questions are read. Headings, the roll number, name and signature boxes, instructions, page
numbers, rough work, blank pages and logos repeated on every page are skipped. Upload one or more
papers at once; every question from all of them is compared together. Bold or capitalised headings, and lines that repeat on every page
(running headers), are skipped as well. Each paper lists what was removed, so you can check the result.

Spelling mistakes are underlined (Indian English; short forms and subject terms are allowed).

## Run

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python make_sample.py
uvicorn app:app --reload --port 8000
```

Open http://127.0.0.1:8000 and upload `sample_question_paper.docx` or your own paper.

The first analysis downloads a small sentence-meaning model (about 90 MB, once). Without
`sentence-transformers` installed the app still works, but similar meaning is judged from
shared words only.

Numbered items such as `1.`, `2)`, `Q.3`, and `Question 4` are detected. Multiple-choice
options stay attached to the parent question and are never counted as questions. Options can be
labelled `a)`, `(B)`, `i)`, `iv.` or `1)`, or typed without a label, one per line. Options written on one
line (`A. ... B. ...`) or in one paragraph (one line break per option) are split too. Word-numbered
lists work: when the paper numbers questions and their options in one sequence, each question takes the
usual number of options (the most common count in the paper) and the next numbered item is the next
question. A `Section B` line restarts the numbering. Match-the-following tables stay with their question.

Questions are compared by their numbered text, plus their tables and pictures. Multiple-choice
options are shown with each question but are not compared.

## Files

- `extractor.py`: reads questions out of the .docx (paragraphs, auto-numbered lists, tables)
- `matcher.py`: duplicate and similar-meaning matching. Add short forms to `SHORT_FORMS`,
  same-meaning words to `SYNONYMS`, and tune `DUPLICATE_AT` / `SIMILAR_AT`.
- `spelling.py`: Indian English spell checker. Add subject words to `DOMAIN_WORDS`.
- `app.py`: FastAPI endpoint `/analyze`
