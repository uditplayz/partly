from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class PartlyUserAdmin(UserAdmin):
    list_display = ("username", "email", "display_name", "campus_tag", "trust_score", "is_staff")
    search_fields = ("username", "email", "display_name", "campus_tag")
    fieldsets = UserAdmin.fieldsets + (
        ("Partly profile", {"fields": ("display_name", "campus_tag", "bio", "vibe_tags")}),
        ("Trust", {"fields": ("trust_score", "hosted_completed_count", "attended_count", "no_show_count")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (("Contact", {"fields": ("email",)}),)
