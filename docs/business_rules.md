# Бизнес-правила и ограничения платформы Helpera

Документ описывает все реализованные бизнес-правила системы рекомендаций волонтёрских задач.
Каждое правило сопровождается целью, местом реализации, примером кода и пояснением.

---

## Правило 1 — Валидация задачи перед публикацией

**Цель:** задача не публикуется, если не заполнены обязательные поля — это исключает «пустые» объявления из рекомендаций.

**Файл:** `server.py` → функция `_validate_task_for_publication()`

```python
def _validate_task_for_publication(data):
    """Правило 1: задача не публикуется при отсутствии обязательных полей."""
    required = ["title", "description"]
    missing = [f for f in required if not str(data.get(f) or "").strip()]
    if missing:
        return f"Не заполнены обязательные поля: {', '.join(missing)}"
    return None
```

**Комментарий:** Проверка срабатывает при `POST /api/tasks` и `PATCH /api/tasks/{id}` при попытке перевести задачу в статус `published`. Задачи без заголовка и описания остаются в черновиках.

---

## Правило 2 — Качество описания задачи

**Цель:** задачи с коротким или пустым описанием получают низкий `task_quality_score` и понижаются в рекомендациях; система также выставляет флаг `task_needs_ai_help` для подсказки НКО об AI-помощнике.

**Файл:** `backend/ml/supabase_repository.py` → `_calc_description_quality_score()`

```python
def _calc_description_quality_score(about_task, work_to_do="", ...):
    n = len(str(about_task or "").strip())
    if n < 30:
        base = 0.0          # слишком короткое — не показываем
    elif n < 80:
        base = 0.20         # warn-зона: AI-помощник обязателен
    elif n < 150:
        base = 0.45         # info-зона: желательно дополнить
    elif n < 300:
        base = 0.65
    elif n < 500:
        base = 0.80
    else:
        base = 0.90
    # Бонусы за заполненность дополнительных полей
    bonus += 0.05 if work_to_do else 0
    bonus += 0.03 if direction_work else 0
    return round(min(base + bonus, 1.0), 3)
```

**Комментарий:** Порог предупреждения — 80 символов (`< 0.45`). В `business_adjustment` оценка качества добавляет до `+0.10` к итоговому скору. Флаг `task_needs_ai_help = int(quality < 0.45)` передаётся в признаки CatBoost.

---

## Правило 3 — Дедупликация задач

**Цель:** предотвратить повторный показ практически одинаковых задач, размещённых одной НКО.

**Файл:** `server.py` → `_check_task_duplicate()`; `backend/ml/features.py` → признак `duplicate_final_flag`

```python
def _check_task_duplicate(sb_url, sb_key, ngo_id, title, description):
    """Правило 3: дедупликация — is_duplicate_candidate в payload задачи."""
    existing = _supabase_list(sb_url, sb_key, "tasks",
                              filters=[f"ngo_profile_id=eq.{ngo_id}", "status=eq.published"],
                              select="id,title,description", limit=50)
    for row in existing:
        if _text_similarity(title, row["title"]) > 0.85:
            return True
    return False
```

В признаках:

```python
"duplicate_final_flag": safe_int(task.get("is_duplicate_candidate")),
```

В `business_adjustment`:

```python
adj -= 0.15 * safe_float(get_value(row, ["duplicate_final_flag", ...], 0))
```

**Комментарий:** Задача-дубликат получает штраф `−0.15` к итоговому скору и понижается в выдаче. Жёсткая блокировка публикации не применяется — НКО может уточнить описание.

---

## Правило 4 — Сброс LinUCB при обновлении задачи

**Цель:** при изменении содержимого задачи её статистика исследования сбрасывается, и задача снова получает UCB-бонус как новая.

**Файл:** `server.py` → `PATCH /api/tasks/{id}`; `backend/ml/linucb.py` → `reset_task_stats()`

```python
def reset_task_stats(task_id):
    """Правило 4: сброс счётчиков показов после обновления задачи."""
    with _lock:
        stats = _load()
        if str(task_id) in stats.get("tasks", {}):
            stats["tasks"][str(task_id)] = {"impressions": 0, "clicks": 0}
            _save(stats)
```

В `server.py` при PATCH задачи:

```python
if any(data.get(f) for f in ("title", "description", "skills", "format")):
    reset_task_stats(task_id)   # Правило 4: задача снова cold-start
```

**Комментарий:** Учитывается и дата последнего обновления (`updated_at`) для признака `task_is_new`: задача считается новой 14 дней с момента создания **или** последнего изменения.

---

## Правило 5 — Лимит активных задач НКО

