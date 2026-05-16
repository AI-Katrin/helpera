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
