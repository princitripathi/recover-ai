from fastapi import APIRouter
from app.schemas.dashboard import DashboardSummary
from app.services.dashboard_service import DashboardService

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
service = DashboardService()


@router.get("/summary", response_model=DashboardSummary)
def dashboard_summary():
    return service.get_summary()
