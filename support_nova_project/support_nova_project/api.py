"""Single NinjaAPI instance. Every app contributes a Router; all endpoints need a JWT unless marked auth=None."""

from ninja import NinjaAPI

from accounts.api import router as accounts_router
from accounts.auth import JWTAuth
from catalog.api import router as catalog_router
from complaints.api import orders_router
from complaints.api import router as complaints_router
from genai_pipeline.api import router as genai_router
from knowledge_base.api import router as kb_router
from python_validation.api import router as validation_router
from reports.api import analytics_router, dashboard_router, reports_router
from rules.api import router as rules_router
from workflow.api import router as workflow_router

api = NinjaAPI(
    title="SupportNova API",
    version="1.0.0",
    description="Complaint intelligence backend for Lumora Home Technologies.",
    auth=JWTAuth(),
)

api.add_router("/auth", accounts_router)
api.add_router("/catalog", catalog_router)
api.add_router("/kb", kb_router)
api.add_router("/rules", rules_router)
api.add_router("/complaints", complaints_router)
api.add_router("/orders", orders_router)
api.add_router("/genai", genai_router)
api.add_router("/validation", validation_router)
api.add_router("/workflow", workflow_router)
api.add_router("/dashboard", dashboard_router)
api.add_router("/analytics", analytics_router)
api.add_router("/reports", reports_router)
