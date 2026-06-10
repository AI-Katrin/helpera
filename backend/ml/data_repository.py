import csv
import uuid
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

from .config import DATASET_DIR
from .normalization import safe_float, safe_int


def _deadline_passed(task) -> bool:
    raw = str(task.get("date_end") or task.get("deadline") or "").strip()
    if not raw:
        return False
    # Supabase returns ISO format "2026-06-09T10:30:00.000Z" — take date part only
    raw = raw[:10]
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(raw, fmt).date() < date.today()
        except ValueError:
            continue
    return False


def _task_is_full(task) -> bool:
    capacity = max(safe_int(task.get("capacity"), 1), 1)
    return safe_int(task.get("current_applications")) >= capacity


def pre_filter_tasks(tasks: list) -> list:
    """
    Hard pre-pipeline filter: removes tasks that can never appear in recommendations
    regardless of volunteer profile. Keeps tasks with unknown/missing deadline (no deadline = open).
    """
    result = []
    for t in tasks:
        status = str(t.get("publication_status") or "published").lower()
        if status not in {"published", "active"}:
            continue
        if _deadline_passed(t):
            continue
        if _task_is_full(t):
            continue
        if safe_int(t.get("is_duplicate_candidate")):
            continue
        result.append(t)
    return result

UUID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://helpera.synthetic")


def synthetic_uuid(kind, source_id):
    return str(uuid.uuid5(UUID_NAMESPACE, f"{kind}:{source_id}"))


def read_csv(name):
    path = Path(DATASET_DIR) / name
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


class CsvRecommendationRepository:
    @lru_cache(maxsize=1)
    def volunteers(self):
        rows = {}
        for row in read_csv("helpera_synthetic_volunteers.csv"):
            source_id = row["volunteer_id"]
            row = dict(row)
            row["source_volunteer_id"] = source_id
            row["volunteer_id"] = synthetic_uuid("volunteer", source_id)
            row["availability_hours_week"] = safe_int(row.get("availability_hours_week"))
            row["profile_completeness"] = safe_float(row.get("profile_completeness"))
            row["volunteer_reliability_score"] = safe_float(row.get("volunteer_reliability_score"), 0.5)
            row["volunteer_cancel_rate"] = safe_float(row.get("volunteer_cancel_rate"))
            row["active_tasks_count"] = safe_int(row.get("active_tasks_count"))
            rows[row["volunteer_id"]] = row
            rows[source_id] = row
        return rows

    @lru_cache(maxsize=1)
    def ngos(self):
        rows = {}
        for row in read_csv("helpera_synthetic_ngos.csv"):
            source_id = row["ngo_id"]
            row = dict(row)
            row["source_ngo_id"] = source_id
            row["ngo_id"] = synthetic_uuid("ngo", source_id)
            row["avg_response_time_hours"] = safe_int(row.get("avg_response_time_hours"), 24)
            row["ngo_reliability_score"] = safe_float(row.get("ngo_reliability_score"), 0.5)
            row["complaint_rate"] = safe_float(row.get("complaint_rate"))
            row["active_tasks_count"] = safe_int(row.get("active_tasks_count"))
            rows[row["ngo_id"]] = row
            rows[source_id] = row
        return rows

    @lru_cache(maxsize=1)
    def tasks(self):
        ngos = self.ngos()
        rows = []
        for row in read_csv("helpera_synthetic_tasks.csv"):
            source_id = row["task_id"]
            source_ngo_id = row["ngo_id"]
            ngo = ngos.get(source_ngo_id) or {}
            item = dict(row)
            item["source_task_id"] = source_id
            item["source_ngo_id"] = source_ngo_id
            item["task_id"] = synthetic_uuid("task", source_id)
            item["ngo_id"] = synthetic_uuid("ngo", source_ngo_id)
            item["ngo_name"] = item.get("ngo_name") or ngo.get("ngo_name") or "НКО"
            item["publication_status"] = item.get("publication_status") or "published"
            item["task_quality_score"] = safe_float(item.get("task_quality_score"))
            item["is_duplicate_candidate"] = safe_int(item.get("is_duplicate_candidate"))
            item["capacity"] = max(safe_int(item.get("capacity"), 1), 1)
            item["current_applications"] = safe_int(item.get("current_applications"))
            item["description"] = item.get("about_task") or item.get("description") or ""
            item["format"] = item.get("participation_type") or item.get("format_clean") or item.get("format_raw") or ""
            item["skills"] = item.get("useful_skills") or item.get("skills_clean") or item.get("skills_raw") or ""
            item["payload"] = {
                "syntheticId": source_id,
                "ngoSyntheticId": source_ngo_id,
                "description": item.get("about_task") or "",
                "comment": item.get("requirements_raw") or "",
                "actionItems": item.get("work_to_do") or "",
                "directions": item.get("direction_work") or item.get("directions_clean") or "",
                "city": item.get("region") or item.get("city_clean") or "",
                "dateStart": item.get("date_start") or "",
                "dateEnd": item.get("date_end") or item.get("deadline") or "",
                "format": item["format"],
                "skills": item["skills"],
            }
            item["ngo_profiles"] = {
                "org_name": item["ngo_name"],
                "about": {"city": ngo.get("ngo_city_clean") or item.get("region") or ""},
                "contacts": {},
            }
            rows.append(item)
        return rows

    def get_volunteer(self, volunteer_id):
        return self.volunteers().get(str(volunteer_id))

    def get_candidate_tasks(self, volunteer_id):
        return pre_filter_tasks(self.tasks())

    def get_ngos_for_tasks(self, tasks):
        ngos = self.ngos()
        return {task["ngo_id"]: ngos.get(task["ngo_id"], {}) for task in tasks}
