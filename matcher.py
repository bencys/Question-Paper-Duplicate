"""Cluster exact, spelling-near, and reworded questions."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from rapidfuzz import fuzz
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from extractor import ExtractedQuestion

FILLER = re.compile(
    r"\b("
    r"briefly|explain|describe|discuss|define|write|short|note|notes|on|about|"
    r"what|is|are|the|a|an|of|to|in|for|with|and|or|do|does|how|why|from|"
    r"answer|following|any|two|three|four|five|"
    r"state|mention|list|give|differentiate|distinguish|between|"
    r"comment|elaborate|illustrate|justify|compare|used|its|main"
    r")\b",
    re.IGNORECASE,
)

STEM_SUFFIXES = (
    "ences",
    "ence",
    "ances",
    "ance",
    "ations",
    "ation",
    "ments",
    "ment",
    "ness",
    "ings",
    "ing",
    "ers",
    "ied",
    "ies",
    "ed",
    "es",
    "s",
)


def _stem(word: str) -> str:
    w = word
    if len(w) <= 4:
        return w
    for suf in STEM_SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[: -len(suf)]
    return w

PUNCT = re.compile(r"[^\w\s]")
MULTI_SPACE = re.compile(r"\s+")


class DSU:
    def __init__(self, n: int):
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            self.parent[ra] = rb
        elif self.rank[ra] > self.rank[rb]:
            self.parent[rb] = ra
        else:
            self.parent[rb] = ra
            self.rank[ra] += 1


def normalize(text: str) -> str:
    t = text.lower().replace("\u2019", "'").replace("\u2018", "'")
    t = t.replace("\u201c", '"').replace("\u201d", '"')
    t = PUNCT.sub(" ", t)
    t = MULTI_SPACE.sub(" ", t).strip()
    return t


def content_key(text: str) -> str:
    t = normalize(text)
    t = FILLER.sub(" ", t)
    tokens = [_stem(tok) for tok in t.split() if tok]
    return " ".join(tokens)


@dataclass
class MatchLink:
    left: int
    right: int
    kind: str
    score: float


def _tfidf_pairs(texts: list[str], threshold: float = 0.52) -> list[tuple[int, int, float]]:
    if len(texts) < 2:
        return []
    vectorizer = TfidfVectorizer(
        ngram_range=(1, 2),
        min_df=1,
        stop_words="english",
        sublinear_tf=True,
    )
    try:
        matrix = vectorizer.fit_transform(texts)
    except ValueError:
        return []
    sim = cosine_similarity(matrix)
    pairs: list[tuple[int, int, float]] = []
    n = len(texts)
    for i in range(n):
        for j in range(i + 1, n):
            score = float(sim[i, j])
            if score >= threshold:
                pairs.append((i, j, score))
    return pairs


def find_matches(questions: list[ExtractedQuestion]) -> dict:
    n = len(questions)
    norms = [normalize(q.text) for q in questions]
    keys = [content_key(q.text) or norms[i] for i, q in enumerate(questions)]
    dsu = DSU(n)
    links: list[MatchLink] = []
    best: dict[tuple[int, int], MatchLink] = {}

    def add_link(i: int, j: int, kind: str, score: float) -> None:
        a, b = (i, j) if i < j else (j, i)
        prev = best.get((a, b))
        rank = {"exact": 3, "spelling": 2, "similar": 1}
        if prev and rank[prev.kind] >= rank[kind]:
            if prev.kind == kind:
                prev.score = max(prev.score, score)
            return
        link = MatchLink(a, b, kind, score)
        best[(a, b)] = link
        dsu.union(a, b)

    by_norm: dict[str, list[int]] = defaultdict(list)
    for i, t in enumerate(norms):
        if t:
            by_norm[t].append(i)
    for idxs in by_norm.values():
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                add_link(idxs[a], idxs[b], "exact", 100.0)

    by_key: dict[str, list[int]] = defaultdict(list)
    for i, t in enumerate(keys):
        if t:
            by_key[t].append(i)
    for idxs in by_key.values():
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                if norms[idxs[a]] != norms[idxs[b]]:
                    add_link(idxs[a], idxs[b], "similar", 96.0)

    for i in range(n):
        for j in range(i + 1, n):
            if dsu.find(i) == dsu.find(j) and (i, j) in best and best[(i, j)].kind == "exact":
                continue
            ratio = fuzz.token_set_ratio(norms[i], norms[j])
            partial = fuzz.token_sort_ratio(norms[i], norms[j])
            score = max(ratio, partial)
            key_ratio = fuzz.token_set_ratio(keys[i], keys[j])
            if score >= 90:
                kind = "spelling" if score >= 93 else "similar"
                add_link(i, j, kind, float(score))
            elif key_ratio >= 86:
                add_link(i, j, "similar", float(key_ratio))
            elif score >= 82 and fuzz.partial_ratio(keys[i], keys[j]) >= 90:
                add_link(i, j, "similar", float(score))

    for i, j, score in _tfidf_pairs(keys):
        add_link(i, j, "similar", round(score * 100, 1))

    links = list(best.values())
    groups_map: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        groups_map[dsu.find(i)].append(i)

    groups = []
    for members in groups_map.values():
        if len(members) < 2:
            continue
        member_links = [lk for lk in links if lk.left in members and lk.right in members]
        kinds = {lk.kind for lk in member_links}
        if kinds == {"exact"} or (kinds <= {"exact", "spelling"} and "similar" not in kinds):
            label = "Repeated (same / spelling)"
            bucket = "repeated"
        else:
            label = "Similar meaning (reworded)"
            bucket = "similar"
        items = []
        for idx in sorted(members, key=lambda k: _sort_num(questions[k].number)):
            others = [questions[k].number for k in members if k != idx]
            items.append(
                {
                    "number": questions[idx].number,
                    "text": questions[idx].text,
                    "repeats_of": others,
                }
            )
        max_score = max((lk.score for lk in member_links), default=0)
        groups.append(
            {
                "type": bucket,
                "label": label,
                "score": round(max_score, 1),
                "question_numbers": [it["number"] for it in items],
                "questions": items,
            }
        )

    groups.sort(key=lambda g: (0 if g["type"] == "repeated" else 1, -g["score"]))
    unique = n - sum(len(g["questions"]) - 1 for g in groups)
    return {
        "total": n,
        "unique_estimate": unique,
        "repeated_groups": [g for g in groups if g["type"] == "repeated"],
        "similar_groups": [g for g in groups if g["type"] == "similar"],
        "questions": [{"number": q.number, "text": q.text} for q in questions],
    }


def _sort_num(num: str):
    m = re.match(r"(\d+)", str(num))
    return (int(m.group(1)) if m else 10**9, str(num))
