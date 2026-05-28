import json
import math
import os
import threading
from pathlib import Path

from .config import COLD_START_THRESH, COLD_TASK_THRESHOLD, ROOT_DIR

_STATS_PATH = Path(os.environ.get("HELPERA_LINUCB_STATS", ROOT_DIR / "model_artifacts" / "linucb_stats.json"))
_ALPHA = float(os.environ.get("HELPERA_LINUCB_ALPHA", "0.5"))
# Правило 9: ограниченный буст — UCB-бонус не превышает MAX_UCB_BONUS,
# чтобы новые задачи не вытесняли качественные и не дестабилизировали обучение.
_MAX_UCB_BONUS = float(os.environ.get("HELPERA_MAX_UCB_BONUS", "0.30"))
_COLD_TASK_THRESHOLD = COLD_TASK_THRESHOLD
_COLD_VOL_THRESHOLD = 5

# Веса для линейного скоринга cold-start пользователей.
# Правило 7: используем и признаки задачи, и профиля/контента — чтобы персонализация
# работала даже без истории взаимодействий.
_COLD_START_FEATURE_WEIGHTS = {
    # Контентные признаки совпадения профиля с задачей
    "embedding_cosine_sim": 1.5,   # семантическое сходство текста профиля и задачи
    "format_match": 0.6,           # совпадение формата участия
    "skill_overlap_count": 0.5,    # кол-во совпадающих навыков
    "direction_overlap": 0.4,      # кол-во совпадающих направлений
    "city_match": 0.3,             # совпадение города для оффлайн-задач
    # Признаки качества задачи (когда профиль пустой — опираемся на них)
    "task_urgency_score": 1.0,
    "ngo_reliability_score": 0.8,
    "task_quality_final": 0.6,
    "task_quality_score": 0.6,
    "exploration_slot": 0.5,
    "cold_start_task": 0.3,
    "task_is_new": 0.2,
}

_lock = threading.Lock()
_cache: dict | None = None


def _load():
    global _cache
    if _cache is not None:
        return _cache
    if _STATS_PATH.exists():
        try:
            with _STATS_PATH.open("r", encoding="utf-8") as f:
                _cache = json.load(f)
                return _cache
        except Exception:
            pass
    _cache = {"tasks": {}, "volunteers": {}, "total_impressions": 0}
    return _cache


