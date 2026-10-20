from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class AlertRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    timestamp: datetime
    device_id: str
    kind: str
    message: str
    root_cause_id: Optional[str] = None
