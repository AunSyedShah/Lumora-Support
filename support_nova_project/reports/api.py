"""
Dashboards, analytics, trends and reports (SRS Steps 62-68).

Access:  agent dashboard            -> the agent's own assigned complaints
         everything else            -> reviewers, managers, administrators (organisation-wide data)
All endpoints accept the same filters (date range, department, category, priority, channel, sentiment).
"""

from datetime import date

from django.http import HttpResponse
from django.utils import timezone
from ninja import Query, Router, Schema
from ninja.errors import HttpError
from pydantic import Field

from accounts.auth import STAFF_ROLES, require_role
from complaints.permissions import FULL_ACCESS_ROLES

from .analytics import analytics, detect_trends
from .catalog import REPORTS
from .dashboards import admin_dashboard, agent_dashboard
from .data import complaint_frame, filtered_complaints
from .export import FORMATS, export

dashboard_router = Router(tags=["Dashboards"])
analytics_router = Router(tags=["Analytics"])
reports_router = Router(tags=["Reports"])


class Filters(Schema):
    date_from: date | None = None
    date_to: date | None = None
    department: str | None = None
    category: str | None = None
    priority: str | None = None
    channel: str | None = None
    sentiment: str | None = None


def _queryset(request, filters):
    return filtered_complaints(request.auth, **filters.model_dump())


def _active(filters):
    return {k: str(v) for k, v in filters.model_dump().items() if v}


# ---------------- dashboards ----------------


@dashboard_router.get("/agent")
def agent(request):
    """Agent Dashboard (Step 62): the logged-in agent's assigned complaints and their workload."""
    require_role(request, *STAFF_ROLES)
    return agent_dashboard(request.auth)


@dashboard_router.get("/admin")
def admin(request, filters: Query[Filters]):
    """Administrator Dashboard (Step 63): organisation-wide complaint metrics."""
    require_role(request, *FULL_ACCESS_ROLES)
    return {"filters": _active(filters), **admin_dashboard(_queryset(request, filters))}


# ---------------- analytics ----------------


@analytics_router.get("")
def complaint_analytics(request, filters: Query[Filters]):
    """Complaint Analytics (Step 64)."""
    require_role(request, *FULL_ACCESS_ROLES)
    return {"filters": _active(filters), **analytics(complaint_frame(_queryset(request, filters)))}


class TrendParams(Schema):
    window_days: int = Field(7, ge=1, le=90)
    min_count: int = Field(3, ge=1)
    growth: float = Field(0.5, ge=0, description="0.5 = at least +50% compared with the previous window")


@analytics_router.get("/trends")
def trends(request, filters: Query[Filters], params: Query[TrendParams]):
    """Trend Detection (Step 65): rising categories/products, recurring issues, repeated failures, escalation spikes."""
    require_role(request, *FULL_ACCESS_ROLES)
    df = complaint_frame(_queryset(request, filters))
    return {"filters": _active(filters),
            **detect_trends(df, window_days=params.window_days, min_count=params.min_count, growth=params.growth)}


# ---------------- reports ----------------


@reports_router.get("")
def list_reports(request):
    require_role(request, *FULL_ACCESS_ROLES)
    return [{"name": name, "title": build.__doc__ or name.replace("_", " ").title()} for name, build in REPORTS.items()]


@reports_router.get("/{name}")
def report(request, name: str, filters: Query[Filters], format: str = "json"):
    """Generate a report (Step 67). format = json | csv | xlsx | pdf (Step 68)."""
    require_role(request, *FULL_ACCESS_ROLES)
    if name not in REPORTS:
        raise HttpError(404, f"Unknown report '{name}'. Available: {sorted(REPORTS)}")
    if format != "json" and format not in FORMATS:
        raise HttpError(400, f"format must be json or one of {sorted(FORMATS)}")

    result = REPORTS[name](_queryset(request, filters))
    active = _active(filters)
    if format == "json":
        return {"report": name, "title": result.title, "description": result.description, "filters": active,
                "generated_at": timezone.now(), "summary": result.summary, "columns": result.columns,
                "row_count": len(result.rows), "rows": result.rows}

    content_type, extension = FORMATS[format]
    response = HttpResponse(export(result, format, active), content_type=content_type)
    stamp = timezone.localtime().strftime("%Y%m%d")
    response["Content-Disposition"] = f'attachment; filename="{name}_{stamp}.{extension}"'
    return response
