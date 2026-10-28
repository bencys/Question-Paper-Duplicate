"""Find duplicate questions and questions with similar meaning.

Duplicate: the same question, whatever the spelling mistakes, word order, filler
("explain", "write a short note on") or short forms (OS = operating system).
Similar: a different question that asks something alike, with a match percentage.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from functools import lru_cache
from typing import Callable

from rapidfuzz import fuzz
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from extractor import ExtractedQuestion
from images import figure_hash, same_figure

DUPLICATE_AT = 88.0   # meaning score from which two questions are the same question
SIMILAR_AT = 60.0     # meaning score from which two questions are alike

# Instruction verbs and glue words that do not change what a question asks.
FILLER = {
    "briefly", "explain", "describe", "discuss", "define", "write", "short", "note",
    "notes", "on", "about", "what", "is", "are", "was", "were", "be", "the", "a", "an",
    "of", "to", "in", "for", "with", "and", "or", "do", "does", "how", "why", "from",
    "answer", "following", "any", "state", "mention", "list", "give", "between",
    "comment", "elaborate", "illustrate", "justify", "used", "its", "it", "main",
    "by", "can", "you", "your", "meant", "mean", "means", "meaning", "understand",
    "detail", "details", "detailed", "suitable", "neat", "sketch", "diagram",
    "necessary", "wherever", "where", "required", "brief", "account", "outline",
    "highlight", "point", "out", "bring", "enumerate", "elucidate", "examine",
    "analyse", "analyze", "this", "that", "these", "those", "which", "their", "them",
    "they", "each", "example", "examples", "help", "using", "use", "relevant",
    "various", "over", "compared", "involved", "taking", "consider", "considering",
    "concept", "term", "terms", "known", "called", "so", "s", "some", "important",
    "basic", "fundamental", "please", "kindly", "question", "related", "regarding",
    "has", "have", "had", "will", "would", "should", "shall", "may", "might", "must",
    "into", "as", "at", "also", "all", "his", "her", "he", "she", "we", "our", "us",
    "name", "identify", "present", "discussion", "explanation", "description",
}

# Ordinal words and forms, folded to one number so "2nd law" == "second law".
ORDINAL_WORDS = {
    "zeroth": "0", "first": "1", "second": "2", "third": "3", "fourth": "4", "fifth": "5",
    "sixth": "6", "seventh": "7", "eighth": "8", "ninth": "9", "tenth": "10",
}
ROMAN = {"I": "1", "II": "2", "III": "3", "IV": "4", "V": "5", "VI": "6", "VII": "7",
         "VIII": "8", "IX": "9", "X": "10"}
NUMBER_WORDS = {
    "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
    "eight": "8", "nine": "9", "ten": "10", "twelve": "12", "fifteen": "15", "twenty": "20",
}
ORDINAL_SUFFIX = re.compile(r"^(\d+)(?:st|nd|rd|th)$")

# Short forms seen in study notes and papers, expanded so "OS" == "operating system".
SHORT_FORMS = {
    # computing
    "os": "operating system", "dbms": "database management system",
    "rdbms": "relational database management system", "cpu": "central processing unit",
    "alu": "arithmetic logic unit", "cu": "control unit", "ram": "random access memory",
    "rom": "read only memory", "prom": "programmable read only memory",
    "eprom": "erasable programmable read only memory", "oop": "object oriented programming",
    "oops": "object oriented programming", "ai": "artificial intelligence",
    "ml": "machine learning", "dl": "deep learning", "nlp": "natural language processing",
    "iot": "internet of things", "lan": "local area network", "wan": "wide area network",
    "man": "metropolitan area network", "pan": "personal area network",
    "sql": "structured query language", "html": "hypertext markup language",
    "css": "cascading style sheets", "xml": "extensible markup language",
    "http": "hypertext transfer protocol", "https": "hypertext transfer protocol secure",
    "ftp": "file transfer protocol", "smtp": "simple mail transfer protocol",
    "tcp": "transmission control protocol", "udp": "user datagram protocol",
    "ip": "internet protocol", "osi": "open systems interconnection",
    "dns": "domain name system", "dhcp": "dynamic host configuration protocol",
    "url": "uniform resource locator", "www": "world wide web",
    "dfd": "data flow diagram", "erd": "entity relationship diagram",
    "er": "entity relationship", "uml": "unified modelling language",
    "gui": "graphical user interface", "cli": "command line interface",
    "api": "application programming interface", "ide": "integrated development environment",
    "ds": "data structure", "dsa": "data structures algorithms",
    "toc": "theory of computation", "dfa": "deterministic finite automata",
    "nfa": "non deterministic finite automata", "cfg": "context free grammar",
    "sdlc": "software development life cycle", "oss": "open source software",
    "vlsi": "very large scale integration", "ic": "integrated circuit",
    "ssd": "solid state drive", "hdd": "hard disk drive", "usb": "universal serial bus",
    "bios": "basic input output system", "io": "input output",
    "fcfs": "first come first serve", "sjf": "shortest job first", "rr": "round robin",
    "lru": "least recently used", "fifo": "first in first out", "lifo": "last in first out",
    "acid": "atomicity consistency isolation durability", "ddl": "data definition language",
    "dml": "data manipulation language", "dcl": "data control language",
    "bst": "binary search tree", "bfs": "breadth first search", "dfs": "depth first search",
    "mst": "minimum spanning tree", "vm": "virtual machine", "pc": "personal computer",
    # physics / chemistry / biology / maths
    "ac": "alternating current", "dc": "direct current", "emf": "electromotive force",
    "pd": "potential difference", "shm": "simple harmonic motion",
    "dna": "deoxyribonucleic acid", "rna": "ribonucleic acid", "atp": "adenosine triphosphate",
    "adp": "adenosine diphosphate",
    "lcm": "least common multiple", "hcf": "highest common factor",
    "gcd": "greatest common divisor", "ode": "ordinary differential equation",
    "pde": "partial differential equation", "lpp": "linear programming problem",
    # commerce / economics / law / management
    "gdp": "gross domestic product", "gnp": "gross national product",
    "gst": "goods services tax", "rbi": "reserve bank india",
    "sebi": "securities exchange board india", "hrm": "human resource management",
    "hr": "human resource", "crm": "customer relationship management",
    "erp": "enterprise resource planning",
    "swot": "strengths weaknesses opportunities threats",
    "ipc": "indian penal code", "crpc": "code criminal procedure",
    "cpc": "code civil procedure", "ngo": "non governmental organisation",
    "mnc": "multinational corporation", "wto": "world trade organisation",
    "imf": "international monetary fund", "un": "united nations",
    "fdi": "foreign direct investment", "roi": "return on investment",
    # study-note abbreviations
    "adv": "advantage", "advs": "advantages", "disadv": "disadvantage",
    "disadvs": "disadvantages", "diff": "difference", "defn": "definition",
    "def": "definition", "eqn": "equation", "eqns": "equations",
    "char": "characteristic", "chars": "characteristics", "imp": "importance",
    "prop": "property", "props": "properties", "algo": "algorithm", "algos": "algorithms",
    "pgm": "program", "prog": "program", "progs": "programs", "func": "function",
    "fn": "function", "govt": "government", "mgmt": "management", "info": "information",
    "vs": "versus", "wrt": "with respect", "eg": "example", "approx": "approximate",
    "calc": "calculate", "diag": "diagram", "fig": "figure", "temp": "temperature",
    "freq": "frequency", "avg": "average", "max": "maximum", "min": "minimum",
    "sol": "solution", "soln": "solution", "thm": "theorem", "intro": "introduction",
    "dept": "department", "env": "environment", "dev": "development",
}
# These short forms are also everyday words, so only expand them when typed in capitals.
CAPS_ONLY = {"man", "pan", "ram", "cu", "ds", "er", "io", "pc", "un", "it", "ip", "dc",
             "ac", "pd", "rr", "vm", "ide", "max", "min", "temp", "sol", "dev", "env",
             "fig", "char", "prop", "def", "imp", "acid", "toc"}

# Words that ask the same thing, folded to one token.
SYNONYMS = {}
for canon, words in {
    "@differ": "differ differs differed difference differences different differentiate "
               "differentiating distinguish distinguishing contrast contrasting compare "
               "comparing comparison versus distinction",
    "@adv": "advantage advantages merit merits benefit benefits pros strength strengths",
    "@disadv": "disadvantage disadvantages demerit demerits drawback drawbacks limitation "
               "limitations cons weakness weaknesses shortcoming shortcomings",
    "@type": "type types kind kinds classification classify classified category "
             "categories categorise categorize variety varieties",
    "@feature": "feature features characteristic characteristics property properties "
                "attribute attributes trait traits",
    "@important": "importance significance significant relevance need needs necessity",
    "@role": "role roles function functions functionality purpose purposes duty duties",
    "@work": "working work works operation operations mechanism principle principles "
             "functioning operate operates",
    "@cause": "cause causes reason reasons factor factors",
    "@effect": "effect effects impact impacts consequence consequences outcome outcomes "
               "influence",
    "@step": "step steps procedure procedures process processes stage stages method "
             "methods",
    "@apply": "application applications apply applied uses usage utility",
    "@part": "component components part parts element elements constituent constituents",
    "@define": "definition definitions",
    "@layer": "layer layers level levels tier tiers",
    "@big": "large big huge major",
    "@small": "small little minor tiny",
}.items():
    for w in words.split():
        SYNONYMS[w] = canon

# Aspects a question asks about; two questions on one topic but different aspects are not alike.
ASPECTS = {"@adv", "@disadv", "@type", "@feature", "@role", "@work", "@cause", "@effect",
           "@step", "@apply", "@part", "@important"}

STEM_SUFFIXES = (
    "izations", "isations", "ization", "isation", "ences", "ence", "ances", "ance",
    "ations", "ation", "ments", "ment", "ness",
    "ings", "ing", "ers", "ied", "ies", "ed", "es", "s",
)

DOTTED = re.compile(r"\b(?:[A-Za-z]\.){1,}[A-Za-z]\b\.?")   # T.C.P, O.S., e.g.
WORD = re.compile(r"[A-Za-z0-9]+(?:['’][A-Za-z]+)?")
GLUE = {"of", "and", "the", "for", "in", "on", "to", "a", "an", "&"}


def _stem(word: str) -> str:
    if len(word) <= 4:
        return word
    for suf in STEM_SUFFIXES:
        if word.endswith(suf) and len(word) - len(suf) >= 3:
            return word[: -len(suf)]
    return word


class DSU:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        self.parent[self.find(a)] = self.find(b)


def raw_tokens(text: str) -> list[str]:
    """Words as typed (case kept), with dotted short forms joined and 's dropped."""
    t = text.replace("’", "'")
    letters = [c for c in t if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) > 0.7 * len(letters):
        # A question typed in capitals: case says nothing about short forms.
        t = t.lower()
    t = DOTTED.sub(lambda m: m.group(0).replace(".", ""), t)
    out = []
    for tok in WORD.findall(t):
        if "'" in tok:
            tok = tok.split("'")[0]
        out.append(tok)
    return out


