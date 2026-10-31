"""Deterministic text helpers: term extraction, ambiguity rules, injection detection, contradiction heuristic."""
import re

STOP = set("""a an the is are was were be been being of to in on for and or with by as at from that this it its what which who whom how why when where
does do did can could should would will shall may might about between difference differences explain tell me please i you we they their there than then so if
into out up down over under not no yes also very more most some any each such these those them one use used using give define describe meaning mean means
work works example examples much many get gets make makes during while""".split())
DEICTIC = {"it", "this", "that", "these", "those", "them", "they", "one", "former", "latter", "same", "above"}
NUMBER_WORDS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten".split())}
NEGATIONS = {"not", "never", "cannot", "no", "without", "neither", "nor", "doesn't", "isn't", "don't", "n't"}

INJECTION_PATTERNS = [re.compile(p, re.I) for p in (
    r"ignore (all |any |the )?(previous|prior|above|earlier|your)( \w+)? (instructions|rules|prompts?)",
    r"disregard (all |any |the )?(previous|prior|above|your)",
    r"you are now\b", r"\b(admin|developer|dan|jailbreak) mode\b",
    r"(reveal|show|print|repeat) (your |the )?(system )?(prompt|instructions)",
    r"system prompt", r"new instructions?:", r"do not (cite|use) (any )?(source|evidence)s?",
    r"without (citing|using) (any )?(source|evidence)s?", r"<\s*/?\s*system\s*>", r"override (the )?(rules|policy|instructions)",
)]


def tokens(t: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", t.lower())


def stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "s", "ly"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def terms(t: str) -> set[str]:
    return {stem(w) for w in tokens(t) if w not in STOP and len(w) > 2 and w not in NUMBER_WORDS}


def sentences(t: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", t) if len(s.strip()) > 15]


def coverage(question_terms: set[str], texts: list[str]) -> float:
    if not question_terms:
        return 0.0
    have = set().union(*[terms(x) for x in texts]) if texts else set()
    # prefix match tolerates inflection (schedule/scheduling)
    hit = sum(1 for q in question_terms if q in have or any(h.startswith(q[:5]) and len(q) >= 5 for h in have))
    return round(hit / len(question_terms), 3)


def injection_hits(text: str) -> list[str]:
    return [p.pattern[:40] for p in INJECTION_PATTERNS if p.search(text)]


def is_vague(question: str) -> str | None:
    """Return a reason if the question lacks a usable referent, else None."""
    toks = tokens(question)
    ts = terms(question)
    if len(ts) == 0:
        return "no identifiable subject"
    if DEICTIC & set(toks) and len(ts) <= 1:
        return "refers to something unspecified ('it', 'this', 'that')"
    if re.search(r"\b(difference|compare|comparison|which is better|versus)\b", question.lower()) and not re.search(r"\b(between|vs\.?|versus|and|or)\b", question.lower()) and len(ts) <= 1:
        return "asks for a comparison without naming what to compare"
    return None


def _numbers(sentence: str) -> list[tuple[int, set[str]]]:
    toks = tokens(sentence)
    out = []
    for i, w in enumerate(toks):
        n = NUMBER_WORDS.get(w, int(w) if w.isdigit() else None)
        if n is not None and n >= 2:  # 'one'/'at least one' are quantifiers, not counts
            out.append((n, {stem(x) for x in toks[i + 1:i + 3] if x not in STOP}))
    return out


def find_contradiction(evidence: list[dict]) -> str | None:
    """Heuristic cross-source conflict check (numeric or negation disagreement on overlapping claims)."""
    sents = [(e, s, terms(s)) for e in evidence for s in sentences(e["text"])]
    for i, (e1, s1, t1) in enumerate(sents):
        for e2, s2, t2 in sents[i + 1:]:
            if e1["source_id"] == e2["source_id"] or len(t1) < 3 or len(t2) < 3:
                continue
            shared = len(t1 & t2)
            if shared < 4 or shared / min(len(t1), len(t2)) < 0.6:
                continue
            n1, n2 = _numbers(s1), _numbers(s2)
            for a, ca in n1:
                for b, cb in n2:
                    if a != b and ca & cb:
                        return f'"{e1["source_name"]}" and "{e2["source_name"]}" give different numbers ({a} vs {b}) for the same claim'
            neg1, neg2 = bool(NEGATIONS & set(tokens(s1))), bool(NEGATIONS & set(tokens(s2)))
            if neg1 != neg2 and shared >= 4 and shared / min(len(t1), len(t2)) >= 0.7:
                return f'"{e1["source_name"]}" and "{e2["source_name"]}" disagree on the same statement'
    return None
