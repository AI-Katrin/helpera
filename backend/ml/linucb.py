import json
import math
import os
import threading
from pathlib import Path

from .config import ROOT_DIR

_STATS_PATH = Path(os.environ.get("HELPERA_LINUCB_STATS", ROOT_DIR / "model_artifacts" / "linucb_stats.json"))
_ALPHA = float(os.environ.get("HELPERA_LINUCB_ALPHA", "0.5"))
_COLD_TASK_THRESHOLD = 10
_COLD_VOL_THRESHOLD = 5

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


def record_click(task_id, volunteer_id):
    """Call when a volunteer clicks a recommended task (reward signal)."""
    with _lock:
        stats = _load()
        entry = stats.setdefault("tasks", {}).setdefault(str(task_id), {"impressions": 0, "clicks": 0})
        entry["clicks"] = entry.get("clicks", 0) + 1
        _save(stats)