def normalize(text: str) -> str:
    return " ".join(t.lower() for t in raw_tokens(text))


# ── Short forms ───────────────────────────────────────────────────────────

def _initials_match(acronym: str, words: list[str]) -> bool:
    letters = "".join(w[0] for w in words if w not in GLUE)
    return letters == acronym and len([w for w in words if w not in GLUE]) >= 2


def _spelled_out(ac: str, words: list[str]) -> str | None:
    """The run of words in *words* whose initials spell *ac*, if any."""
    for start in range(len(words)):
        if words[start] in GLUE or words[start] in FILLER:
            continue
        for end in range(start + 2, min(len(words), start + 2 * len(ac)) + 1):
            run = words[start:end]
            if run[-1] in GLUE or any(w in FILLER and w not in GLUE for w in run):
                break
            if _initials_match(ac, run):
                return " ".join(w for w in run if w not in GLUE)
    return None


def learn_short_forms(texts: list[str]) -> dict[str, str]:
    """Short forms the paper itself defines or spells out elsewhere.

    "Open Systems Interconnection (OSI)" teaches OSI. A short form of three or
    more letters that is not in SHORT_FORMS is also learned when another
    question spells it out, e.g. "CNN" in one and "convolutional neural network"
    in another.
    """
    learned: dict[str, str] = {}
    for t in texts:
        toks = raw_tokens(t)
        for k, tok in enumerate(toks):
            if not (tok.isupper() and tok.isalpha() and 2 <= len(tok) <= 6):
                continue
            ac = tok.lower()
            # Defined in place: "Open Systems Interconnection (OSI)" / "OSI (Open Systems ...)".
            window = [w.lower() for w in toks[max(0, k - 2 * len(ac)):k]]
            after = [w.lower() for w in toks[k + 1:k + 1 + 2 * len(ac)]]
            for words in (window[::-1], after):
                for size in range(len(words), 1, -1):
                    run = words[:size][::-1] if words is not after else words[:size]
                    if _initials_match(ac, run):
                        learned[ac] = " ".join(w for w in run if w not in GLUE)
                        break
                if ac in learned:
                    break

    acronyms = {tok.lower() for t in texts for tok in raw_tokens(t)
                if tok.isupper() and tok.isalpha() and 3 <= len(tok) <= 6}
    lowered = [[w.lower() for w in raw_tokens(t)] for t in texts]
    for ac in acronyms - set(learned) - set(SHORT_FORMS):
        for words in lowered:
            found = _spelled_out(ac, words)
            if found:
                learned[ac] = found
                break
    return learned


