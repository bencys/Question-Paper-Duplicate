"""Indian English spell checking for question papers.

The bundled pyspellchecker dictionary is American, so British/Indian forms
(colour, programme, analyse, centre, defence, labelled ...) are accepted by
mapping them to their American form before lookup. Acronyms, study-note short
forms, words with digits, proper nouns and terms the paper itself repeats are
skipped so only genuine typos are flagged.
"""

from __future__ import annotations

import re
from collections import Counter
from functools import lru_cache

from spellchecker import SpellChecker

from matcher import SHORT_FORMS as EXPANDED_SHORT_FORMS

_spell = SpellChecker(language="en")

# Short forms common in Indian exam papers and study notes.
SHORT_FORMS = {
    "wrt", "eg", "ie", "etc", "viz", "approx", "diff", "eqn", "eqns", "qn", "qns",
    "ans", "defn", "def", "govt", "dept", "reqd", "max", "min", "std", "temp",
    "nos", "fig", "figs", "imp", "mgmt", "info", "sec", "chap", "ch", "pg", "ref",
    "abbr", "adv", "disadv", "advs", "char", "prop", "props", "expt", "expts",
    "obs", "calc", "const", "coeff", "coeffs", "dia", "dist", "freq", "vol",
    "wt", "ht", "len", "avg", "esp", "incl", "excl", "intro", "concl", "pls",
    "sol", "soln", "solns", "thm", "pf", "cf", "nb", "ps", "vs", "resp",
    "mcq", "mcqs", "viva", "pgm", "pgms", "prog", "progs", "algo", "algos",
    "func", "fn", "fns", "var", "vars", "arg", "args", "init", "config", "admin",
    "env", "dev", "lib", "libs", "src", "dest", "addr", "ptr", "ptrs", "struct",
    "enum", "bool", "int", "stdio", "printf", "scanf", "cout", "cin", "malloc",
    "sem", "sems", "lab", "labs", "hrs", "mins", "secs", "yr", "yrs", "km", "kg",
    "mg", "ml", "cm", "mm", "kw", "kwh", "hp", "rpm", "mrp", "pvt", "ltd", "co",
    "inc", "corp", "acc", "bal", "amt", "qty", "dr", "cr", "p&l", "roi", "npv",
    "irr", "emi", "gst", "tds", "pan", "ifsc", "upi", "neft", "rtgs",
}

# Indian-context vocabulary missing from the American dictionary.
INDIAN_WORDS = {
    "lakh", "lakhs", "crore", "crores", "rupee", "rupees", "paise", "panchayat",
    "panchayats", "gram", "sabha", "lok", "rajya", "vidhan", "zila", "parishad",
    "tehsil", "taluk", "taluka", "mandal", "nagar", "nigam", "kharif", "rabi",
    "zaid", "monsoon", "ayurveda", "ayurvedic", "yoga", "swadeshi", "satyagraha",
    "swaraj", "mahatma", "sarvodaya", "niti", "aayog", "aadhaar", "ayushman",
    "anganwadi", "ashram", "gurukul", "sanskrit", "hindi", "tamil", "telugu",
    "kannada", "malayalam", "marathi", "bengali", "gujarati", "punjabi", "odia",
    "prelims", "mains", "practicals", "invigilator", "syllabi", "coursework",
    "maths", "stats", "timetable", "fortnight", "fortnightly", "matric",
    "intermediate", "polytechnic", "postgraduate", "undergraduate", "crèche",
}

# Academic terms across fields that the generic dictionary often lacks.
DOMAIN_WORDS = {
    "docx", "pdf", "online", "offline", "email", "website", "webpage", "internet",
    "elucidate", "enumerate", "tabulate", "diagrammatically", "schematically",
    "stoichiometry", "molarity", "molality", "valency", "hybridisation",
    "isomerism", "electrolysis", "chromatography", "spectroscopy", "aliphatic",
    "alicyclic", "heterocyclic", "carbonyl", "carboxyl", "hydroxyl", "aldehyde",
    "ketone", "alkane", "alkene", "alkyne", "esterification", "saponification",
    "exothermic", "endothermic", "lanthanide", "actinide", "photoelectric",
    "isothermal", "adiabatic", "isobaric", "isochoric", "enthalpy", "kirchhoff",
    "schrodinger", "electrostatics", "electrodynamics", "inductance",
    "capacitance", "reactance", "superconductor", "dielectric", "mitosis",
    "meiosis", "chromatid", "deoxyribonucleic", "ribonucleic", "nucleotide",
    "chloroplast", "transpiration", "homeostasis", "anabolism", "catabolism",
    "phylogeny", "histology", "cytology", "embryology", "prokaryote",
    "prokaryotic", "eukaryote", "eukaryotic", "organelle", "ribosome",
    "allosteric", "mitochondria", "endoplasmic", "golgi", "lysosome",
    "eigenvalue", "eigenvalues", "eigenvector", "eigenvectors", "laplacian",
    "stochastic", "probabilistic", "binomial", "poisson", "gaussian",
    "isomorphism", "homomorphism", "bijection", "surjection", "differentiability",
    "polymorphism", "encapsulation", "concurrency", "semaphore", "semaphores",
    "mutex", "checksum", "cryptography", "blockchain", "middleware",
    "virtualisation", "containerisation", "microservices", "preprocessor",
    "opcode", "bytecode", "runtime", "singleton", "devops", "refactoring",
    "serialisation", "deserialisation", "denormalisation", "hashing",
    "multiplexer", "demultiplexer", "microcontroller", "microprocessor",
    "mosfet", "thyristor", "triac", "flipflop", "flipflops", "tribology",
    "pneumatics", "prestressed", "cantilever", "levelling", "subgrade",
    "amortisation", "macroeconomics", "microeconomics", "oligopoly", "duopoly",
    "debenture", "debentures", "shareholding", "formulae", "radii", "loci",
    "foci", "maxima", "minima", "dataset", "datasets", "database", "databases",
    "frontend", "backend", "javascript", "python", "linux", "unix", "boolean",
}

