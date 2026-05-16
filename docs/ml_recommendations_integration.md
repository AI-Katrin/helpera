# ML-рекомендации Helpera

Модуль ранжирует задачи НКО для конкретного волонтёра: модель CatBoost YetiRank считает `ml_score`, затем обязательный слой Business Rules добавляет `business_adjustment`, а выдача сортируется по `final_score`.

## Артефакт модели

Основной артефакт ожидается здесь:

```text
model_artifacts/helpera_selected_catboost_ranker.joblib
```

Путь можно переопределить переменной окружения `HELPERA_MODEL_ARTIFACT_PATH`.

## Запуск

```bash
python3 -m pip install -r backend/requirements.txt
python3 server.py
```

Healthcheck:

```bash
curl http://localhost:3000/api/recommendations/health
```

Рекомендации:

```bash
curl "http://localhost:3000/api/recommendations/volunteers/<volunteer_uuid>?k=10"
```

`volunteer-tasks.html` запрашивает top-10, `volunteer-lk.html` запрашивает top-5. Если ML API временно недоступно, frontend сохраняет текущую локальную сортировку как fallback.

## Данные для inference

Runtime-слой сейчас читает синтетические CSV из `datasets/` и использует те же UUID, что импортёр Supabase. Позже `CsvRecommendationRepository` можно заменить репозиторием к Supabase без изменения бизнес-логики.

## События

Показы и клики пишутся через существующий `helperaDb.logEvent`. В payload добавляются `rank`, `recommendation_session_id`, `ml_score`, `business_adjustment` и `final_score`, когда они доступны.

## Business Rules

Business Rules обязательны, потому что модель не должна показывать закрытые, просроченные или переполненные задачи только из-за исторического ML-score. Корректировка учитывает срочность, качество карточки, надёжность НКО, жалобы, перегруз волонтёра и дубликаты.

## Leakage

В inference нельзя использовать outcome-признаки: `clicked`, `details_viewed`, `applied`, `accepted`, `completed`, `hidden`, `dwell_ms`, `scroll_depth_pct`.