def expand_tokens(tokens: list[str], learned: dict[str, str]) -> tuple[list[str], list[str]]:
    """Lower-cased words with short forms expanded; also returns the short forms used."""
    out, used = [], []
    for tok in tokens:
        low = tok.lower()
        full = learned.get(low)
        if full is None and low in SHORT_FORMS and (low not in CAPS_ONLY or tok.isupper()):
            full = SHORT_FORMS[low]
        # Plural short forms: "DBMSs", "ICs".
        if full is None and tok[:-1].isupper() and tok.endswith("s") and len(tok) > 2:
            base = low[:-1]
            full = learned.get(base) or SHORT_FORMS.get(base)
        if full is not None:
            out.extend(full.split())
            used.append(low)
        else:
            out.append(low)
    return out, used


def _collapse_phrases(words: list[str], learned: dict[str, str]) -> list[str]:
    """Replace each spelled-out term by its short form, so a shared subject counts once.

    Words of the term may be misspelled: "object oriented programing" -> "oop".
    """
    phrases: dict[tuple[str, ...], str] = {}
    for short, full in sorted(list(SHORT_FORMS.items()) + list(learned.items()), key=lambda kv: len(kv[0])):
        if " " in full:
            phrases.setdefault(tuple(full.split()), short)
    by_first: dict[str, list[tuple[str, ...]]] = defaultdict(list)
    for p in phrases:
        by_first[p[0][0]].append(p)

    def same(word: str, target: str) -> bool:
        return word == target or (len(target) > 4 and fuzz.ratio(word, target) >= 85)

    out, i = [], 0
    while i < len(words):
        best = None
        for p in by_first.get(words[i][:1], ()):
            if len(p) <= len(words) - i and (best is None or len(p) > len(best))                     and all(same(w, t) for w, t in zip(words[i:i + len(p)], p)):
                best = p
        if best:
            out.append("#" + phrases[best])
            i += len(best)
        else:
            out.append(words[i])
            i += 1
    return out


