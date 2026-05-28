"""
Правило 27: структурированный лог событий взаимодействия для дообучения CatBoost.

Формат: JSONL (append-only), одна запись на событие.
Используется для формирования обучающих пар при периодическом re-training модели.

Отличие от linucb_stats.json:
  linucb_stats.json — агрегаты (счётчики показов/кликов) для UCB-скоринга в реальном времени.
  events.jsonl      — полная история событий с контекстом для offline re-training.

Типы событий и их reward (целевой сигнал):
  impression  →  0.0   (показ; без дальнейшего действия — слабый негативный сигнал)
  click       → +1.0   (открытие карточки)
  apply       → +3.0   (отклик на задачу)
  hide        → −1.0   (волонтёр скрыл задачу)
  outcome     → +5/+2/−3/−2 (завершение / частично / отмена / не выполнено)

Формирование обучающих пар при re-training:
  - Объединить impressions с последующими событиями по (volunteer_id, task_id, session_id).
  - Итоговый label = max(reward) по цепочке событий для пары.
  - Label 0 (только impression, нет действий) → отрицательный пример.
"""

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from .config import ROOT_DIR

_LOG_PATH = Path(os.environ.get(
    "HELPERA_EVENT_LOG_PATH",
    str(ROOT_DIR / "model_artifacts" / "events.jsonl"),
))
# Максимальное число строк в файле; при превышении удаляется первая половина.
_MAX_LINES = int(os.environ.get("HELPERA_EVENT_LOG_MAX_LINES", "200000"))

# Веса сигналов — используются как reward при построении обучающих пар.
REWARD_MAP: dict[str, float] = {
    "impression":               0.0,
    "click":                    1.0,
    "apply":                    3.0,
    "hide":                    -1.0,
    "outcome_completed":        5.0,
    "outcome_done":             5.0,
    "outcome_finished":         5.0,
    "outcome_partial_done":     2.0,
    "outcome_partial":          2.0,
    "outcome_cancelled":       -3.0,
    "outcome_cancelled_by_volunteer": -3.0,
    "outcome_volunteer_cancelled":    -3.0,
    "outcome_not_done":        -2.0,
}

_lock = threading.Lock()


def _reward_for(event_type: str, outcome_status: str | None = None) -> float:
    if event_type == "outcome" and outcome_status:
        return REWARD_MAP.get(f"outcome_{outcome_status.lower()}", 0.0)
    return REWARD_MAP.get(event_type, 0.0)


def log_event(
    event_type: str,
    volunteer_id: str,
    task_id: str,
    *,
    session_id: str | None = None,
    ngo_id: str | None = None,
    position: int | None = None,
    ml_score: float | None = None,
    linucb_bonus: float | None = None,
    business_adjustment: float | None = None,
    final_score: float | None = None,
    outcome_status: str | None = None,
    extra: dict | None = None,
) -> None:
    """
    Записывает одно событие взаимодействия в JSONL-лог.

    Поля лога (короткие имена для экономии места):
      ts   — ISO-timestamp
      ev   — тип события
      vol  — volunteer_id
      task — task_id
      rw   — reward (целевой сигнал)
      sid  — session_id (группирует события одного сеанса рекомендаций)
      ngo  — ngo_id
      pos  — позиция в выдаче (1 = первая)
      ml   — ml_score от CatBoost
      ucb  — linucb_bonus
      adj  — business_adjustment
      fs   — final_score
      out  — outcome_status (только для outcome-событий)
      x    — произвольные доп. поля
    """
    record: dict = {
        "ts":   datetime.now(timezone.utc).isoformat(),
        "ev":   event_type,
        "vol":  str(volunteer_id),
        "task": str(task_id),
        "rw":   _reward_for(event_type, outcome_status),
    }
    if session_id is not None:
        record["sid"] = str(session_id)
    if ngo_id is not None:
        record["ngo"] = str(ngo_id)
    if position is not None:
        record["pos"] = int(position)
    if ml_score is not None:
        record["ml"] = round(float(ml_score), 6)
    if linucb_bonus is not None:
        record["ucb"] = round(float(linucb_bonus), 6)
    if business_adjustment is not None:
        record["adj"] = round(float(business_adjustment), 6)
    if final_score is not None:
        record["fs"] = round(float(final_score), 6)
    if outcome_status is not None:
        record["out"] = outcome_status
    if extra:
        record["x"] = extra

    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        with _LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        _maybe_rotate()


def log_impression_batch(session_id: str, volunteer_id: str, items) -> None:
    """
    Записывает пакет показов из одного сеанса рекомендаций.
    Каждая позиция логируется отдельно с позицией, скорами и session_id.
    items — список RecommendedTask (dataclass) или dict.
    """
    for item in items:
        if hasattr(item, "task_id"):
            log_event(
                "impression",
                volunteer_id=volunteer_id,
                task_id=item.task_id,
                session_id=session_id,
                ngo_id=item.ngo_id,
                position=item.rank,
                ml_score=item.ml_score,
                linucb_bonus=item.linucb_bonus,
                business_adjustment=item.business_adjustment,
                final_score=item.final_score,
            )
        else:
            log_event(
                "impression",
                volunteer_id=volunteer_id,
                task_id=str(item.get("task_id", "")),
                session_id=session_id,
                ngo_id=str(item.get("ngo_id", "")),
                position=item.get("rank"),
                ml_score=item.get("ml_score"),
                linucb_bonus=item.get("linucb_bonus"),
                business_adjustment=item.get("business_adjustment"),
                final_score=item.get("final_score"),
            )


def get_stats() -> dict:
    """
    Возвращает агрегированную статистику по JSONL-логу.
    Используется эндпоинтом GET /api/recommendations/events/stats.
    """
    if not _LOG_PATH.exists():
        return {
            "total_events": 0,
            "by_event_type": {},
            "log_size_bytes": 0,
            "log_path": str(_LOG_PATH),
            "max_lines": _MAX_LINES,
        }

    counts: dict[str, int] = {}
    total = 0
    try:
        with _LOG_PATH.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    ev = rec.get("ev", "unknown")
                    counts[ev] = counts.get(ev, 0) + 1
                    total += 1
                except json.JSONDecodeError:
                    continue
    except Exception:
        pass

    log_size = _LOG_PATH.stat().st_size if _LOG_PATH.exists() else 0
    return {
        "total_events": total,
        "by_event_type": counts,
        "log_size_bytes": log_size,
        "log_path": str(_LOG_PATH),
        "max_lines": _MAX_LINES,
        "utilization_pct": round(total / _MAX_LINES * 100, 1) if _MAX_LINES else 0,
    }


def _maybe_rotate() -> None:
    """
    Скользящее окно: если лог превысил MAX_LINES — удаляем первую половину.
    Вызывается внутри _lock, поэтому дополнительная блокировка не нужна.
    """
    try:
        lines = _LOG_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
        if len(lines) > _MAX_LINES:
            keep = lines[len(lines) // 2:]
            _LOG_PATH.write_text("".join(keep), encoding="utf-8")
    except Exception:
        pass
