from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.db import get_session
from app.services.metrics import Dashboard, GroupBy, Period, build_dashboard

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard", response_model=Dashboard)
def dashboard(
    period: Period = "weekly",
    group_by: GroupBy = "agent",
    session: Session = Depends(get_session),
) -> Dashboard:
    return build_dashboard(session, period, group_by)