**Цель:** одна НКО не может публиковать более `MAX_NGO_TASKS` задач одновременно, чтобы не перегружать выдачу.

**Файл:** `server.py` → `_get_ngo_active_task_count()`, проверка при `POST /api/tasks`

```python
MAX_NGO_TASKS = int(os.environ.get("HELPERA_MAX_NGO_TASKS", "10"))

def _get_ngo_active_task_count(sb_url, sb_key, ngo_id):
    """Правило 5: возвращает число активных (published) задач НКО."""
    rows = _supabase_list(sb_url, sb_key, "tasks",
                          filters=[f"ngo_profile_id=eq.{ngo_id}", "status=eq.published"],
                          select="id", limit=MAX_NGO_TASKS + 1)
    return len(rows)

# При создании задачи:
if _get_ngo_active_task_count(sb_url, sb_key, ngo_id) >= MAX_NGO_TASKS:
    return json_response(self, 429, {"error": f"Достигнут лимит активных задач ({MAX_NGO_TASKS})."})
```

**Комментарий:** Лимит задаётся переменной окружения `HELPERA_MAX_NGO_TASKS` (по умолчанию 10). При превышении возвращается `HTTP 429 Too Many Requests`.

---

## Правило 6 — Жёсткие фильтры по формату и региону

**Цель:** исключить задачи, которые физически недоступны волонтёру (другой формат или город).

**Файл:** `backend/ml/business_rules.py` → `is_eligible()`

```python
def is_eligible(row):
    vol_fmt  = str(row.get("vol_format_norm") or "").strip()
    task_fmt = str(row.get("task_format_norm") or "").strip()
    vol_city  = str(row.get("vol_city_norm") or "").strip()
    task_city = str(row.get("task_city_norm") or "").strip()

    # Волонтёр хочет только онлайн, а задача требует присутствия
    if vol_fmt == "Онлайн" and task_fmt == "Оффлайн":
        return 0

    # Задача оффлайн/смешанная, оба города известны и не совпадают
    if task_fmt in ("Оффлайн", "Смешанный") and vol_city and task_city \
            and not safe_int(row.get("city_match"), 1):
        return 0

    # Волонтёр уже ведёт ≥5 активных задач — недоступен
    if safe_int(row.get("active_tasks_count")) >= 5:
        return 0

    return 1
```

**Комментарий:** Результат `is_eligible()` попадает в признак `eligible_for_recommendations`. В `business_adjustment` неподходящие задачи получают жёсткий штраф `−5.0`, фактически убирая их из выдачи.

---

## Правило 7 — Персонализация для cold-start волонтёров

**Цель:** для волонтёров с незаполненным профилем (`completeness < 0.4`) обеспечить персонализацию на основе признаков задачи и контента, не полагаясь на историю взаимодействий.

**Файл:** `backend/ml/linucb.py` → `score_cold_start()`, веса `_COLD_START_FEATURE_WEIGHTS`

```python
_COLD_START_FEATURE_WEIGHTS = {
    "embedding_cosine_sim": 1.5,   # семантическое сходство профиля и задачи
    "format_match":         0.6,   # совпадение формата участия
    "skill_overlap_count":  0.5,   # число совпадающих навыков
    "direction_overlap":    0.4,   # число совпадающих направлений
    "city_match":           0.3,   # совпадение города (для оффлайн)
    "task_urgency_score":   1.0,   # срочность задачи
    "ngo_reliability_score":0.8,   # надёжность НКО
    "task_quality_final":   0.6,   # качество описания
}

def score_cold_start(row, task_id, volunteer_id):
    score = sum(w * float(row.get(f) or 0)
                for f, w in _COLD_START_FEATURE_WEIGHTS.items())
    ucb_bonus = min(_ALPHA * sqrt(log(1 + total) / (1 + task_n)), _MAX_UCB_BONUS)
    return round(score + ucb_bonus, 6)
```

**Комментарий:** Cold-start волонтёры (completeness < `COLD_START_THRESH = 0.4`) используют линейный скоринг вместо CatBoost. Пороговое значение задаётся переменной окружения `HELPERA_COLD_START_THRESH`.

---

## Правило 8 — Слот исследования для новых задач

**Цель:** новые задачи без истории показов всегда получают хотя бы один слот в выдаче для сбора первичной статистики.

**Файл:** `backend/ml/features.py` → признак `exploration_slot`

```python
"exploration_slot": int(
    bool(cold_start_task)   # задача новая (мало показов) → всегда слот
    or (
        safe_int(task.get("current_applications")) == 0
        and stable_bucket(task.get("task_id"), 10) == 0   # 10% старых без откликов
    )
),
```

