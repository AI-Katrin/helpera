import json
import math
import os
import threading
from pathlib import Path

import numpy as np

from .config import COLD_START_THRESH, COLD_TASK_THRESHOLD, ROOT_DIR

_STATS_PATH = Path(os.environ.get("HELPERA_LINUCB_STATS", ROOT_DIR / "model_artifacts" / "linucb_stats.json"))
_MATRIX_PATH = Path(os.environ.get("HELPERA_LINUCB_MATRIX", ROOT_DIR / "model_artifacts" / "linucb_matrix.npz"))
_ALPHA = float(os.environ.get("HELPERA_LINUCB_ALPHA", "0.5"))
_LAMBDA_REG = float(os.environ.get("HELPERA_LINUCB_LAMBDA", "1.0"))
_MAX_UCB_BONUS = float(os.environ.get("HELPERA_MAX_UCB_BONUS", "0.30"))
_COLD_TASK_THRESHOLD = COLD_TASK_THRESHOLD
_COLD_VOL_THRESHOLD = 5

# Ordered feature list for LinUCB context vector x.
# Prior: A₀ = λI, b₀ = λ·w → θ₀ = w (current hand-tuned weights become Bayesian prior).
# As feedback accumulates, θ shifts toward empirically learned values.
_FEATURES: list[str] = [
    "embedding_cosine_sim",
    "format_match",
    "skill_overlap_count",
    "direction_overlap",
    "city_match",
    "task_urgency_score",
    "ngo_reliability_score",
    "task_quality_final",
    "exploration_slot",
    "cold_start_task",
    "task_is_new",
]
_PRIOR_WEIGHTS: list[float] = [1.5, 0.6, 0.5, 0.4, 0.3, 1.0, 0.8, 0.6, 0.5, 0.3, 0.2]
_D = len(_FEATURES)

_lock = threading.Lock()
_stats_cache: dict | None = None
_A: np.ndarray | None = None
_b: np.ndarray | None = None
# In-memory context store: "vol_id:task_id" → feature vector x.
# Lost on restart; reward updates silently skip if context is missing.
_context: dict[str, np.ndarray] = {}
_MAX_CONTEXT = 50_000


# ── Stats (impression counters, reward log) ──────────────────────────────────

def _load_stats() -> dict:
    global _stats_cache
    if _stats_cache is not None:
        return _stats_cache
    if _STATS_PATH.exists():
        try:
            with _STATS_PATH.open("r", encoding="utf-8") as f:
                _stats_cache = json.load(f)
                return _stats_cache
        except Exception:
            pass
    _stats_cache = {"tasks": {}, "volunteers": {}, "total_impressions": 0}
    return _stats_cache


