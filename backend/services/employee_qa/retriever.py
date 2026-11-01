# Retrieves relevant HR sections: pure-Python BM25 plus the full-context / retrieval strategy switch
import difflib
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Protocol

from core.llm.client import estimate_tokens
from services.employee_qa.models import Section

STOPWORDS = set("""
a an and are as at be been being but by can could do does did for from had has have how i if in into is it its
me my of on or our should so than that the their them then there these they this to up us was we were what when
where which who why will with would you your yours am any some about per much many get got need want please tell
know like just also only more most other own same such very s t don doesnt isnt cant northwind labs company
""".split())

# Everyday words employees use -> words the policies use. Expansion only adds terms.
SYNONYMS = {
    "vacation": ["leave", "annual"], "holiday": ["leave", "annual"], "holidays": ["leave", "public"],
    "pto": ["leave", "annual"], "off": ["leave"], "time": [],
    "wfh": ["remote"], "home": ["remote", "home"], "telework": ["remote"], "hybrid": ["remote", "hybrid"],
    "overseas": ["abroad", "country"], "foreign": ["abroad", "country"], "travel": ["travel", "abroad"],
    "reimburse": ["expense", "claim", "reimburse"], "reimbursed": ["expense", "claim"], "refund": ["expense", "claim"],
    "receipt": ["receipt"], "computer": ["laptop"], "pc": ["laptop"], "notebook": ["laptop"],
    "ill": ["sick"], "illness": ["sick"], "doctor": ["medical", "certificate"], "note": ["certificate"],
    "maternity": ["parental", "caregiver"], "paternity": ["parental", "caregiver", "secondary"],
    "baby": ["parental", "birth"], "adoption": ["parental", "adopt"],
    "payday": ["payroll", "paid", "28th"], "salary": ["salary", "paid"], "paid": ["paid", "payroll"],
    "mfa": ["two", "factor", "authentication", "2fa"], "2fa": ["two", "factor", "authentication", "2fa"],
    "stolen": ["stolen", "lost"], "lose": ["lost"], "lost": ["lost"],
    "training": ["learning", "course"], "course": ["learning", "course"], "conference": ["learning", "conference"],
    "mentor": ["buddy"], "trial": ["probation"], "insurance": ["health", "insurance", "premium"],
    "lunch": ["meal", "voucher"], "food": ["meal", "voucher"], "desk": ["desk", "stipend"], "chair": ["chair", "stipend"],
    "stipend": ["stipend", "home"], "allowance": ["stipend", "budget", "allowance"],
    "often": ["every", "refresh"], "replace": ["refresh", "replacement"],
    "yearly": ["year", "annual"], "annually": ["year", "annual"],
}

TOKEN = re.compile(r"[a-z0-9]+")


def stem(word: str) -> str:
    # (suffix, replacement, shortest stem kept): "caring" must not become "car".
    for suffix, repl, keep in (("ies", "y", 3), ("ied", "y", 3), ("ing", "", 4), ("ed", "", 4), ("es", "", 3), ("s", "", 3)):
        if word.endswith(suffix) and len(word) - len(suffix) >= keep and not word.endswith("ss"):
            return word[: -len(suffix)] + repl
    return word


def tokenize(text: str) -> list[str]:
    return [stem(w) for w in TOKEN.findall(text.lower()) if w not in STOPWORDS]


def section_text(section: Section) -> str:
    # Headings count twice: they name what the section is about.
    head = f"{section.doc_title} {section.parent} {section.heading}"
    return f"{head} {head} {section.text}"


class BM25:
    def __init__(self, sections: list[Section], k1: float = 1.5, b: float = 0.75) -> None:
        self.sections = sections
        self.k1, self.b = k1, b
        self.docs = [Counter(tokenize(section_text(s))) for s in sections]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.avg_len = sum(self.lengths) / max(len(self.docs), 1)
        df: Counter[str] = Counter(t for d in self.docs for t in d)
        n = len(self.docs)
        self.idf = {t: math.log((n - f + 0.5) / (f + 0.5) + 1) for t, f in df.items()}
        self.vocab = sorted(self.idf)

    def query_terms(self, question: str) -> list[str]:
        terms: list[str] = []
        for word in TOKEN.findall(question.lower()):
            if word in STOPWORDS:
                continue
            expanded = [stem(word)] + [stem(s) for s in SYNONYMS.get(word, [])]
            for term in expanded:
                if term not in self.idf and len(term) >= 5:  # typo tolerance: nearest indexed word
                    close = difflib.get_close_matches(term, self.vocab, n=1, cutoff=0.8)
                    term = close[0] if close else term
                terms.append(term)
        return list(dict.fromkeys(terms))

    def scores(self, question: str) -> list[tuple[float, Section]]:
        terms = self.query_terms(question)
        result = []
        for doc, length, section in zip(self.docs, self.lengths, self.sections):
            score = 0.0
            for t in terms:
                f = doc.get(t, 0)
                if f:
                    score += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * length / self.avg_len))
            result.append((score, section))
        return sorted(result, key=lambda pair: pair[0], reverse=True)


@dataclass
class Selection:
    sections: list[Section]
    mode: str                  # "full" | "retrieval"
    top_score: float | None = None


class ContextStrategy(Protocol):
    name: str

    def select(self, question: str) -> Selection: ...


class FullContext:
    """Every accessible section goes into the prompt; the model decides what is relevant."""

    name = "full"

    def __init__(self, sections: list[Section]) -> None:
        self.sections = sections

    def select(self, question: str) -> Selection:
        return Selection(list(self.sections), "full")


class Retrieval:
    """Top-k BM25 sections above a minimum score; below it nothing is selected and no LLM call is made."""

    name = "retrieval"

    def __init__(self, sections: list[Section], top_k: int, min_score: float) -> None:
        self.index = BM25(sections)
        self.top_k = top_k
        self.min_score = min_score

    def select(self, question: str) -> Selection:
        ranked = self.index.scores(question)
        top = ranked[0][0] if ranked else 0.0
        chosen = [s for score, s in ranked[: self.top_k] if score >= self.min_score]
        return Selection(chosen, "retrieval", top)


def context_tokens(sections: list[Section]) -> int:
    return sum(estimate_tokens(section_text(s)) for s in sections)


def choose_strategy(sections: list[Section], mode: str, budget: int, top_k: int, min_score: float) -> ContextStrategy:
    """auto: full context when everything fits the token budget (best for small corpora), else retrieval."""
    if mode == "full" or (mode == "auto" and context_tokens(sections) <= budget):
        return FullContext(sections)
    if mode in ("auto", "retrieval"):
        return Retrieval(sections, top_k, min_score)
    raise ValueError(f"unknown mode {mode!r}; use auto, full or retrieval")