В `business_adjustment`:

```python
adj += 0.12 * safe_float(get_value(row, ["exploration_slot"], 0))
```

**Комментарий:** Признак `cold_start_task` выставляется через `get_cold_task_flags_batch()` — задача считается cold, если у неё менее `COLD_TASK_THRESHOLD` показов. Стабильный хеш-бакет обеспечивает детерминированность (одна и та же задача всегда попадает в один бакет).

---

## Правило 9 — Гарантированный слот для cold-start задачи в top-K

**Цель:** диверсификация не должна полностью вытеснять новые задачи — всегда хотя бы одна cold-start задача присутствует в выдаче; UCB-бонус ограничен сверху для стабильности обучения.

**Файл:** `backend/ml/recommender.py` → `_ensure_exploration_slot()`; `backend/ml/linucb.py`

```python
def _ensure_exploration_slot(top_rows, ranked, top_k):
    """Правило 9: если диверсификация вытеснила все cold-задачи — заменяем последний элемент."""
    has_cold = any(int(r.get("cold_start_task") or 0) for r in top_rows)
    if has_cold or len(top_rows) < top_k:
        return top_rows
    selected_ids = {r["task_id"] for r in top_rows}
    cold_candidates = [r for r in ranked
                       if int(r.get("cold_start_task") or 0)
                       and r["task_id"] not in selected_ids]
    if not cold_candidates:
        return top_rows
    return top_rows[:-1] + [cold_candidates[0]]
```

Ограничение бонуса:

```python
_MAX_UCB_BONUS = float(os.environ.get("HELPERA_MAX_UCB_BONUS", "0.30"))
bonus = min(bonus, _MAX_UCB_BONUS)   # Правило 9: новые задачи не вытесняют качественные
```

**Комментарий:** Без ограничения UCB-бонуса новые задачи с высокой неопределённостью могли бы монополизировать выдачу. Кап `0.30` настраивается переменной окружения.

---

## Правило 10 — Fallback при нулевой выдаче

**Цель:** если рекомендательная система не нашла подходящих задач, волонтёр получает персонализированные подсказки по заполнению профиля.

**Файл:** `backend/ml/recommender.py` → `_make_fallback_hints()`

```python
def _make_fallback_hints(volunteer):
    """Правило 10: до 3 конкретных рекомендаций по профилю при нулевой выдаче."""
    hints = []
    if vol_format == "Оффлайн" and not vol_city:
        hints.append("Укажите ваш город — офлайн-задачи подбираются по региону")
    if not vol_skills:
        hints.append("Добавьте навыки — система сможет точнее подобрать задачи")
    if not vol_dirs:
        hints.append("Укажите направления волонтёрства, которые вам интересны")
    if completeness < 0.6 and not hints:
        hints.append("Заполните профиль подробнее — чем больше данных, тем точнее подборка")
    if not hints:
        hints.append("Новые задачи появляются регулярно — загляните позже")
    return hints[:3]
```

**Комментарий:** Подсказки возвращаются в поле `fallback_hints` ответа API вместе с `fallback_mode: "no_tasks"`. Ответ имеет статус `200` — это не ошибка, а осознанный UI-паттерн.

---

## Правило 11 — Ограничение доли популярных задач

**Цель:** популярные задачи (много откликов) не должны вытеснять разнообразные предложения.

**Файл:** `backend/ml/recommender.py` → `_diversify()`

```python
_MAX_POPULAR_FRAC = float(os.environ.get("HELPERA_MAX_POPULAR_FRAC", "0.6"))
_POPULAR_PRESSURE_THRESHOLD = 0.5   # application_pressure ≥ 0.5 → популярная

def _diversify(ranked, top_k, ...):
    max_popular = max(1, math.ceil(top_k * _MAX_POPULAR_FRAC))
    for row in ranked:
        is_popular = float(row.get("application_pressure") or 0) >= _POPULAR_PRESSURE_THRESHOLD
        popular_ok = not is_popular or popular_count < max_popular
        if ngo_ok and dir_ok and cold_ok and popular_ok:
            selected.append(row)
            if is_popular:
                popular_count += 1
```

**Комментарий:** `application_pressure = current_applications / capacity`. При `top_k=10` не более 6 позиций могут занимать популярные задачи. Параметр настраивается переменной `HELPERA_MAX_POPULAR_FRAC`.

---

## Правило 12 — MMR-диверсификация тематик

**Цель:** принудительное разнообразие направлений (categories) в топ-выдаче — волонтёр не видит 5 задач подряд одной тематики.

