from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class MetricRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    device_id: str
    timestamp: datetime
    metric_type: str
    value: Optional[float] = None
    status: Optional[str] = None
    detail: Optional[str] = None