# ── Per-question preparation ──────────────────────────────────────────────

@dataclass
class Prepared:
    norm: str                  # lower-case words as typed
    clean: str                 # short forms expanded, spelling fixed (for the meaning model)
    key: str                   # meaning-bearing tokens only
    ordinals: frozenset[str]   # "second law", "World War II"
    values: frozenset[str]     # numbers and coded terms: 1011, IPv4, 8086
    short_forms: list[str]


def prepare(text: str, learned: dict[str, str], fix_word: Callable[[str], str] | None) -> Prepared:
    tokens = raw_tokens(text)
    ordinals, values = set(), set()
    for idx, tok in enumerate(tokens):
        low = tok.lower()
        m = ORDINAL_SUFFIX.match(low)
        if low in ORDINAL_WORDS:
            ordinals.add(ORDINAL_WORDS[low])
        elif m:
            ordinals.add(m.group(1))
        elif tok in ROMAN and (tok != "I" or idx > 0):   # "World War II"; not a leading "I"
            ordinals.add(ROMAN[tok])
        elif low in NUMBER_WORDS:
            values.add(NUMBER_WORDS[low])
        elif any(c.isdigit() for c in low):
            values.add(low)

    words, used = expand_tokens(tokens, learned)
    expanded_shorts = {w for s in used for w in (learned.get(s) or SHORT_FORMS.get(s, "")).split()}
    fixed = []
    for w in words:
        if fix_word and w.isalpha() and w not in expanded_shorts:
            w = fix_word(w)
        fixed.append(w)

    key = []
    for w in _collapse_phrases(fixed, learned):
        if w in FILLER or w in ORDINAL_WORDS or w in NUMBER_WORDS:
            continue
        if ORDINAL_SUFFIX.match(w) or w.isdigit():
            continue
        key.append(w if w.startswith("#") else SYNONYMS.get(w) or _stem(w))
    norm = " ".join(t.lower() for t in tokens)
    return Prepared(
        norm=norm,
        clean=" ".join(fixed),
        key=" ".join(key) or norm,
        ordinals=frozenset(ordinals),
        values=frozenset(values),
        short_forms=used,
    )


