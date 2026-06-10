import os
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
DATASET_DIR = Path(os.environ.get("HELPERA_DATASET_DIR", ROOT_DIR / "datasets"))
MODEL_ARTIFACT_PATH = Path(
    os.environ.get(
        "HELPERA_MODEL_ARTIFACT_PATH",
        ROOT_DIR / "model_artifacts" / "helpera_selected_catboost_ranker.joblib",
    )
)

DEFAULT_TOP_K = int(os.environ.get("HELPERA_RECOMMENDATIONS_TOP_K", "10"))
MAX_TOP_K = int(os.environ.get("HELPERA_RECOMMENDATIONS_MAX_TOP_K", "600"))
COLD_START_THRESH = float(os.environ.get("HELPERA_COLD_START_THRESH", "0.40"))  # deprecated, kept for backward compat
COLD_TASK_THRESHOLD = int(os.environ.get("HELPERA_COLD_TASK_THRESHOLD", "10"))  # deprecated impression-based, kept for UCB bonus
# Task is cold-start if (clicks + applies) < threshold — no real interest shown yet
COLD_TASK_INTERACTION_THRESHOLD = int(os.environ.get("HELPERA_COLD_TASK_INTERACTION_THRESHOLD", "3"))
# Volunteer is cold-start if (clicks + applies) < threshold — no real interaction history yet
COLD_VOL_INTERACTION_THRESHOLD = int(os.environ.get("HELPERA_COLD_VOL_INTERACTION_THRESHOLD", "3"))
MAX_TASKS_PER_NGO = int(os.environ.get("HELPERA_MAX_TASKS_PER_NGO", "3"))
MODEL_NAME = "CatBoost YetiRank"
VARIANT_NAME = "CatBoost YetiRank + Business Rules"
SCHEMA_VERSION = "helpera_recommendations_catboost_production_v1"

LEAKAGE_FEATURES = {
    "clicked",
    "details_viewed",
    "applied",
    "accepted",
    "completed",
    "hidden",
    "dwell_ms",
    "scroll_depth_pct",
}
