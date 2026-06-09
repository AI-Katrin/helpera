import math
import re
from datetime import date, datetime

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .normalization import normalize_city, normalize_format, normalize_skills, safe_float, safe_int

_TFIDF_MAX_FEATURES = 3000
_TFIDF_NGRAM_RANGE = (1, 2)

# Stage 1 weights from research notebook (Optuna-tuned, 25 trials).
# ngo_reliability_score is excluded — NGO data is not joined yet at Stage 1.
_W_COSINE = 1.0
_W_SKILL_JACCARD = 0.8
_W_SKILL_COVERAGE = 0.8
_W_FORMAT_MATCH = 0.35
_W_CITY_MATCH = 0.25
_W_TASK_QUALITY = 0.25
_W_TASK_URGENCY = 0.15
_W_PROFILE_COMPLETENESS = 0.10
_W_APPLICATION_PRESSURE = -0.10


def _normalize_text(text):
    if not isinstance(text, str) or not text.strip():
        return ""
    text = text.lower().strip()
    text = re.sub(r"[^а-яёa-z0-9\s,;/-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _str(value):
    if isinstance(value, list):
        return ", ".join(str(v) for v in value if v)
    return str(value or "")


def _volunteer_text(volunteer):
    return _normalize_text(
        " ".join(
            filter(
                None,
                [
                    _str(volunteer.get("skills_clean") or volunteer.get("skills") or volunteer.get("skills_raw")),
                    _str(volunteer.get("directions_clean") or volunteer.get("help_directions")),
                    _str(volunteer.get("about") or volunteer.get("bio")),
                    _str(volunteer.get("city")),
                ],
            )
        )
    )


def _task_text(task):
    return _normalize_text(
        " ".join(
            filter(
                None,
                [
                    _str(task.get("title")),
                    _str(task.get("about_task") or task.get("description")),
                    _str(task.get("work_to_do")),
                    _str(task.get("useful_skills") or task.get("skills")),
                    _str(task.get("direction_work")),
                    _str(task.get("region") or task.get("city_raw")),
                ],
            )
        )
    )


def _parse_date(value):
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _task_urgency(task):
    deadline = _parse_date(task.get("deadline") or task.get("date_end"))
    if not deadline:
        return 0.0
    today = date.today()
    if deadline < today:
        return 0.0
    days = (deadline - today).days
    if days <= 3:
        return 1.0
    return round(math.exp(-(days - 3) / 14), 4)


def _task_quality(task):
    q = safe_float(task.get("task_quality_score"))
    if q:
        return q
    filled = sum(
        1 for name in ("title", "about_task", "work_to_do", "useful_skills", "direction_work", "date_end")
        if task.get(name)
    )
    return round(filled / 6, 3)


def compute_cosine_sims(volunteer, tasks):
    """Returns dict[task_id -> float] TF-IDF cosine similarities between volunteer and each task."""
    if not tasks:
        return {}
    task_texts = [_task_text(t) for t in tasks]
    vol_text = _volunteer_text(volunteer)

    vectorizer = TfidfVectorizer(
        max_features=_TFIDF_MAX_FEATURES,
        ngram_range=_TFIDF_NGRAM_RANGE,
        min_df=1,
    )
    task_matrix = vectorizer.fit_transform(task_texts)
    vol_vec = vectorizer.transform([vol_text])
    sims = cosine_similarity(vol_vec, task_matrix).flatten()
    return {tasks[i]["task_id"]: float(sims[i]) for i in range(len(tasks))}


def _stage1_score(volunteer, task, cosine_sim):
    """
    Weighted Stage 1 score matching the research notebook.
    Combines TF-IDF cosine with lightweight content features computable before NGO join.
    """
    vol_skills, _ = normalize_skills(
        volunteer.get("skills_clean") or volunteer.get("skills") or volunteer.get("skills_raw") or ""
    )
    task_skills, _ = normalize_skills(
        task.get("useful_skills") or task.get("skills_clean") or task.get("skills") or ""
    )
    vol_set = set(vol_skills)
    task_set = set(task_skills)
    union = vol_set | task_set
    jaccard = len(vol_set & task_set) / len(union) if union else 0.0
    coverage = len(vol_set & task_set) / len(task_set) if task_set else 0.0

    vol_fmt = normalize_format(volunteer.get("format_clean") or volunteer.get("task_format"))
    task_fmt = normalize_format(
        task.get("format_clean") or task.get("participation_type") or task.get("format")
    )
    vol_city = normalize_city(volunteer.get("city_clean") or volunteer.get("city") or "")
    task_city = normalize_city(task.get("city_clean") or task.get("region") or task.get("city_raw") or "")

    format_match = int(
        bool(vol_fmt and task_fmt and (vol_fmt == task_fmt or task_fmt == "Смешанный"))
    )
    city_match = int(
        (bool(vol_city and task_city and vol_city == task_city)) or task_fmt == "Онлайн"
    )

    quality = _task_quality(task)
    urgency = _task_urgency(task)
    completeness = safe_float(volunteer.get("profile_completeness"), 0.5)
    capacity = max(safe_int(task.get("capacity"), 1), 1)
    pressure = round(safe_int(task.get("current_applications"), 0) / capacity, 4)

    return (
        _W_COSINE * cosine_sim
        + _W_SKILL_JACCARD * jaccard
        + _W_SKILL_COVERAGE * coverage
        + _W_FORMAT_MATCH * format_match
        + _W_CITY_MATCH * city_match
        + _W_TASK_QUALITY * quality
        + _W_TASK_URGENCY * urgency
        + _W_PROFILE_COMPLETENESS * completeness
        + _W_APPLICATION_PRESSURE * pressure
    )


def select_top_candidates(volunteer, tasks, top_n):
    """
    Selects top_n tasks using a weighted Stage 1 score (TF-IDF cosine + content features).
    Returns (filtered_tasks, {task_id: tfidf_cosine_sim}).
    The returned sims dict contains raw TF-IDF cosine values — used as embedding_cosine_sim
    feature for CatBoost in Stage 2.
    """
    tfidf_sims = compute_cosine_sims(volunteer, tasks)
    if not tfidf_sims or top_n >= len(tasks):
        return tasks, tfidf_sims

    stage1_scores = {
        t["task_id"]: _stage1_score(volunteer, t, tfidf_sims.get(t["task_id"], 0.0))
        for t in tasks
    }
    sorted_tasks = sorted(tasks, key=lambda t: stage1_scores.get(t["task_id"], 0.0), reverse=True)
    top_tasks = sorted_tasks[:top_n]
    return top_tasks, {t["task_id"]: tfidf_sims[t["task_id"]] for t in top_tasks}
