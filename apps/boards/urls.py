from django.urls import path

from apps.annotations.views import BoardAnnotationListView

from .views import BoardDetailView, BoardListView, BoardViewEndpoint

urlpatterns = [
    path("", BoardListView.as_view(), name="board-list"),
    path("<int:pk>/", BoardDetailView.as_view(), name="board-detail"),
    path("<int:pk>/view/", BoardViewEndpoint.as_view(), name="board-view"),
    path("<int:pk>/annotations/", BoardAnnotationListView.as_view(), name="board-annotations"),
]