**Файл:** `backend/ml/recommender.py` → `_diversity_rerank()`

```python
_DIVERSITY_LAMBDA = float(os.environ.get("HELPERA_DIVERSITY_LAMBDA", "0.25"))

def _diversity_rerank(scored_rows, lambda_div=None):
    """MMR-style re-ranking: на каждом шаге выбираем кандидата с максимальным
    final_score − lambda * (1 если направление уже представлено, 0 иначе)."""
    remaining, selected, covered = list(scored_rows), [], set()
    while remaining:
        best_idx, best_val = 0, float("-inf")
        for i, row in enumerate(remaining):
            dirs = _parse_directions(row)
            penalty = lambda_div if dirs & covered else 0.0
            val = row["final_score"] - penalty
            if val > best_val:
                best_val, best_idx = val, i
        chosen = remaining.pop(best_idx)
        selected.append(chosen)
        covered |= _parse_directions(chosen)
    return selected
```

**Комментарий:** `lambda_div=0` — чистый скоринг без диверсификации; `lambda_div=1` — максимальное разнообразие. Значение `0.25` балансирует качество и разнообразие.

---

## Правило 13 — Временной коэффициент срочности

**Цель:** задачи с близким дедлайном повышаются в выдаче; задача с дедлайном ≤3 дня получает флаг `is_urgent` для отображения на фронте.

**Файл:** `backend/ml/features.py` → `task_urgency_score`, `task_critical_urgency`

```python
# Правило 13: плавный временной коэффициент срочности.
# Максимум 1.0 при ≤3 дня, экспоненциальный спад с полупериодом 14 дней.
if deadline and not deadline_passed:
    if days_to_deadline <= 3:
        urgency = 1.0
    else:
        urgency = round(math.exp(-(days_to_deadline - 3) / 14), 4)

"task_critical_urgency": int(days_to_deadline <= 3 and not deadline_passed),
```

В `business_adjustment`:

```python
adj += 0.20 * task_urgency_score
adj += 0.10 * task_critical_urgency
```

На фронте:

```python
is_urgent = bool(row.get("task_critical_urgency")
                 or safe_float(row.get("task_urgency_score")) >= 0.7)
```

---

## Правило 14 — Штраф за ненадёжного волонтёра

**Цель:** волонтёры с высоким процентом срывов получают пониженный приоритет; критический риск (`high_risk`) даёт двойной штраф.

**Файл:** `backend/ml/features.py` → `volunteer_high_risk`; `business_rules.py` → `business_adjustment()`

```python
# Флаг высокого риска: надёжность < 0.25 ИЛИ процент срывов > 50 %
"volunteer_high_risk": int(
    volunteer_reliability_score < 0.25
    or volunteer_cancel_rate > 0.5
),
```

В `business_adjustment`:

```python
# Правило 14: квадратичный штраф за срывы (мягко при редких, жёстко при частых)
adj -= 0.30 * (cancel_rate ** 2)
adj -= 0.15 * volunteer_high_risk

# Составной штраф: высокий риск + качественная задача
if volunteer_high_risk and task_quality > 0.6:
    adj -= 0.20
elif reliability < 0.4 and task_quality > 0.7:
    adj -= 0.15
```

**Комментарий:** Квадратичный штраф: при `cancel_rate=0.3` штраф = `−0.027`, при `cancel_rate=0.7` = `−0.147`. Надёжность вычисляется в `compute_volunteer_reliability()` как комбинация статусной части (60%) и средней оценки НКО (40%).

---

## Правило 15 — Оценка скорости ответа НКО

**Цель:** НКО, которые медленно реагируют на отклики, получают штраф в рекомендациях.

**Файл:** `backend/ml/features.py` → `ngo_response_score`, `ngo_ignoring_flag`

```python
# Правило 15: непрерывная оценка скорости ответа НКО.
# Экспоненциальный спад от порога 24 ч, полупериод 48 ч.
"ngo_response_score": round(
    math.exp(-max(0, avg_response_hours - 24) / 48), 4
),
# Флаг игнорирования: нет ответа более 5 дней
"ngo_ignoring_flag": int(avg_response_hours > 120),
```

В `business_adjustment`:

```python
adj -= 0.20 * (1.0 - ngo_response_score)   # непрерывный штраф
adj -= 0.10 * ngo_ignoring_flag             # дополнительный штраф за игнорирование
adj -= 0.20 * complaint_rate                # штраф за жалобы
```

Вычисление в `supabase_repository.py`:

```python
# Надёжность НКО: скорость 50% + охват откликов 20% + оценки волонтёров 30%
reliability = min(1.0, speed_score * 0.5 + response_rate * 0.2 + avg_vol_rating * 0.3)
```