def _save(stats):
    _STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _STATS_PATH.open("w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False)


def get_cold_start_info(task_id, volunteer_id):
    """
    Returns (is_cold_task, is_cold_volunteer, exploration_bonus).
    Exploration bonus uses UCB formula: alpha * sqrt(log(1 + N) / (1 + n_task)).
    """
    stats = _load()
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

    # Правило 9: UCB-бонус не превышает MAX_UCB_BONUS — стабильность обучения.
    bonus = min(bonus, _MAX_UCB_BONUS)
    return is_cold_task, is_cold_vol, round(bonus, 6)


def record_impressions(task_ids, volunteer_id):
    """Call after each recommendation response to update LinUCB impression counts."""
    with _lock:
        stats = _load()
        stats["total_impressions"] = stats.get("total_impressions", 0) + len(task_ids)
        tasks_dict = stats.setdefault("tasks", {})
        for tid in task_ids:
            entry = tasks_dict.setdefault(str(tid), {"impressions": 0, "clicks": 0})
            entry["impressions"] += 1
        vols_dict = stats.setdefault("volunteers", {})
        vols_dict.setdefault(str(volunteer_id), {"impressions": 0})["impressions"] += 1
        _save(stats)


def get_cold_task_flags_batch(task_ids):
    """Возвращает dict[task_id -> is_cold_task] для пакета задач."""
    stats = _load()
    tasks_stats = stats.get("tasks", {})
    return {
        tid: int(tasks_stats.get(str(tid), {}).get("impressions", 0) < _COLD_TASK_THRESHOLD)
        for tid in task_ids
    }


def score_cold_start(row, task_id, volunteer_id):
    """
    Линейный контекстный скор для cold-start волонтёров (completeness < 0.4).
    Не использует персонализированные признаки — только характеристики задачи.
    Включает UCB-бонус за исследование.
    """
    stats = _load()
    total = max(stats.get("total_impressions", 0), 1)
    task_n = stats.get("tasks", {}).get(str(task_id), {}).get("impressions", 0)

    score = 0.0
    seen = set()
    for feature, weight in _COLD_START_FEATURE_WEIGHTS.items():
        if feature in seen:
            continue
        seen.add(feature)
        val = row.get(feature)
        try:
            score += weight * float(val or 0)
        except (TypeError, ValueError):
            pass

    # Правило 9: ограниченный буст — не более MAX_UCB_BONUS.
    ucb_bonus = min(_ALPHA * math.sqrt(math.log(1 + total) / (1 + task_n)), _MAX_UCB_BONUS)
    return round(score + ucb_bonus, 6)


def record_click(task_id, volunteer_id):
    """Call when a volunteer clicks a recommended task (reward signal)."""
    with _lock:
        stats = _load()
        entry = stats.setdefault("tasks", {}).setdefault(str(task_id), {"impressions": 0, "clicks": 0})
        entry["clicks"] = entry.get("clicks", 0) + 1
        entry["reward_sum"] = entry.get("reward_sum", 0.0) + 1.0
        _save(stats)


# Правило 27: Логирование — веса сигналов для формирования reward при дообучении.
# apply сильнее клика в 3 раза; outcome — сильнейший сигнал.
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


def record_apply(task_id, volunteer_id):
    """Правило 27: волонтёр откликнулся — сильный позитивный сигнал (reward +3)."""
    with _lock:
        stats = _load()
        entry = stats.setdefault("tasks", {}).setdefault(str(task_id), {"impressions": 0, "clicks": 0})
        entry["applies"] = entry.get("applies", 0) + 1
        entry["reward_sum"] = entry.get("reward_sum", 0.0) + 3.0
        vol_entry = stats.setdefault("volunteers", {}).setdefault(str(volunteer_id), {"impressions": 0})
        vol_entry["applies"] = vol_entry.get("applies", 0) + 1
        _save(stats)


def record_hide(task_id, volunteer_id):
    """Правило 27: волонтёр скрыл задачу — слабый негативный сигнал (reward −1)."""
    with _lock:
        stats = _load()
        entry = stats.setdefault("tasks", {}).setdefault(str(task_id), {"impressions": 0, "clicks": 0})
        entry["hides"] = entry.get("hides", 0) + 1
        entry["reward_sum"] = entry.get("reward_sum", 0.0) - 1.0
        _save(stats)


def record_outcome(task_id, volunteer_id, outcome_status):
    """
    Правило 27: исход задачи — самый сильный сигнал для дообучения модели.
    completed/done → +5, partial → +2, cancelled → −3, not_done → −2.
    """
    reward = _OUTCOME_REWARDS.get(str(outcome_status).lower(), 0.0)
    with _lock:
        stats = _load()
        entry = stats.setdefault("tasks", {}).setdefault(str(task_id), {"impressions": 0, "clicks": 0})
        entry["outcomes"] = entry.get("outcomes", 0) + 1
        entry["reward_sum"] = entry.get("reward_sum", 0.0) + reward
        vol_entry = stats.setdefault("volunteers", {}).setdefault(str(volunteer_id), {"impressions": 0})
        vol_entry["outcomes"] = vol_entry.get("outcomes", 0) + 1
        vol_entry["reward_sum"] = vol_entry.get("reward_sum", 0.0) + reward
        _save(stats)


def reset_task_stats(task_id):
    """Правило 4: сбрасывает счётчики показов задачи после обновления её содержимого.
    Задача снова считается cold-start и получает UCB-бонус за исследование.
    """
    with _lock:
        stats = _load()
        task_id_str = str(task_id)
        if task_id_str in stats.get("tasks", {}):
            stats["tasks"][task_id_str] = {"impressions": 0, "clicks": 0}
            _save(stats)
