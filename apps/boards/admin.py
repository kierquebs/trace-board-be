from django.contrib import admin
from .models import BoardFile

@admin.register(BoardFile)
class BoardFileAdmin(admin.ModelAdmin):
    list_display = ["name", "brand", "category", "format", "status", "parse_status", "view_count", "uploaded_at"]
    list_filter = ["status", "parse_status", "category", "format"]
    search_fields = ["name", "brand", "model_number", "original_filename"]
    readonly_fields = ["content_hash", "s3_key", "file_size", "parse_error", "view_count", "last_viewed_at", "uploaded_at"]
    ordering = ["-uploaded_at"]