---

## Правило 16 — Градуированный штраф за перегрузку волонтёра

**Цель:** волонтёр с большим числом активных задач не получает новые рекомендации.

**Файл:** `backend/ml/features.py` → `is_overloaded`, `volunteer_nearly_overloaded`; `business_rules.py` → `is_eligible()`

```python
"is_overloaded":             int(active_tasks_count >= 3),  # штраф −0.08
"volunteer_nearly_overloaded": int(active_tasks_count >= 4),  # штраф −0.12 (доп.)

# Жёсткий блок в is_eligible():
if active_tasks_count >= 5:
    return 0   # задача полностью исключается из выдачи
```

**Комментарий:** Трёхуровневая шкала: `3+` задачи — мягкий штраф, `4+` — дополнительный штраф, `5+` — полный блок. Это снижает вероятность срывов у перегруженных волонтёров.

---

## Правило 17 — Проверка права волонтёра на отклик

**Цель:** волонтёр не может подать заявку на задачу, если нарушено одно из условий.

**Файл:** `server.py` → `_check_application_eligibility()`

```python
def _check_application_eligibility(sb_url, sb_key, task_id, volunteer_id):
    """Правило 17: проверяет право волонтёра на отклик."""
    task = _supabase_get_one(...)
    if not task or task.get("status") != "published":
        return "Задача не доступна для откликов"
    payload = task.get("payload") or {}
    deadline = payload.get("deadline") or task.get("date_end")
    if deadline and date.fromisoformat(deadline) < date.today():
        return "Дедлайн задачи истёк"
    # Проверка дубликата заявки
    existing = _supabase_list(..., filters=[
        f"task_id=eq.{task_id}",
        f"volunteer_profile_id=eq.{volunteer_id}",
        "status=neq.cancelled",
    ])
    if existing:
        return "Вы уже подали заявку на эту задачу"
    return None   # всё в порядке
```

---

## Правило 18 — Таймаут статуса «review»

**Цель:** если НКО не обработала отклик за `REVIEW_TIMEOUT_DAYS` (по умолчанию 7 дней), заявка автоматически переводится в статус `timeout`.

**Файл:** `server.py` → `_process_application_timeouts()`, `POST /api/applications/process-timeouts`

```python
REVIEW_TIMEOUT_DAYS = int(os.environ.get("HELPERA_REVIEW_TIMEOUT_DAYS", "7"))

def _process_application_timeouts(sb_url, sb_key):
    """Правило 18: переводит просроченные заявки 'review' → 'timeout'."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=REVIEW_TIMEOUT_DAYS)).isoformat()
    stale = _supabase_list(..., filters=[
        "status=eq.review",
        f"updated_at=lt.{cutoff}",
    ])
    for app in stale:
        _supabase_patch(..., {"status": "timeout"})
```

**Комментарий:** Эндпоинт `POST /api/applications/process-timeouts` вызывается по расписанию (cron) или вручную. Таймаут настраивается переменной `HELPERA_REVIEW_TIMEOUT_DAYS`.

---

## Правило 19 — Отмена заявки волонтёром

**Цель:** волонтёр может отменить заявку, но только из статусов `review` или `invite`; после отмены счётчик срывов обновляется.

**Файл:** `server.py` → `POST /api/applications/{id}/cancel`

```python
# Разрешённые для отмены статусы
CANCELLABLE = {"review", "invite", "active"}
app_row = _supabase_get_one(...)
if app_row["status"] not in CANCELLABLE:
    return json_response(self, 409, {"error": "Нельзя отменить заявку в текущем статусе"})

_supabase_patch_repr(..., {"status": "cancelled_by_volunteer"})
# Правило 27: фиксируем отмену как негативный исход (reward −3)
record_outcome(task_id, volunteer_id, "cancelled_by_volunteer")
log_event("outcome", volunteer_id, task_id, outcome_status="cancelled_by_volunteer")
```

---

## Правило 20 — Градуированная шкала исходов

**Цель:** целевая переменная для обучения ранкера отражает качество исхода задачи по трёхбалльной шкале.

**Файл:** `backend/ml/features.py` → `outcome_label_from_status()`; `backend/ml/supabase_repository.py` → `outcome_label()`

```python
def outcome_label_from_status(status: str) -> int:
    """Правило 20: целевая переменная.
    2 = выполнено полностью
    1 = выполнено частично
    0 = отменено / не выполнено
    """
    s = str(status or "").lower()
    if s in {"completed", "done", "finished"}:
        return 2
    if s in {"partial_done", "partial"}:
        return 1
    return 0
```