# ── Meaning model ─────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _meaning_model():
    """Sentence-meaning model if installed; the matcher falls back to word overlap without it."""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        return None
    name = "sentence-transformers/all-MiniLM-L6-v2"
    try:
        return SentenceTransformer(name, local_files_only=True)  # no network once downloaded
    except Exception:
        pass
    try:
        return SentenceTransformer(name)
    except Exception:
        return None


def meaning_model_available() -> bool:
    return _meaning_model() is not None


def _semantic_matrix(texts: list[str]):
    model = _meaning_model()
    if model is None or len(texts) < 2:
        return None
    emb = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return emb @ emb.T


def _tfidf_matrix(texts: list[str]):
    if len(texts) < 2:
        return None
    vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=1, sublinear_tf=True,
                                 token_pattern=r"(?u)[@#]?\b\w+\b")
    try:
        return cosine_similarity(vectorizer.fit_transform(texts))
    except ValueError:
        return None


# ── Pair matching ─────────────────────────────────────────────────────────

def spelling_variants(a: str, b: str) -> list[tuple[str, str]]:
    """Word pairs that differ only by spelling, e.g. ('diference', 'difference')."""
    ta, tb = normalize(a).split(), normalize(b).split()
    variants: list[tuple[str, str]] = []
    for op, i1, i2, j1, j2 in SequenceMatcher(None, ta, tb, autojunk=False).get_opcodes():
        if op != "replace":
            continue
        for wa in ta[i1:i2]:
            if not wa.isalpha() or not any(wb.isalpha() for wb in tb[j1:j2]):
                continue
            best = max((wb for wb in tb[j1:j2] if wb.isalpha()), key=lambda wb: fuzz.ratio(wa, wb))
            if len(wa) > 2 and fuzz.ratio(wa, best) >= 72 and SYNONYMS.get(wa) != SYNONYMS.get(best, "~"):
                variants.append((wa, best))
    return variants


@dataclass
class MatchLink:
    left: int
    right: int
    kind: str          # duplicate | similar
    score: float       # match percentage shown to the user
    reasons: list[str] = field(default_factory=list)
    variants: list[tuple[str, str]] = field(default_factory=list)


def _aspects(key: str) -> set[str]:
    return {t for t in key.split() if t in ASPECTS}


def match_text(q: ExtractedQuestion) -> str:
    """What a question asks: its stem plus the words and numbers in its tables."""
    cells = [cell for table in q.tables for row in table for cell in row]
    return " ".join([q.text, *cells])


@dataclass
class Attachments:
    """Pictures and tables of a question, in order. Pictures compare by fingerprint, tables by content."""
    figures: list[int | str]
    tables: list[tuple[tuple[str, ...], ...]]

    def __bool__(self) -> bool:
        return bool(self.figures or self.tables)


def _attachments(q: ExtractedQuestion) -> Attachments:
    pictures = q.images   # the question's own pictures; choices are not compared
    tables = [tuple(tuple(" ".join(cell.lower().split()) for cell in row) for row in t) for t in q.tables]
    return Attachments([figure_hash(pic) for pic in pictures], tables)


def _same_figures(a: Attachments, b: Attachments) -> bool:
    return len(a.figures) == len(b.figures) and all(same_figure(x, y) for x, y in zip(a.figures, b.figures))


def _same_attachments(a: Attachments, b: Attachments) -> bool:
    return _same_figures(a, b) and a.tables == b.tables


