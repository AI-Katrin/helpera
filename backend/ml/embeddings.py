from functools import lru_cache

import numpy as np

_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
_EMBEDDING_DIM = 384


@lru_cache(maxsize=1)
def _load_model():
    try:
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer(_MODEL_NAME)
    except ImportError:
        return None


def embed(texts):
    """Returns L2-normalised float32 embeddings (N, D). Falls back to zeros if unavailable."""
    if not texts:
        return np.zeros((0, _EMBEDDING_DIM), dtype=np.float32)
    model = _load_model()
    if model is None:
        return np.zeros((len(texts), _EMBEDDING_DIM), dtype=np.float32)
    result = model.encode(texts, normalize_embeddings=True, show_progress_bar=False, batch_size=64)
    return np.array(result, dtype=np.float32)


def _volunteer_text(volunteer):
    return " ".join(
        filter(
            None,
            [
                volunteer.get("skills_clean") or volunteer.get("skills") or volunteer.get("skills_raw") or "",
                volunteer.get("directions_clean") or volunteer.get("help_directions") or "",
                volunteer.get("about") or volunteer.get("bio") or "",
                volunteer.get("city") or "",
            ],
        )
    ).strip()


def _task_text(task):
    return " ".join(
        filter(
            None,
            [
                task.get("title") or "",
                task.get("about_task") or task.get("description") or "",
                task.get("work_to_do") or "",
                task.get("useful_skills") or task.get("skills") or "",
                task.get("direction_work") or "",
                task.get("region") or task.get("city_raw") or "",
            ],
        )
    ).strip()


def compute_cosine_sims(volunteer, tasks):
    """Returns dict[task_id -> float] cosine similarities between volunteer and each task."""
    if not tasks:
        return {}
    vol_text = _volunteer_text(volunteer)
    task_texts = [_task_text(t) for t in tasks]
    all_embs = embed([vol_text] + task_texts)
    vol_emb = all_embs[0]
    task_embs = all_embs[1:]
    sims = task_embs @ vol_emb  # dot product of unit vectors == cosine sim
    return {tasks[i]["task_id"]: float(sims[i]) for i in range(len(tasks))}


def select_top_candidates(volunteer, tasks, top_n):
    """
    Selects top_n tasks by semantic similarity to volunteer profile.
    Returns (filtered_tasks, {task_id: cosine_sim}).
    Falls back to all tasks when sentence-transformers is unavailable.
    """
    sims = compute_cosine_sims(volunteer, tasks)
    if not sims or top_n >= len(tasks):
        return tasks, sims
    sorted_tasks = sorted(tasks, key=lambda t: sims.get(t["task_id"], 0.0), reverse=True)
    top_tasks = sorted_tasks[:top_n]
    return top_tasks, {t["task_id"]: sims[t["task_id"]] for t in top_tasks}
