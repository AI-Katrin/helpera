from dataclasses import asdict, dataclass, field


@dataclass
class RecommendedTask:
    rank: int
    task_id: str
    ngo_id: str
    title: str
    about_task: str
    work_to_do: str
    useful_skills: str
    direction_work: str
    region: str
    date_start: str
    date_end: str
    participation_type: str
    ngo_name: str
    ml_score: float
    business_adjustment: float
    final_score: float
    match_percent: int
    reason: str
    payload: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


@dataclass
class RecommendationResponse:
    volunteer_id: str
    k: int
    model_name: str
    variant_name: str
    schema_version: str
    recommendation_session_id: str
    items: list

    def to_dict(self):
        data = asdict(self)
        data["items"] = [item.to_dict() if hasattr(item, "to_dict") else item for item in self.items]
        return data
