# Deterministic offline "extractive" LLM: quotes the best-matching sentences from the supplied sections
import difflib
import html
import json
import re

from core.llm.client import FakeLLM
from services.employee_qa.retriever import TOKEN, stem, STOPWORDS, SYNONYMS

SECTION = re.compile(r'<section id="([^"]+)" title="([^"]*)" version="[^"]*">\s*(.*?)\s*</section>', re.DOTALL)
QUESTION = re.compile(r"<employee_question>\s*(.*?)\s*</employee_question>", re.DOTALL)
SENTENCE = re.compile(r"(?<=[.!?])\s+")
MIN_OVERLAP = 2
MAX_SENTENCES = 3


def _terms(text: str, expand: bool = False) -> set[str]:
    terms = set()
    for word in TOKEN.findall(text.lower()):
        if word in STOPWORDS:
            continue
        terms.add(stem(word))
        if expand:
            terms.update(stem(s) for s in SYNONYMS.get(word, []))
    return terms


def _fix_typos(terms: set[str], vocab: set[str]) -> set[str]:
    words = sorted(vocab)
    return {t if t in vocab or len(t) < 4 else (difflib.get_close_matches(t, words, n=1, cutoff=0.75) or [t])[0]
            for t in terms}


def respond(system: str, user: str, json_mode: bool = False) -> str:
    match = QUESTION.search(user)
    question = html.unescape(match.group(1)) if match else ""
    sections = SECTION.findall(user)
    vocab = set().union(*(_terms(html.unescape(t + " " + b)) for _, t, b in sections)) if sections else set()
    q_terms = _fix_typos(_terms(question, expand=True), vocab)
    # One group per question word (the word plus its synonyms): a question is answerable only when
    # enough of the asker's words are covered, not when one synonym happens to match.
    groups = [_fix_typos({stem(w)} | {stem(s) for s in SYNONYMS.get(w, [])}, vocab)
              for w in dict.fromkeys(TOKEN.findall(question.lower())) if w not in STOPWORDS]
    needed = min(MIN_OVERLAP, len(groups)) or MIN_OVERLAP
    candidates = []
    for section_id, title, body in sections:
        head = _terms(html.unescape(title))
        for sentence in SENTENCE.split(html.unescape(body)):
            words = _terms(sentence) | head
            covered = sum(bool(g & words) for g in groups)
            candidates.append((len(q_terms & words), covered, len(q_terms & _terms(sentence)),
                               section_id, sentence.strip()))
    candidates.sort(key=lambda c: (c[0], c[1], c[2]), reverse=True)  # stable: prompt order breaks ties
    if not candidates or candidates[0][1] < needed or candidates[0][2] == 0:
        return json.dumps({"answerable": False, "answer": "", "citations": [], "topic": ""})
    best = candidates[0]
    picked = [best]
    for c in candidates[1:]:  # up to two more supporting sentences, possibly from other sections
        if len(picked) == MAX_SENTENCES:
            break
        if c[0] >= max(MIN_OVERLAP, best[0] - 1) and c[1] >= needed and c[2] > 0 and c[4] not in {p[4] for p in picked}:
            picked.append(c)
    citations = list(dict.fromkeys(c[3] for c in picked))
    return json.dumps({"answerable": True, "answer": " ".join(c[4] for c in picked), "citations": citations,
                       "topic": citations[0].split("#")[0]})


def extractive_llm() -> FakeLLM:
    return FakeLLM(respond)