def _attachment_reason(a: Attachments, b: Attachments) -> str:
    return "different table" if _same_figures(a, b) else "different picture"


def find_matches(
    questions: list[ExtractedQuestion],
    fix_word: Callable[[str], str] | None = None,
    word_freq: Callable[[str], int] | None = None,
) -> dict:
    n = len(questions)
    texts = [match_text(q) for q in questions]
    learned = learn_short_forms(texts)
    preps = [prepare(t, learned, fix_word) for t in texts]
    keys = [p.key for p in preps]
    lexical_sim = _tfidf_matrix(keys)
    semantic_sim = _semantic_matrix([p.clean for p in preps])
    attachments = [_attachments(q) for q in questions]

    links: list[MatchLink] = []
    for i in range(n):
        for j in range(i + 1, n):
            a, b = preps[i], preps[j]
            if a.ordinals != b.ordinals and a.norm != b.norm:
                continue  # "second law" vs "third law": different questions

            att_a, att_b = attachments[i], attachments[j]
            same_att = _same_attachments(att_a, att_b)
            att_diff = (bool(att_a) or bool(att_b)) and not same_att

            if not a.key and not b.key:   # picture-only questions: the pictures decide
                lexical = 100.0 if same_att and bool(att_a) else 0.0
            elif sorted(a.key.split()) == sorted(b.key.split()) or set(a.key.split()) == set(b.key.split()):
                lexical = 100.0
            else:
                set_ratio = fuzz.token_set_ratio(a.key, b.key)
                sort_ratio = fuzz.token_sort_ratio(a.key, b.key)
                cosine = float(lexical_sim[i, j]) * 100 if lexical_sim is not None else 0.0
                # token_set is generous with subsets; temper it with the order-free ratio.
                lexical = max(0.5 * set_ratio + 0.5 * sort_ratio, cosine)

            if semantic_sim is not None and (a.key or b.key):
                semantic = max(0.0, float(semantic_sim[i, j])) * 100
                meaning = lexical if lexical == 100 else max(semantic, 0.45 * lexical + 0.55 * semantic)
            else:
                meaning = lexical

            # Same topic, different aspect: causes vs effects, merits vs demerits.
            asp_a, asp_b = _aspects(a.key), _aspects(b.key)
            if asp_a and asp_b and not asp_a & asp_b:
                meaning = min(meaning, SIMILAR_AT - 5)

            if att_diff:
                # Same wording but another picture or table: a different question, alike in topic.
                if meaning < SIMILAR_AT:
                    continue
                kind, score = "similar", min(meaning, 80.0)
                reasons = [_attachment_reason(att_a, att_b)]
            elif a.norm == b.norm:
                kind, score = "duplicate", 100.0
                reasons = ["identical"] if a.norm else ["same picture" if att_a.figures else "same table"]
            elif meaning >= DUPLICATE_AT and a.values == b.values:
                kind = "duplicate"
                # Closer wording scores higher; only an identical question reads 100%.
                wording = max(fuzz.ratio(a.norm, b.norm), fuzz.token_sort_ratio(a.norm, b.norm))
                score = min(99.0, 0.85 * meaning + 0.15 * wording)
                reasons = _reasons(a, b, questions[i].text, questions[j].text)
                if same_att and att_a:
                    reasons.insert(0, "same picture" if att_a.figures else "same table")
            elif meaning >= SIMILAR_AT:
                kind = "similar"
                score = meaning
                if a.values != b.values:
                    score = min(score, 80.0)   # same pattern, different numbers or codes
                    reasons = ["different values"]
                else:
                    reasons = ["similar meaning"]
            else:
                continue

            variants = spelling_variants(texts[i], texts[j]) if score < 100 else []
            if variants and "spelling" not in reasons and kind == "duplicate":
                reasons.insert(0, "spelling")
            links.append(MatchLink(i, j, kind, round(score, 1), reasons, variants))

    return _build_result(questions, preps, links, learned, fix_word, word_freq)


