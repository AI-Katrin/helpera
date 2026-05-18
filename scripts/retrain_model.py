#!/usr/bin/env python3
"""
Скрипт дообучения CatBoost YetiRank на накопленных поведенческих данных.

Использование:
  python scripts/retrain_model.py [--source csv|supabase] [--output path/to/model.joblib]

Источники данных:
  csv       — datasets/helpera_ranking_dataset.csv (локальная разработка)
  supabase  — таблица ml_ranking_examples через HELPERA_SUPABASE_URL / HELPERA_SUPABASE_ANON_KEY

Алгоритм:
  1. Загружает датасет пар (volunteer, task) с label_relevance 0..5
  2. Применяет GroupShuffleSplit по qid (volunteer_id) для изоляции пользователей
  3. Дообучает CatBoost YetiRank или обучает с нуля, если артефакт не найден
  4. Оценивает NDCG@10 на val-выборке
  5. Сохраняет артефакт через joblib в формате, совместимом с model_loader.py
"""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

try:
    import joblib
    import numpy as np
    import pandas as pd
    from catboost import CatBoostRanker, Pool
    from sklearn.model_selection import GroupShuffleSplit
except ImportError as exc:
    print(f"[retrain] Не установлена зависимость: {exc}")
    print("Установите: pip install catboost scikit-learn pandas numpy joblib")
    sys.exit(1)

from backend.ml.config import (
    DATASET_DIR,
    LEAKAGE_FEATURES,
    MODEL_ARTIFACT_PATH,
    MODEL_NAME,
    SCHEMA_VERSION,
    VARIANT_NAME,
)

# Признаки для обучения (без leakage)
FEATURE_COLS = [
    "skill_overlap_count",
    "skill_jaccard",
    "skill_coverage",
    "direction_overlap",
    "format_match",
    "city_match",
    "embedding_cosine_sim",
    "task_quality_score",
    "task_description_len",
    "task_age_days",
    "days_to_deadline",
    "task_urgency_score",
    "task_is_new",
    "task_is_duplicate_candidate",
    "capacity",
    "current_applications",
    "application_pressure",
    "task_is_full",
    "volunteer_reliability_score",
    "volunteer_cancel_rate",
    "volunteer_active_tasks_count",
    "volunteer_profile_completeness",
    "volunteer_availability_hours_week",
    "ngo_reliability_score",
    "ngo_avg_response_time_hours",
    "ngo_complaint_rate",
    "ngo_response_penalty",
    "cold_start_volunteer",
    "cold_start_task",
    "exploration_slot",
]

LABEL_COL = "label_relevance"
GROUP_COL = "qid"
MIN_SAMPLES = 50


def load_from_csv():
    path = DATASET_DIR / "helpera_ranking_dataset.csv"
    if not path.exists():
        raise FileNotFoundError(f"Датасет не найден: {path}")
    df = pd.read_csv(path)
    print(f"[retrain] CSV: загружено {len(df)} строк из {path}")
    return df


def load_from_supabase():
    url = os.environ.get("HELPERA_SUPABASE_URL") or os.environ.get("SUPABASE_URL", "")
    key = (
        os.environ.get("HELPERA_SUPABASE_ANON_KEY")
        or os.environ.get("SUPABASE_ANON_KEY")
        or os.environ.get("SUPABASE_KEY", "")
    )
    if not url or not key:
        raise EnvironmentError("Не заданы HELPERA_SUPABASE_URL и HELPERA_SUPABASE_ANON_KEY")

    from urllib.request import Request, urlopen
    limit = 10000
    offset = 0
    rows = []
    while True:
        endpoint = (
            f"{url.rstrip('/')}/rest/v1/ml_ranking_examples"
            f"?select=*&limit={limit}&offset={offset}&order=created_at.asc"
        )
        req = Request(endpoint, headers={"apikey": key, "Authorization": f"Bearer {key}"})
        with urlopen(req, timeout=60) as resp:
            batch = json.loads(resp.read().decode("utf-8"))
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
    df = pd.DataFrame(rows)
    print(f"[retrain] Supabase: загружено {len(df)} строк")
    return df