_spell.word_frequency.load_words(SHORT_FORMS | INDIAN_WORDS | DOMAIN_WORDS)

# British -> American rewrites, tried in order on unknown words.
_UK_TO_US = [
    (re.compile(r"isation(s?)$"), r"ization\1"),
    (re.compile(r"is(e|ed|es|ing|er|ers)$"), r"iz\1"),
    (re.compile(r"ys(e|ed|es|ing|er|ers)$"), r"yz\1"),
    (re.compile(r"our(s|ed|ing|ite|ites|able|ably|ful|less|er|ers|ism|hood)?$"), r"or\1"),
    (re.compile(r"tre(s|d)?$"), r"ter\1"),
    (re.compile(r"bre(s)?$"), r"ber\1"),
    (re.compile(r"ence(s)?$"), r"ense\1"),
    (re.compile(r"ogue(s)?$"), r"og\1"),
    (re.compile(r"amme(s)?$"), r"am\1"),
    (re.compile(r"ll(ed|ing|er|ers)$"), r"l\1"),
    (re.compile(r"ae"), "e"),
    (re.compile(r"oe"), "e"),
    (re.compile(r"l$"), "ll"),          # fulfil, enrol, instil
    (re.compile(r"lment(s?)$"), r"llment\1"),
    (re.compile(r"t$"), "ed"),          # learnt, spelt, burnt
]

WORD = re.compile(r"[A-Za-z][A-Za-z'’]*[A-Za-z]|[A-Za-z]")


def _known(word: str) -> bool:
    return word in _spell


@lru_cache(maxsize=20000)
def is_valid(word: str) -> bool:
    w = word.lower().replace("’", "'")
    if w.endswith("'s"):
        w = w[:-2]
    if _known(w):
        return True
    for pattern, repl in _UK_TO_US:
        alt = pattern.sub(repl, w)
        if alt != w and _known(alt):
            return True
    # Hyphen-free compounds such as "multithreading": accept if both halves are words.
    for cut in range(3, len(w) - 2):
        if _known(w[:cut]) and _known(w[cut:]) and len(w[:cut]) > 3 and len(w[cut:]) > 3:
            return True
    return False


@lru_cache(maxsize=20000)
def suggest(word: str) -> str | None:
    fix = _spell.correction(word.lower())
    if not fix or fix == word.lower():
        return None
    if word.isupper():
        return fix.upper()
    if word[0].isupper():
        return fix.capitalize()
    return fix


def _skip_token(token: str, sentence_start: bool) -> bool:
    if len(token) <= 2:
        return True
    if token.isupper():                       # acronyms: DBMS, TCP, RBI
        return True
    if any(c.isupper() for c in token[1:]):   # camelCase / mixed: IPv4, JavaScript
        return True
    if token[0].isupper() and not sentence_start:  # proper nouns mid-sentence
        return True
    return token.lower() in SHORT_FORMS or token.lower() in EXPANDED_SHORT_FORMS


def check_text(text: str, paper_vocab: Counter | None = None) -> list[dict]:
    """Return [{word, suggestion}] for likely typos in *text* (first occurrence each)."""
    issues: list[dict] = []
    seen: set[str] = set()
    for m in WORD.finditer(text):
        token = m.group(0)
        before = text[: m.start()].rstrip()
        sentence_start = not before or before[-1] in ".?!:;)"
        # Tokens glued to digits or dots (w.r.t, 2nd, H2O) are notation, not words.
        prev_ch = text[m.start() - 1] if m.start() else " "
        next_ch = text[m.end()] if m.end() < len(text) else " "
        if prev_ch.isdigit() or next_ch.isdigit() or next_ch == "." and m.end() + 1 < len(text) and text[m.end() + 1].isalpha():
            continue
        if _skip_token(token, sentence_start):
            continue
        key = token.lower()
        if key in seen:
            continue
        # A term the paper repeats 3+ times is subject vocabulary, not a typo.
        if paper_vocab and paper_vocab.get(key, 0) >= 3:
            continue
        if is_valid(token):
            continue
        seen.add(key)
        issues.append({"word": token, "suggestion": suggest(token)})
    return issues


def paper_vocabulary(texts: list[str]) -> Counter:
    vocab: Counter = Counter()
    for t in texts:
        vocab.update(w.lower() for w in WORD.findall(t))
    return vocab


def corrected_word(word: str) -> str:
    """Best-effort correction used to normalise text before matching."""
    if len(word) <= 3 or is_valid(word):
        return word
    return (suggest(word) or word).lower()


def word_frequency(word: str) -> int:
    return _spell.word_frequency[word.lower()]
