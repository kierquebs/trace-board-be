from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ["username", "email", "role", "is_suspended", "has_active_subscription", "date_joined"]
    list_filter = ["role", "is_suspended", "is_active"]
    search_fields = ["username", "email", "company_name"]
    ordering = ["-date_joined"]

    fieldsets = BaseUserAdmin.fieldsets + (  # type: ignore[operator]
        (
            "NailTrace",
            {
                "fields": ("role", "phone", "company_name", "is_suspended"),
            },
        ),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (  # type: ignore[operator]
        (
            "NailTrace",
            {
                "fields": ("role", "email", "phone", "company_name"),
            },
        ),
    )
