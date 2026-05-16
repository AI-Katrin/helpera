import re

from .taxonomy import FORMAT_ALIASES, SKILL_ALIASES


def normalize_text(value):
    text = str(value or "").strip().lower().replace("ё", "е")
    text = re.sub(r"\s+", " ", text)
    return text


def split_list(value):
    text = str(value or "")
    if not text:
        return []
    parts = re.split(r"[,;|\n]+", text)
    return [item.strip() for item in parts if item.strip()]


def normalize_skills(value):
    normalized = []
    unknown = []
    for item in split_list(value):
        key = normalize_text(item)
        canonical = SKILL_ALIASES.get(key)
        if canonical:
            normalized.append(canonical)
        else:
            cleaned = re.sub(r"\s+", " ", item.strip())
            if cleaned:
                unknown.append(cleaned)
                normalized.append(cleaned)
    return list(dict.fromkeys(normalized)), list(dict.fromkeys(unknown))


def normalize_format(value):
    key = normalize_text(value)
    return FORMAT_ALIASES.get(key, str(value or "").strip())


def normalize_city(value):
    text = str(value or "").strip()
    return re.sub(r"\s+", " ", text).title()


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