Влияние на скор:

```python
# Правило 20: средняя метка исхода масштабируется к [0,1] (делим на 2)
adj += 0.08 * (volunteer_avg_outcome / 2.0)
```

---

## Правило 21 — Двустороннее взаимное оценивание

**Цель:** задача закрывается только при наличии отзывов обеих сторон (волонтёра и НКО); повторный отзыв запрещён.

**Файл:** `server.py` → `POST /api/reviews`

```python
# Правило 21: валидация — все три оценки 1–10 обязательны
for field in ["quality", "communication", "responsibility"]:
    if not (1 <= int(ratings.get(field, 0)) <= 10):
        return json_response(self, 422, {"error": f"Оценка {field} должна быть от 1 до 10"})

# Повторный отзыв от той же стороны запрещён
existing_review = payload.get("reviews", {}).get(reviewer_role)
if existing_review:
    return json_response(self, 409, {"error": "Вы уже оставили отзыв"})

# Задача закрывается только при двустороннем отзыве
both_reviewed = "volunteer" in reviews and "ngo" in reviews
if both_reviewed:
    _supabase_patch(..., {"status": "completed"})
```

---

## Правило 22 — Оценка содержательности отзыва (anti-spam)

**Цель:** текстовые отзывы проверяются на содержательность; короткие или спам-подобные тексты получают низкий score и не учитываются как сигнал вовлечённости.

**Файл:** `server.py` → `_calc_review_quality_score()`

```python
def _calc_review_quality_score(text):
    """Правило 22: оценка содержательности (0.0–1.0)."""
    text = str(text or "").strip()
    if len(text) < 10:
        return 0.0
    words = text.split()
    unique_ratio = len(set(words)) / max(len(words), 1)
    length_score = min(1.0, len(text) / 200)
    # Штраф за повторяющиеся слова (спам)
    spam_penalty = 1.0 - max(0.0, 0.8 - unique_ratio)
    return round(length_score * spam_penalty, 3)

def _validate_review_quality(text, min_score=0.15):
    """Правило 22: блокируем бессодержательные отзывы."""
    if text and _calc_review_quality_score(text) < min_score:
        return "Отзыв слишком короткий или неинформативный"
    return None
```

---

## Правило 23 — Мотивационная механика: флаг расширенного отзыва

**Цель:** волонтёры, оставляющие развёрнутые отзывы, получают небольшой буст в рекомендациях — поощрение вовлечённости.

**Файл:** `server.py` → запись флага при `POST /api/reviews`; `business_rules.py` → буст

```python
# Правило 23: фиксируем флаг расширенного отзыва
review_quality = _calc_review_quality_score(text_comment)
if review_quality >= 0.5:
    _supabase_patch(..., "volunteer_profiles", volunteer_id,
                   {"volunteer_extended_review_flag": True})
```

В `business_adjustment`:

```python
# Правило 23: волонтёр с историей расширенных отзывов — вовлечённый
adj += 0.04 * volunteer_extended_review_flag
```

---

## Правило 24 — Средняя оценка волонтёра от НКО

**Цель:** агрегированный рейтинг волонтёра от НКО учитывается при вычислении `volunteer_reliability_score` и напрямую влияет на скор.

**Файл:** `backend/ml/supabase_repository.py` → `compute_volunteer_reliability()`

```python
# Агрегация оценок из отзывов НКО (ratings.quality/communication/responsibility)
if ngo_rating_sums:
    avg_ngo_rating_norm = sum(ngo_rating_sums) / len(ngo_rating_sums) / 10.0
    # Надёжность: статусная часть 60% + оценки НКО 40%
    reliability = min(1.0, status_score * 0.6 + avg_ngo_rating_norm * 0.4)
```

В `business_adjustment`:

```python
review_rating = safe_float(get_value(row, ["volunteer_review_avg_rating"], 0.7))
adj += 0.06 * max(0.0, review_rating - 0.5)   # буст при рейтинге > 0.5
```

---

## Правило 25 — Ограничение сложных задач для ненадёжных волонтёров

**Цель:** снизить вероятность срыва, рекомендуя ненадёжным волонтёрам задачи, соответствующие их уровню.

**Файлы:** `backend/ml/features.py` → вычисление сложности; `business_rules.py` → трёхуровневый штраф

Вычисление сложности в `features.py`:

```python
# Сложность задачи — комбинация навыков, объёма работы и срочности
skill_complexity = min(1.0, task_skill_count / 5.0)       # 5+ навыков → 1.0
scope_complexity = min(1.0, work_scope_len / 800.0)        # 800+ символов → 1.0
task_complexity_score = skill_complexity * 0.45 + scope_complexity * 0.35 + urgency * 0.20

# Пробел навыков: доля требуемых навыков, которых НЕТ у волонтёра
skill_gap_ratio = len(task_skills - vol_skills) / len(task_skills)

# Относительная сложность для конкретной пары (волонтёр, задача)
volunteer_complexity_mismatch = task_complexity_score * skill_gap_ratio
```

Трёхуровневый штраф в `business_adjustment`:

```python
# Уровень 3 — высокий риск (reliability < 0.25 или cancel_rate > 50 %)
if is_high_risk:
    if complexity > 0.80:   adj -= 0.35
    elif complexity > 0.65: adj -= 0.22
    elif complexity > 0.45: adj -= 0.10
# Уровень 2 — умеренная ненадёжность (reliability < 0.45 или cancel_rate > 30 %)
elif is_unreliable:
    if complexity > 0.65:   adj -= 0.12
    elif complexity > 0.45: adj -= 0.06

# Штраф за навыковый пробел при сложной задаче
if mismatch > 0.50:
    adj -= 0.08 * mismatch   # mismatch=0.6 → −0.048, mismatch=1.0 → −0.08
```

Позитивный сигнал в `make_recommendation_reason`:

```python
if task_complexity_score > 0.50 and volunteer_complexity_mismatch < 0.25:
    reasons.append("у вас есть необходимые навыки для этой задачи")
```

---

## Правило 26 — Автоматическое снятие задач после дедлайна

**Цель:** задачи с истёкшим сроком автоматически закрываются; их незакрытые заявки переводятся в `expired` (не в `cancelled`), чтобы не ухудшать рейтинг волонтёра.

**Файл:** `server.py` → `run_expire_tasks()`, `_expire_pending_applications()`

```python
def run_expire_tasks():
    """Правило 26: 5-шаговый pipeline снятия просроченных задач."""
    today = date.today().isoformat()

    # Шаг 1: получить ID задач ДО изменения статуса
    task_ids = _fetch_expiring_task_ids(url, key)

    # Шаг 2: закрыть через RPC или REST-fallback
    try:
        _call_rpc(url, key, "helpera_expire_tasks", {})
    except Exception:
        _expire_tasks_via_rest(url, key, task_ids)   # fallback

    for task_id in task_ids:
        # Шаг 3: сбросить LinUCB — задача больше не исследуется
        reset_task_stats(task_id)                     # Правило 4

        # Шаг 4: записать событие жизненного цикла
        _insert_app_event(url, key, task_id, "task_expired")

        # Шаг 5: перевести открытые заявки в 'expired' (не в 'cancelled')
        _expire_pending_applications(url, key, task_id)
```

Критическая деталь: статус заявки `expired` ≠ `cancelled_by_volunteer` — не влияет на `volunteer_cancel_rate`.

---

## Правило 27 — Структурированный лог событий взаимодействия

**Цель:** фиксировать все события (показ, клик, отклик, скрытие, исход) с весами reward для последующего дообучения CatBoost и обновления LinUCB-агрегатов.

**Двойная запись:**
- `linucb_stats.json` — агрегаты (счётчики) для UCB-скоринга в реальном времени
- `events.jsonl` — полная история событий с контекстом для offline re-training

**Файлы:** `backend/ml/event_logger.py`, `backend/ml/linucb.py`, `backend/api/recommendations.py`

Веса сигналов (reward):

```python
REWARD_MAP = {
    "impression":          0.0,   # показ без действия — слабый негативный сигнал
    "click":               1.0,   # открытие карточки
    "apply":               3.0,   # отклик на задачу
    "hide":               -1.0,   # скрытие задачи
    "outcome_completed":   5.0,   # задача выполнена — сильнейший сигнал
    "outcome_partial":     2.0,   # частичное выполнение
    "outcome_cancelled":  -3.0,   # отмена
    "outcome_not_done":   -2.0,   # не выполнено
}
```

Запись события через API:

```python
# POST /api/recommendations/events
# Body: {"event_type": "click", "task_id": "...", "volunteer_id": "...", "session_id": "..."}

# Двойная запись:
record_click(task_id, volunteer_id)          # LinUCB агрегат
log_event("click", volunteer_id, task_id,   # JSONL полное событие
          session_id=session_id, position=position)
```

Формат JSONL-записи:

```json
{
  "ts": "2025-05-28T10:00:00+00:00",
  "ev": "apply",
  "vol": "uuid-volunteer",
  "task": "uuid-task",
  "rw": 3.0,
  "sid": "uuid-session",
  "pos": 2
}
```

