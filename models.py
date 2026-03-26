from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from uuid import UUID

class IncidentIngest(BaseModel):
    source: str
    source_type: str
    platform: str
    label: Optional[str] = None
    clean_text: str

class IncidentStatusUpdate(BaseModel):
    status: str

class IncidentResponse(BaseModel):
    id: UUID
    source: str
    platform: str
    label: Optional[str]
    category: Optional[str]
    repair_urgency: str
    status: str
    created_at: datetime

class StatsResponse(BaseModel):
    total: int
    active: int
    critical: int
    avg_resolution_hours: float

class SLAMetric(BaseModel):
    department: str
    total: int
    met_sla: int
    sla_pct: float
    avg_hours: float
