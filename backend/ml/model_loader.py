from functools import lru_cache

from .config import MODEL_ARTIFACT_PATH, MODEL_NAME, SCHEMA_VERSION, VARIANT_NAME


class ModelArtifactError(RuntimeError):
    pass


class ModelArtifactNotFound(ModelArtifactError):
    pass


class ModelRuntimeError(ModelArtifactError):
    pass


class ModelArtifact:
    def __init__(self, raw, path):
        self.raw = raw
        self.path = path
        self.artifact = raw.get("artifact", {}) if isinstance(raw, dict) else {}
        self.model_object = raw.get("model_object", {}) if isinstance(raw, dict) else {}
        self.model = self.model_object.get("model")
        self.preprocess = raw.get("preprocess") or self.model_object.get("preprocess")
        self.feature_cols = (
            self.artifact.get("feature_cols")
            or self.model_object.get("feature_cols")
            or []
        )
        self.model_name = self.artifact.get("selected_model_name") or MODEL_NAME
        self.variant_name = self.artifact.get("selected_variant_name") or VARIANT_NAME
        self.schema_version = self.artifact.get("schema_version") or SCHEMA_VERSION

    def validate(self):
        if not self.feature_cols:
            raise ModelRuntimeError("ML artifact has empty feature_cols.")
        if self.model is None:
            raise ModelRuntimeError("ML artifact has no model_object.model.")
        if self.preprocess is None:
            raise ModelRuntimeError("ML artifact has no preprocess.")
        return self


@lru_cache(maxsize=1)
def load_model_artifact(path=None):
    artifact_path = path or MODEL_ARTIFACT_PATH
    if not artifact_path.exists():
        raise ModelArtifactNotFound(f"ML model artifact not found: {artifact_path}")
    try:
        import joblib
    except ImportError as error:
        raise ModelRuntimeError("Python package joblib is required for ML recommendations.") from error
    try:
        loaded = joblib.load(artifact_path)
    except ModuleNotFoundError as error:
        raise ModelRuntimeError(
            f"ML artifact dependency is missing: {error.name}. Install runtime requirements."
        ) from error
    except Exception as error:
        raise ModelRuntimeError(f"Could not load ML artifact: {error}") from error
    return ModelArtifact(loaded, artifact_path).validate()


def health():
    try:
        model_artifact = load_model_artifact()
        return {
            "status": "ok",
            "model_loaded": True,
            "model_name": model_artifact.model_name,
            "variant_name": model_artifact.variant_name,
            "schema_version": model_artifact.schema_version,
            "feature_count": len(model_artifact.feature_cols),
            "artifact_path": str(model_artifact.path),
        }
    except ModelArtifactError as error:
        return {
            "status": "error",
            "model_loaded": False,
            "model_name": MODEL_NAME,
            "variant_name": VARIANT_NAME,
            "schema_version": SCHEMA_VERSION,
            "feature_count": 0,
            "artifact_path": str(MODEL_ARTIFACT_PATH),
            "error": str(error),
        }


def predict_scores(model_artifact, feature_rows, group_ids):
    try:
        import numpy as np
        import pandas as pd
        from catboost import Pool
    except ImportError as error:
        raise ModelRuntimeError(f"ML runtime dependency is missing: {error.name}") from error

    frame = pd.DataFrame(feature_rows, columns=model_artifact.feature_cols)
    frame = frame.replace([np.inf, -np.inf], np.nan)
    prepared = model_artifact.preprocess.transform(frame)
    pool = Pool(prepared, group_id=group_ids)
    return [float(value) for value in model_artifact.model.predict(pool)]
