from django.contrib import admin
from .models import Plan, Subscription, Payment

@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "price_php", "max_seats", "is_active"]

@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ["user", "plan", "status", "current_period_end", "created_at"]
    list_filter = ["status", "plan"]
    search_fields = ["user__username", "user__email"]

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ["paymongo_payment_id", "user", "amount_php", "status", "created_at"]
    list_filter = ["status"]
    readonly_fields = ["raw_webhook_data"]