import json
from datetime import date
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .normalization import safe_float, safe_int


class SupabaseError(RuntimeError):
    pass


class SupabaseRecommendationRepository:
    def __init__(self, url, anon_key):
        self.url = url.rstrip("/")
        self.anon_key = anon_key

    def _get(self, table, params, select):
        query = dict(params)
        query["select"] = select
        endpoint = f"{self.url}/rest/v1/{table}?{urlencode(query)}"
        req = Request(
            endpoint,
            headers={
                "apikey": self.anon_key,
                "Authorization": f"Bearer {self.anon_key}",
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as error:
            body = error.read().decode("utf-8")[:300]
            raise SupabaseError(f"Supabase {error.code}: {body}") from error
        except URLError as error:
            raise SupabaseError(f"Supabase connection error: {error.reason}") from error

    # ------------------------------------------------------------------
    # Volunteer
    # ------------------------------------------------------------------

    def get_volunteer(self, volunteer_id):
        rows = self._get(
            "volunteer_profiles",
            {"id": f"eq.{volunteer_id}"},
            "id,contact,about,skills,interests,"
            "skills_clean,skills_raw,directions_clean,directions_raw,"
            "city_clean,city_raw,format_clean,age,"
            "availability_hours_week,profile_completeness,"
            "volunteer_reliability_score,volunteer_cancel_rate,active_tasks_count",
        )
        if not rows:
            return None
        return self._map_volunteer(rows[0])

    def _map_volunteer(self, row):
        about = row.get("about") or {}
        skills_json = row.get("skills") or {}
        interests = row.get("interests") or {}

        skills_text = row.get("skills_clean") or ", ".join(skills_json.get("skills") or [])
        directions_text = row.get("directions_clean") or ", ".join(skills_json.get("helpDirections") or [])
        city = row.get("city_clean") or row.get("city_raw") or about.get("city") or ""

        fmt = row.get("format_clean") or ""
        if not fmt:
            raw_fmt = interests.get("format")
            if isinstance(raw_fmt, list):
                fmt = raw_fmt[0] if raw_fmt else ""
            else:
                fmt = raw_fmt or ""

        age = safe_int(row.get("age"))
        if not age and about.get("birthDate"):
            try:
                birth = date.fromisoformat(str(about["birthDate"])[:10])
                today = date.today()
                age = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
            except (ValueError, TypeError):
                age = 0

        return {
            "volunteer_id": str(row["id"]),
            "skills": skills_text,
            "skills_raw": row.get("skills_raw") or skills_text,
            "skills_clean": row.get("skills_clean") or skills_text,
            "help_directions": directions_text,
            "directions_clean": row.get("directions_clean") or directions_text,
            "city": city,
            "city_clean": city,
            "task_format": fmt,
            "format_clean": fmt,
            "age": age,
            "availability_hours_week": safe_int(row.get("availability_hours_week")),
            "profile_completeness": safe_float(row.get("profile_completeness"), 0.5),
            "volunteer_reliability_score": safe_float(row.get("volunteer_reliability_score"), 0.5),
            "volunteer_cancel_rate": safe_float(row.get("volunteer_cancel_rate")),
            "active_tasks_count": safe_int(row.get("active_tasks_count")),
        }

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    def get_candidate_tasks(self, volunteer_id):
        rows = self._get(
            "tasks",
            {"status": "eq.published", "limit": "600"},
            "id,ngo_profile_id,title,description,format,skills,"
            "date_start,date_end,status,payload,created_at,"
            "ngo_profiles(id,org_name,about,avg_response_time_hours,ngo_reliability_score,complaint_rate)",
        )
        return [self._map_task(row) for row in (rows or [])]

    def _map_task(self, row):
        payload = row.get("payload") or {}
        ngo = row.get("ngo_profiles") or {}
        ngo_about = ngo.get("about") or {}

        return {
            "task_id": str(row["id"]),
            "ngo_id": str(row.get("ngo_profile_id") or ""),
            "title": row.get("title") or "",
            "about_task": row.get("description") or payload.get("description") or "",
            "work_to_do": payload.get("actionItems") or "",
            "useful_skills": row.get("skills") or payload.get("skills") or "",
            "direction_work": payload.get("directions") or "",
            "region": payload.get("city") or ngo_about.get("city") or "",
            "participation_type": row.get("format") or payload.get("format") or "",
            "date_start": str(row.get("date_start") or payload.get("dateStart") or ""),
            "date_end": str(row.get("date_end") or payload.get("dateEnd") or ""),
            "publication_status": row.get("status") or "published",
            "ngo_name": ngo.get("org_name") or "НКО",
            "capacity": safe_int(payload.get("capacity"), 1),
            "current_applications": 0,
            "task_quality_score": 0.0,
            "is_duplicate_candidate": 0,
            "created_at": str(row.get("created_at") or ""),
            "payload": payload,
            # keep raw NGO for get_ngos_for_tasks
            "_ngo": ngo,
            "ngo_profiles": {
                "org_name": ngo.get("org_name") or "НКО",
                "about": ngo_about,
                "contacts": {},
            },
        }

    def get_ngos_for_tasks(self, tasks):
        result = {}
        for task in tasks:
            ngo_id = task.get("ngo_id")
            if not ngo_id or ngo_id in result:
                continue
            ngo = task.get("_ngo") or {}
            result[ngo_id] = {
                "ngo_id": ngo_id,
                "ngo_name": ngo.get("org_name") or "НКО",
                "ngo_city_clean": (ngo.get("about") or {}).get("city") or "",
                "avg_response_time_hours": safe_int(ngo.get("avg_response_time_hours"), 24),
                "ngo_reliability_score": safe_float(ngo.get("ngo_reliability_score"), 0.5),
                "complaint_rate": safe_float(ngo.get("complaint_rate")),
            }
        return result
