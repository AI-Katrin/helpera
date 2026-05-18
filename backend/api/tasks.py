import json
import os

from backend.ml.data_repository import CsvRecommendationRepository
from backend.ml.deduplication import check_duplicate


def _make_repository():
    url = os.environ.get("HELPERA_SUPABASE_URL") or os.environ.get("SUPABASE_URL", "")
    key = (
        os.environ.get("HELPERA_SUPABASE_ANON_KEY")
        or os.environ.get("SUPABASE_ANON_KEY")
        or os.environ.get("SUPABASE_KEY", "")
    )
    if url and key:
        from backend.ml.supabase_repository import SupabaseRecommendationRepository
        return SupabaseRecommendationRepository(url, key)
    return CsvRecommendationRepository()


def task_duplicate_check_response(body_bytes):
    """
    POST /api/tasks/check-duplicate
    Body: {
      "task": {"title": "...", "description": "...", ...},
      "ngo_id": "optional — skip tasks from same NGO"
    }
    Returns: {"is_duplicate": bool, "similarity": float, "most_similar_task_id": str|null}
    """
    try:
        body = json.loads(body_bytes or b"{}")
    except (json.JSONDecodeError, ValueError):
        return 400, {"error": "Invalid JSON body."}

    new_task = body.get("task")
    if not new_task or not isinstance(new_task, dict):
        return 422, {"error": "Field 'task' is required and must be an object."}

    ngo_id = body.get("ngo_id")
    try:
        repo = _make_repository()
        all_tasks = repo.get_candidate_tasks(None) if hasattr(repo, "get_candidate_tasks") else []
        # Исключаем задачи той же НКО (редактирование существующей задачи)
        if ngo_id:
            all_tasks = [t for t in all_tasks if t.get("ngo_id") != ngo_id]
    except Exception:
        all_tasks = []

    result = check_duplicate(new_task, all_tasks)
    return 200, result
