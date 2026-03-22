from django.contrib import admin
from .models import Annotation

@admin.register(Annotation)
class AnnotationAdmin(admin.ModelAdmin):
    list_display = ["user", "board", "annotation_type", "component_ref", "created_at"]
    list_filter = ["annotation_type"]
    search_fields = ["user__username", "board__name", "text"]