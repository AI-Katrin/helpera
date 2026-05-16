import json
import os
from urllib.parse import parse_qs, urlparse

from backend.ml.config import DEFAULT_TOP_K
from backend.ml.data_repository import CsvRecommendationRepository
from backend.ml.linucb import record_click
from backend.ml.model_loader import ModelArtifactError, health
from backend.ml.recommender import RecommendationService, VolunteerNotFound
from backend.ml.supabase_repository import SupabaseRecommendationRepository


def _make_service():
    url = os.environ.get("HELPERA_SUPABASE_URL") or os.environ.get("SUPABASE_URL", "")
    key = (
        os.environ.get("HELPERA_SUPABASE_ANON_KEY")
        or os.environ.get("SUPABASE_ANON_KEY")
        or os.environ.get("SUPABASE_KEY", "")
    )
    if url and key:
        return RecommendationService(SupabaseRecommendationRepository(url, key))
    return RecommendationService(CsvRecommendationRepository())


_service = None


def _get_service():
    global _service
    if _service is None:
        _service = _make_service()
    return _service


def recommendations_health_response():
    return 200, health()


def recommendations_for_path(path):
    parsed = urlparse(path)
    prefix = "/api/recommendations/volunteers/"
    volunteer_id = parsed.path[len(prefix):].strip("/")
    query = parse_qs(parsed.query)
    try:
        k = int(query.get("k", [DEFAULT_TOP_K])[0] or DEFAULT_TOP_K)
    except (TypeError, ValueError):
        return 422, {"error": "Query parameter k must be an integer."}
    if not volunteer_id:
        return 422, {"error": "volunteer_id is required."}
    try:
        response = _get_service().recommend_for_volunteer(volunteer_id, k)
        return 200, response.to_dict()
    except VolunteerNotFound as error:
        return 404, {"error": str(error)}
    except ModelArtifactError as error:
        return 503, {"error": str(error)}
    except ValueError as error:
        return 422, {"error": str(error)}


def recommendations_event_response(body_bytes):
    """
    POST /api/recommendations/events
    Body: {"event_type": "click", "task_id": "...", "volunteer_id": "..."}
    """
    try:
        body = json.loads(body_bytes or b"{}")
    except (json.JSONDecodeError, ValueError):
        return 400, {"error": "Invalid JSON body."}

    event_type = body.get("event_type")
    task_id = body.get("task_id")
    volunteer_id = body.get("volunteer_id")

    if not event_type or not task_id or not volunteer_id:
        return 422, {"error": "Fields event_type, task_id, volunteer_id are required."}

    if event_type == "click":
        record_click(task_id, volunteer_id)

    return 200, {"ok": True}