`session_id` связывает показы с последующими кликами/откликами для построения обучающих пар.

---

## Правило 29 — Конфиденциальность: ограничение доступа к персональным данным

**Цель:** персональные данные (контакты, email, дата рождения и пр.) не попадают во внешние API-ответы.

**Файл:** `server.py` → `_strip_pii()`, ограниченные `select` в эндпоинтах; `backend/ml/supabase_repository.py` → `_safe_task_payload()`

Рекурсивное удаление PII-ключей:

```python
_PII_KEYS = frozenset({
    "contact", "contacts", "email", "phone", "phone_number",
    "birthDate", "birth_date", "passport", "inn", "snils",
    "address", "personal_address",
})

def _strip_pii(obj):
    """Правило 29: рекурсивно удаляет PII-ключи из ответа API."""
    if isinstance(obj, dict):
        return {k: _strip_pii(v) for k, v in obj.items() if k not in _PII_KEYS}
    if isinstance(obj, list):
        return [_strip_pii(item) for item in obj]
    return obj
```

Применение по эндпоинтам:

| Эндпоинт | Ограничение |
|---|---|
| `GET /api/volunteers/{id}` | Явный select: только публичные поля; `_strip_pii()` на ответе |
| `GET /api/ngos/{id}` | Без поля `contacts`; `_strip_pii()` на `about` |
| `GET /api/tasks` | Без `contacts` в join NGO; `_strip_pii()` |
| `GET /api/tasks/{id}` | То же самое |
| `GET /api/applications/{id}` | Только `id, task_id, volunteer_profile_id, status, created/updated_at` — без `payload` с рецензиями |

Очистка payload задачи в ML-pipeline:

```python
def _safe_task_payload(payload):
    """Правило 29: payload задачи без PII-ключей."""
    return {k: v for k, v in payload.items() if k not in _TASK_PAYLOAD_PII_KEYS}

# В _map_task():
payload = _safe_task_payload(row.get("payload") or {})
```

---

## Сводная таблица правил

| № | Название | Файл | Тип воздействия |
|---|---|---|---|
| 1 | Валидация задачи | `server.py` | Блокировка публикации |
| 2 | Качество описания | `supabase_repository.py`, `features.py` | Признак, скор |
| 3 | Дедупликация задач | `server.py`, `features.py` | Штраф `−0.15` |
| 4 | Сброс LinUCB при обновлении | `server.py`, `linucb.py` | Cold-start reset |
| 5 | Лимит задач НКО | `server.py` | HTTP 429 |
| 6 | Фильтры формата/региона | `business_rules.py` | Жёсткий фильтр |
| 7 | Cold-start персонализация | `linucb.py` | Линейный скоринг |
| 8 | Слот исследования | `features.py` | Буст `+0.12` |
| 9 | Гарантированный cold-слот | `recommender.py`, `linucb.py` | UCB кап, swap |
| 10 | Fallback подсказки | `recommender.py` | Ответ с hints |
| 11 | Лимит популярных задач | `recommender.py` | Hard cap 60 % |
| 12 | MMR-диверсификация | `recommender.py` | Re-ranking |
| 13 | Срочность | `features.py`, `business_rules.py` | Буст `+0.20–0.30` |
| 14 | Штраф за ненадёжность | `features.py`, `business_rules.py` | Штраф `−0.15–0.35` |
| 15 | Скорость ответа НКО | `features.py`, `supabase_repository.py` | Штраф `−0.20` |
| 16 | Нагрузка волонтёра | `features.py`, `business_rules.py` | Штраф, блок |
| 17 | Право на отклик | `server.py` | HTTP 422 |
| 18 | Таймаут review | `server.py` | Автоматический статус |
| 19 | Отмена заявки | `server.py` | Статус + reward |
| 20 | Шкала исходов | `features.py`, `supabase_repository.py` | Целевая переменная |
| 21 | Двусторонний отзыв | `server.py` | Условие закрытия |
| 22 | Качество отзыва | `server.py` | Anti-spam |
| 23 | Флаг расширенного отзыва | `server.py`, `business_rules.py` | Буст `+0.04` |
| 24 | Рейтинг от НКО | `supabase_repository.py`, `business_rules.py` | Буст `+0.06` |
| 25 | Сложность задач | `features.py`, `business_rules.py` | Штраф `−0.06–0.35` |
| 26 | Снятие по дедлайну | `server.py` | Lifecycle pipeline |
| 27 | Лог событий | `event_logger.py`, `linucb.py` | Двойная запись |
| 29 | Конфиденциальность | `server.py`, `supabase_repository.py` | PII-фильтр |
