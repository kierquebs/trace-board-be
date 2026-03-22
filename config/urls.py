from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path("django-admin/", admin.site.urls),

    # API routes
    path("api/auth/", include("apps.accounts.urls")),
    path("api/boards/", include("apps.boards.urls")),
    path("api/annotations/", include("apps.annotations.urls")),
    path("api/billing/", include("apps.billing.urls")),
    path("api/admin/", include("apps.admin_panel.urls")),

    # OpenAPI schema (dev only — disable in prod via settings)
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]

# Debug toolbar (dev only)
import os
if os.environ.get("DJANGO_SETTINGS_MODULE", "").endswith("dev"):
    import debug_toolbar
    urlpatterns = [path("__debug__/", include(debug_toolbar.urls))] + urlpatterns
