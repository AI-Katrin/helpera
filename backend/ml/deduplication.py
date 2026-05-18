"""
Проверка текстового сходства задач при публикации.
Использует TF-IDF косинусное сходство для обнаружения дублей.
Порог DEDUP_THRESHOLD: задачи с similarity >= порога считаются дублями.
"""
import math
import re
from collections import Counter

DEDUP_THRESHOLD = float(0.75)
_MAX_COMPARE = 500


def _tokenize(text):
    text = str(text or "").lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return [t for t in text.split() if len(t) > 2]


def _tf(tokens):
    counts = Counter(tokens)
    total = max(len(tokens), 1)
    return {term: count / total for term, count in counts.items()}


def _idf(term, documents):
    df = sum(1 for doc in documents if term in doc)
    return math.log((1 + len(documents)) / (1 + df))


def _tfidf_vector(tokens, documents):
    tf = _tf(tokens)
    return {term: weight * _idf(term, documents) for term, weight in tf.items()}


def _cosine(vec_a, vec_b):
    common = set(vec_a) & set(vec_b)
    if not common:
        return 0.0
    dot = sum(vec_a[t] * vec_b[t] for t in common)
    norm_a = math.sqrt(sum(v ** 2 for v in vec_a.values()))
    norm_b = math.sqrt(sum(v ** 2 for v in vec_b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _task_text(task):
    return " ".join(str(task.get(f) or "") for f in ("title", "description", "about_task", "work_to_do", "useful_skills"))


def check_duplicate(new_task, existing_tasks, threshold=DEDUP_THRESHOLD):
    """
    Сравнивает new_task с existing_tasks по TF-IDF cosine similarity.

    Returns:
        dict с полями:
          is_duplicate (bool)
          similarity (float, 0..1)
          most_similar_task_id (str | None)
          most_similar_score (float)
    """
    candidates = existing_tasks[:_MAX_COMPARE]
    if not candidates:
        return {"is_duplicate": False, "similarity": 0.0, "most_similar_task_id": None, "most_similar_score": 0.0}

    new_tokens = _tokenize(_task_text(new_task))
    all_token_sets = [set(_tokenize(_task_text(t))) for t in candidates]
    all_token_sets.append(set(new_tokens))

    new_vec = _tfidf_vector(new_tokens, all_token_sets)

    best_id = None
    best_score = 0.0
    for task, token_set in zip(candidates, all_token_sets):
        tokens = list(token_set)
        vec = _tfidf_vector(tokens, all_token_sets)
        score = _cosine(new_vec, vec)
        if score > best_score:
            best_score = score
            best_id = task.get("task_id") or task.get("id")

    is_dup = best_score >= threshold
    return {
        "is_duplicate": is_dup,
        "similarity": round(best_score, 4),
        "most_similar_task_id": best_id,
        "most_similar_score": round(best_score, 4),
    }
