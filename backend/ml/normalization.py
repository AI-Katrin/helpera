import re
import unicodedata

from .taxonomy import CANONICAL_DIRECTIONS, CANONICAL_SKILLS, FORMAT_ALIASES, SKILL_ALIASES

try:
    import pymorphy3 as _pymorphy3
    from rapidfuzz import fuzz as _fuzz
    from rapidfuzz import process as _rfprocess
    from razdel import tokenize as _razdel_tokenize
    _morph = _pymorphy3.MorphAnalyzer()
    _USE_MORPH = True
except ImportError:
    _morph = None
    _USE_MORPH = False

_FUZZY_THRESHOLD = 65
_CANONICAL_LOWER = [s.lower() for s in CANONICAL_SKILLS]
_ALIAS_KEYS = list(SKILL_ALIASES.keys())
_ALIAS_VALS = list(SKILL_ALIASES.values())


def normalize_text(value):
    text = str(value or "").strip()
    # NFKC resolves non-breaking spaces, narrow spaces, ligatures, BOM and other
    # Unicode compatibility variants common in copy-pasted user input.
    text = unicodedata.normalize("NFKC", text)
    # Remove zero-width characters not handled by NFKC
    text = re.sub(r"[​‌‍⁠﻿]", "", text)
    text = text.lower().replace("ё", "е")
    return re.sub(r"\s+", " ", text).strip()


def split_list(value):
    text = str(value or "")
    if not text:
        return []
    parts = re.split(r"[,;|/\n]+", text)
    return [item.strip() for item in parts if item.strip()]


def _lemmatize(text: str) -> str:
    """
    Tokenize with razdel (handles Russian hyphenated compounds and punctuation),
    then lemmatize each word-token with pymorphy3.
    """
    if not _USE_MORPH or not _morph:
        return text
    tokens = [
        t.text for t in _razdel_tokenize(text)
        if any(c.isalpha() for c in t.text)
    ]
    return " ".join(_morph.parse(w)[0].normal_form for w in tokens if w)


def normalize_skills(value):
    normalized = []
    unknown = []
    for item in split_list(value):
        key = normalize_text(item)
        if not key:
            continue

        # 1. Exact match in SKILL_ALIASES
        canonical = SKILL_ALIASES.get(key)
        if canonical:
            normalized.append(canonical)
            continue

        if _USE_MORPH:
            # 2. Lemmatize whole phrase + exact match
            lemma = _lemmatize(key)
            canonical = SKILL_ALIASES.get(lemma)
            if canonical:
                normalized.append(canonical)
                continue

            # 3. Word-by-word lemmatized match + hyphen split
            #    "юридическую помощь" → "юридический" → match
            #    "smm-менеджер"       → "smm"          → SMM
            words = lemma.split()
            if len(words) == 1 and "-" in words[0]:
                words = words[0].split("-") + words
            for word in words:
                canonical = SKILL_ALIASES.get(word)
                if canonical:
                    normalized.append(canonical)
                    break
            else:
                canonical = None
            if canonical:
                continue

            # 4. Fuzzy vs SKILL_ALIASES keys — catches morphological adj variants
            #    "психологический поддержка" → 92% vs "психологическая поддержка"
            result = _rfprocess.extractOne(lemma, _ALIAS_KEYS, scorer=_fuzz.token_sort_ratio)
            if result is not None:
                _, score, idx = result
                if score >= _FUZZY_THRESHOLD:
                    normalized.append(_ALIAS_VALS[idx])
                    continue

            # 5. Fuzzy vs canonical skill names
            result = _rfprocess.extractOne(lemma, _CANONICAL_LOWER, scorer=_fuzz.token_sort_ratio)
            if result is not None:
                _, score, idx = result
                if score >= _FUZZY_THRESHOLD:
                    normalized.append(CANONICAL_SKILLS[idx])
                    continue

        # Not recognized — keep as-is (two sides with same unknown string still match)
        cleaned = re.sub(r"\s+", " ", item.strip())
        if cleaned:
            unknown.append(cleaned)
            normalized.append(cleaned)

    return list(dict.fromkeys(normalized)), list(dict.fromkeys(unknown))


_DIRECTIONS_LOWER = [d.lower() for d in CANONICAL_DIRECTIONS]
_DIR_FUZZY_THRESHOLD = 70
# Короткие слова, которые fuzzy не берёт из-за разной длины
_DIR_EXACT_FALLBACK = {
    "спорт": "спорт и зож",
    "культура": "культура и искусство",
    "медицина": "здравоохранение",
    "дети": "дети и молодёжь",
    "молодёжь": "дети и молодёжь",
    "молодежь": "дети и молодёжь",
    "бездомные": "люди без жилья",
    "пожилые": "помощь пожилым",
}


def normalize_direction(value: str) -> str:
    key = normalize_text(value)
    if not key:
        return key
    if key in _DIRECTIONS_LOWER:
        return key
    if key in _DIR_EXACT_FALLBACK:
        return _DIR_EXACT_FALLBACK[key]
    if _USE_MORPH:
        result = _rfprocess.extractOne(key, _DIRECTIONS_LOWER, scorer=_fuzz.token_sort_ratio)
        if result is not None:
            match, score, _ = result
            if score >= _DIR_FUZZY_THRESHOLD:
                return match
    return key


def normalize_format(value):
    key = normalize_text(value)
    return FORMAT_ALIASES.get(key, str(value or "").strip())


def normalize_city(value):
    text = str(value or "").strip()
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", text).strip().title()


def safe_float(value, default=0.0):
    try:
        if value in (None, ""):
            return default
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return default


def safe_int(value, default=0):
    try:
        if value in (None, ""):
            return default
        return int(float(str(value).replace(",", ".")))
    except (TypeError, ValueError):
        return default