def _save_stats(stats: dict) -> None:
    _STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _STATS_PATH.open("w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False)


# ── LinUCB matrix state ───────────────────────────────────────────────────────

def _load_matrix() -> tuple[np.ndarray, np.ndarray]:
    global _A, _b
    if _A is not None and _b is not None:
        return _A, _b
    if _MATRIX_PATH.exists():
        try:
            data = np.load(str(_MATRIX_PATH))
            _A = data["A"].astype(np.float64)
            _b = data["b"].astype(np.float64)
            return _A, _b
        except Exception:
            pass
    _A = _LAMBDA_REG * np.eye(_D, dtype=np.float64)
    _b = _LAMBDA_REG * np.array(_PRIOR_WEIGHTS, dtype=np.float64)
    return _A, _b


def _save_matrix(A: np.ndarray, b: np.ndarray) -> None:
    _MATRIX_PATH.parent.mkdir(parents=True, exist_ok=True)
    np.savez(str(_MATRIX_PATH), A=A, b=b)


def _update_linucb(x: np.ndarray, reward: float) -> None:
    """Rank-1 LinUCB update: A += xxᵀ, b += r·x. Must be called inside _lock."""
    global _A, _b
    A, b = _load_matrix()
    _A = A + np.outer(x, x)
    _b = b + reward * x
    _save_matrix(_A, _b)


# ── Context store ─────────────────────────────────────────────────────────────

def _extract_context(row: dict) -> np.ndarray:
    x = np.zeros(_D, dtype=np.float64)
    for i, feat in enumerate(_FEATURES):
        try:
            x[i] = float(row.get(feat) or 0.0)
        except (TypeError, ValueError):
            x[i] = 0.0
    return x


def record_context(volunteer_id: str, task_id: str, row: dict) -> None:
    """Store feature vector for a cold-start impression for later LinUCB update on feedback."""
    key = f"{volunteer_id}:{task_id}"
    _context[key] = _extract_context(row)
    if len(_context) > _MAX_CONTEXT:
        del _context[next(iter(_context))]


def _get_context(volunteer_id: str, task_id: str) -> np.ndarray | None:
    return _context.get(f"{volunteer_id}:{task_id}")


# ── Public scoring ────────────────────────────────────────────────────────────

def score_cold_start(row: dict, task_id: str, volunteer_id: str) -> float:
    """
    LinUCB score for cold-start volunteers: xᵀθ + α·√(xᵀA⁻¹x), capped at MAX_UCB_BONUS.
    θ = A⁻¹b is updated online from click/apply/outcome feedback.
    """
    x = _extract_context(row)
    with _lock:
        A, b = _load_matrix()
        try:
            A_inv = np.linalg.inv(A)
        except np.linalg.LinAlgError:
            A_inv = np.linalg.pinv(A)
        theta = A_inv @ b

    linear = float(x @ theta)
    ucb_bonus = min(_ALPHA * float(np.sqrt(max(float(x @ A_inv @ x), 0.0))), _MAX_UCB_BONUS)
    return round(linear + ucb_bonus, 6)


def get_cold_start_info(task_id: str, volunteer_id: str) -> tuple[int, int, float]:
    """
    Returns (is_cold_task, is_cold_volunteer, exploration_bonus).
    Used for warm volunteers: adds UCB bonus for underexplored tasks.
    """
    stats = _load_stats()
    total = max(stats.get("total_impressions", 0), 1)
    task_n = stats.get("tasks", {}).get(str(task_id), {}).get("impressions", 0)
    vol_n = stats.get("volunteers", {}).get(str(volunteer_id), {}).get("impressions", 0)

    is_cold_task = int(task_n < _COLD_TASK_THRESHOLD)
    is_cold_vol = int(vol_n < _COLD_VOL_THRESHOLD)

    bonus = 0.0
    if is_cold_task:
        bonus += _ALPHA * math.sqrt(math.log(1 + total) / (1 + task_n))
    if is_cold_vol:
        bonus += 0.3 * _ALPHA * math.sqrt(math.log(1 + total) / (1 + vol_n))
    bonus = min(bonus, _MAX_UCB_BONUS)
    return is_cold_task, is_cold_vol, round(bonus, 6)


def get_cold_task_flags_batch(task_ids) -> dict:
    """Returns dict[task_id -> is_cold_task] for a batch of tasks."""
    stats = _load_stats()
    tasks_stats = stats.get("tasks", {})
    return {
        tid: int(tasks_stats.get(str(tid), {}).get("impressions", 0) < _COLD_TASK_THRESHOLD)
        for tid in task_ids
    }


# ── Impression & feedback recording ──────────────────────────────────────────

def record_impressions(task_ids, volunteer_id: str) -> None:
    """Update impression counters after each recommendation response."""
    with _lock:
        stats = _load_stats()
        stats["total_impressions"] = stats.get("total_impressions", 0) + len(task_ids)
        tasks_dict = stats.setdefault("tasks", {})
        for tid in task_ids:
            entry = tasks_dict.setdefault(str(tid), {"impressions": 0, "clicks": 0})
            entry["impressions"] += 1
        stats.setdefault("volunteers", {}).setdefault(str(volunteer_id), {"impressions": 0})["impressions"] += 1
        _save_stats(stats)


def record_click(task_id: str, volunteer_id: str) -> None:
    """Volunteer opened a task card: reward +1."""
    with _lock:
        stats = _load_stats()
        entry = stats.setdefault("tasks", {}).setdefault(str(task_id), {"impressions": 0, "clicks": 0})
        entry["clicks"] = entry.get("clicks", 0) + 1
        entry["reward_sum"] = entry.get("reward_sum", 0.0) + 1.0
        _save_stats(stats)
        x = _get_context(volunteer_id, task_id)
        if x is not None:
            _update_linucb(x, 1.0)


def record_apply(task_id: str, volunteer_id: str) -> None:
    """Volunteer applied to a task: reward +3."""
    with _lock:
        stats = _load_stats()
        entry = stats.setdefault("tasks", {}).setdefault(str(task_id), {"impressions": 0, "clicks": 0})
        entry["applies"] = entry.get("applies", 0) + 1
        entry["reward_sum"] = entry.get("reward_sum", 0.0) + 3.0
        vol_entry = stats.setdefault("volunteers", {}).setdefault(str(volunteer_id), {"impressions": 0})
        vol_entry["applies"] = vol_entry.get("applies", 0) + 1
        _save_stats(stats)
        x = _get_context(volunteer_id, task_id)
        if x is not None:
            _update_linucb(x, 3.0)


def record_hide(task_id: str, volunteer_id: str) -> None:
    """Volunteer hid a task: reward −1."""
    with _lock:
        stats = _load_stats()
        entry = stats.setdefault("tasks", {}).setdefault(str(task_id), {"impressions": 0, "clicks": 0})
        entry["hides"] = entry.get("hides", 0) + 1
        entry["reward_sum"] = entry.get("reward_sum", 0.0) - 1.0
        _save_stats(stats)
        x = _get_context(volunteer_id, task_id)
        if x is not None:
            _update_linucb(x, -1.0)


_OUTCOME_REWARDS = {
    "completed": 5.0,
    "done": 5.0,
    "finished": 5.0,
    "partial_done": 2.0,
    "partial": 2.0,
    "cancelled": -3.0,
    "cancelled_by_volunteer": -3.0,
    "volunteer_cancelled": -3.0,
    "not_done": -2.0,
}


def record_outcome(task_id: str, volunteer_id: str, outcome_status: str) -> None:
    """Task outcome — strongest feedback signal. Rewards: +5/+2/−3/−2."""
    reward = _OUTCOME_REWARDS.get(str(outcome_status).lower(), 0.0)
    with _lock:
        stats = _load_stats()
        entry = stats.setdefault("tasks", {}).setdefault(str(task_id), {"impressions": 0, "clicks": 0})
        entry["outcomes"] = entry.get("outcomes", 0) + 1
        entry["reward_sum"] = entry.get("reward_sum", 0.0) + reward
        vol_entry = stats.setdefault("volunteers", {}).setdefault(str(volunteer_id), {"impressions": 0})
        vol_entry["outcomes"] = vol_entry.get("outcomes", 0) + 1
        vol_entry["reward_sum"] = vol_entry.get("reward_sum", 0.0) + reward
        _save_stats(stats)
        if reward != 0.0:
            x = _get_context(volunteer_id, task_id)
            if x is not None:
                _update_linucb(x, reward)


def reset_task_stats(task_id: str) -> None:
    """Reset impression counters after a task update so it re-enters exploration."""
    with _lock:
        stats = _load_stats()
        task_id_str = str(task_id)
        if task_id_str in stats.get("tasks", {}):
            stats["tasks"][task_id_str] = {"impressions": 0, "clicks": 0}
            _save_stats(stats)
