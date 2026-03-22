from django.urls import path
from apps.annotations.views import BoardAnnotationListView
from .views import (
    AdminBoardDetailView,
    AdminBoardListView,
    AdminBoardReparseView,
    AdminBoardUploadView,
    AdminUserDetailView,
    AdminUserListView,
    AdminAnalyticsOverviewView,
    AdminAnalyticsPopularBoardsView,
)

urlpatterns = [
    # Board management
    path("boards/", AdminBoardListView.as_view(), name="admin-board-list"),
    path("boards/upload/", AdminBoardUploadView.as_view(), name="admin-board-upload"),
    path("boards/<int:pk>/", AdminBoardDetailView.as_view(), name="admin-board-detail"),
    path("boards/<int:pk>/reparse/", AdminBoardReparseView.as_view(), name="admin-board-reparse"),

    # Board annotations (also accessible from technician routes, but admin can view all)
    path("boards/<int:board_id>/annotations/", BoardAnnotationListView.as_view(), name="admin-board-annotations"),

    # User management
    path("users/", AdminUserListView.as_view(), name="admin-user-list"),
    path("users/<int:pk>/", AdminUserDetailView.as_view(), name="admin-user-detail"),

    # Analytics
    path("analytics/overview/", AdminAnalyticsOverviewView.as_view(), name="admin-analytics-overview"),
    path("analytics/popular-boards/", AdminAnalyticsPopularBoardsView.as_view(), name="admin-analytics-popular"),
]