def prepare_dataset(df):
    # Убираем leakage-признаки из FEATURE_COLS
    safe_cols = [c for c in FEATURE_COLS if c not in LEAKAGE_FEATURES and c in df.columns]
    missing = [c for c in FEATURE_COLS if c not in df.columns]
    if missing:
        print(f"[retrain] Предупреждение: отсутствуют признаки {missing}, они будут пропущены")

    # Группы для ранжирования
    df = df[df[GROUP_COL].notna() & df[LABEL_COL].notna()].copy()
    df[LABEL_COL] = df[LABEL_COL].clip(lower=0).astype(int)

    # Убираем группы с менее 2 примерами (YetiRank требует >=2)
    group_sizes = df.groupby(GROUP_COL).size()
    valid_groups = group_sizes[group_sizes >= 2].index
    df = df[df[GROUP_COL].isin(valid_groups)]

    print(f"[retrain] После фильтрации: {len(df)} строк, {df[GROUP_COL].nunique()} групп")
    return df, safe_cols


def train(df, feature_cols, output_path, init_model_path=None):
    gss = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
    groups = df[GROUP_COL].values
    train_idx, val_idx = next(gss.split(df, groups=groups))

    df_train = df.iloc[train_idx].sort_values(GROUP_COL)
    df_val = df.iloc[val_idx].sort_values(GROUP_COL)

    X_train = df_train[feature_cols].fillna(0).values
    y_train = df_train[LABEL_COL].values
    g_train = df_train.groupby(GROUP_COL, sort=False).size().values

    X_val = df_val[feature_cols].fillna(0).values
    y_val = df_val[LABEL_COL].values
    g_val = df_val.groupby(GROUP_COL, sort=False).size().values

    train_pool = Pool(X_train, label=y_train, group_id=np.repeat(np.arange(len(g_train)), g_train))
    val_pool = Pool(X_val, label=y_val, group_id=np.repeat(np.arange(len(g_val)), g_val))

    params = {
        "loss_function": "YetiRank",
        "eval_metric": "NDCG:top=10",
        "iterations": 500,
        "learning_rate": 0.05,
        "depth": 6,
        "random_seed": 42,
        "verbose": 100,
        "early_stopping_rounds": 50,
        "task_type": "CPU",
    }

    model = CatBoostRanker(**params)

    # Дообучение на основе существующего артефакта, если он есть
    if init_model_path and Path(init_model_path).exists():
        print(f"[retrain] Дообучение на основе: {init_model_path}")
        try:
            prev = joblib.load(init_model_path)
            if hasattr(prev, "model") and isinstance(prev.model, CatBoostRanker):
                model = prev.model
                model.set_params(iterations=200, learning_rate=0.02)
        except Exception as exc:
            print(f"[retrain] Не удалось загрузить предыдущий артефакт: {exc}. Обучаем с нуля.")

    model.fit(train_pool, eval_set=val_pool)

    # Оценка NDCG@10
    metrics = model.eval_metrics(val_pool, ["NDCG:top=10"])
    best_ndcg = max(metrics.get("NDCG:top=10", [0]))
    print(f"[retrain] NDCG@10 на val: {best_ndcg:.4f}")

    # Сохраняем артефакт в формате, совместимом с model_loader.py
    from dataclasses import dataclass, field

    @dataclass
    class ModelArtifact:
        model: object
        feature_cols: list
        model_name: str = MODEL_NAME
        variant_name: str = VARIANT_NAME
        schema_version: str = SCHEMA_VERSION
        metrics: dict = field(default_factory=dict)

    artifact = ModelArtifact(
        model=model,
        feature_cols=feature_cols,
        metrics={"ndcg_at_10_val": round(best_ndcg, 4)},
    )
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, output_path)
    print(f"[retrain] Артефакт сохранён: {output_path}")
    return best_ndcg


def main():
    parser = argparse.ArgumentParser(description="Дообучение CatBoost YetiRank для Helpera")
    parser.add_argument("--source", choices=["csv", "supabase"], default="csv")
    parser.add_argument("--output", default=str(MODEL_ARTIFACT_PATH))
    parser.add_argument("--no-warmstart", action="store_true", help="Обучать с нуля без загрузки существующей модели")
    args = parser.parse_args()

    print(f"[retrain] Источник: {args.source}")
    df = load_from_csv() if args.source == "csv" else load_from_supabase()

    if len(df) < MIN_SAMPLES:
        print(f"[retrain] Недостаточно данных для обучения ({len(df)} строк, нужно >= {MIN_SAMPLES}). Выход.")
        sys.exit(0)

    df, feature_cols = prepare_dataset(df)
    init_path = None if args.no_warmstart else args.output
    train(df, feature_cols, args.output, init_model_path=init_path)
    print("[retrain] Готово.")


if __name__ == "__main__":
    main()