def _reasons(a: Prepared, b: Prepared, text_a: str, text_b: str) -> list[str]:
    reasons = []
    if a.clean.split() != a.norm.split() or b.clean.split() != b.norm.split():
        if sorted(a.clean.split()) == sorted(b.clean.split()) and set(a.short_forms) == set(b.short_forms):
            reasons.append("spelling")
    if set(a.short_forms) != set(b.short_forms):
        reasons.append("short form")
    if sorted(a.norm.split()) == sorted(b.norm.split()):
        reasons.append("word order")
    elif sorted(a.key.split()) == sorted(b.key.split()) and a.key.split() != b.key.split():
        reasons.append("word order")
    if not reasons or fuzz.token_sort_ratio(a.clean, b.clean) < 90:
        reasons.append("reworded")
    return reasons


def _build_result(questions, preps, links, learned, fix_word, word_freq) -> dict:
    n = len(questions)

    def is_rarer(x: str, y: str) -> bool:
        return bool(word_freq) and word_freq(x) < word_freq(y)

    def wrong_sides(wa: str, wb: str) -> tuple[bool, bool]:
        """Which side of a spelling variant is the misspelling."""
        wrong_a = bool(fix_word) and fix_word(wa) != wa
        wrong_b = bool(fix_word) and fix_word(wb) != wb
        if wrong_a == wrong_b:  # both or neither flagged: the less common spelling is wrong
            wrong_a, wrong_b = is_rarer(wa, wb), is_rarer(wb, wa)
        return wrong_a, wrong_b

    def components(member_links: list[MatchLink]) -> list[list[int]]:
        uf = DSU(n)
        for lk in member_links:
            uf.union(lk.left, lk.right)
        comp: dict[int, list[int]] = defaultdict(list)
        for i in range(n):
            comp[uf.find(i)].append(i)
        return [m for m in comp.values() if len(m) > 1]

    def build_group(members: list[int], member_links: list[MatchLink], kind: str) -> dict:
        variant_words: dict[int, set[str]] = defaultdict(set)
        for lk in member_links:
            for wa, wb in lk.variants:
                wrong_a, wrong_b = wrong_sides(wa, wb)
                if wrong_a:
                    variant_words[lk.left].add(wa)
                if wrong_b:
                    variant_words[lk.right].add(wb)
        scores = [lk.score for lk in member_links if lk.kind == kind] or [lk.score for lk in member_links]
        return {
            "type": kind,
            "score": round(max(scores), 1),
            "question_numbers": [questions[i].number for i in members],
            "member_index": members,
            "questions": [
                {"number": questions[i].number, "text": questions[i].text,
                 "source": questions[i].source, "images": questions[i].images, "option_images": questions[i].option_images,
                 "tables": questions[i].tables, "variant_words": sorted(variant_words[i]),
                 "short_forms": preps[i].short_forms}
                for i in members
            ],
            "pairs": [
                {"a": questions[lk.left].number, "b": questions[lk.right].number,
                 "a_source": questions[lk.left].source, "b_source": questions[lk.right].source,
                 "kind": lk.kind, "score": lk.score, "reasons": lk.reasons}
                for lk in sorted(member_links, key=lambda lk: (lk.kind != kind, -lk.score))
            ],
        }

    dup_links = [lk for lk in links if lk.kind == "duplicate"]
    duplicates = []
    for members in components(dup_links):
        mset = set(members)
        duplicates.append(build_group(
            members, [lk for lk in dup_links if lk.left in mset and lk.right in mset], "duplicate"))

    # Similar groups: questions joined by a similar-meaning link. Duplicates inside a
    # similar group are shown in it too, so the whole family is visible in one place.
    similar = []
    for members in components(links):
        mset = set(members)
        member_links = [lk for lk in links if lk.left in mset and lk.right in mset]
        if any(lk.kind == "similar" for lk in member_links):
            similar.append(build_group(members, member_links, "similar"))

    duplicates.sort(key=lambda g: (-len(g["member_index"]), -g["score"]))
    similar.sort(key=lambda g: -g["score"])

    used = sorted({s for p in preps for s in p.short_forms})
    short_forms = [
        {"short": s.upper(), "full": learned.get(s) or SHORT_FORMS[s],
         "learned": s in learned and s not in SHORT_FORMS}
        for s in used
    ]
    return {
        "total": n,
        "duplicate_groups": duplicates,
        "similar_groups": similar,
        "duplicate_questions": sum(len(g["member_index"]) - 1 for g in duplicates),
        "short_forms": short_forms,
        "meaning_model": meaning_model_available(),
    }
