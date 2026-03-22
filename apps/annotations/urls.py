from django.urls import path
from .views import AnnotationDetailView

urlpatterns = [
    path("<int:pk>/", AnnotationDetailView.as_view(), name="annotation-detail"),
]
