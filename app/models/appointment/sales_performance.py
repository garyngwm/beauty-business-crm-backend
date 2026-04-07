from pydantic import BaseModel
from typing import List, Literal

class SalesPerformancePoint(BaseModel):
    date: str
    revenue: float
    count: int

class SalesPerformanceResponse(BaseModel):
    groupBy: Literal["day", "month"]
    points: List[SalesPerformancePoint]
    totalRevenue: float
    totalCount: int
