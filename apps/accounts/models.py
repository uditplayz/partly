from decimal import Decimal

from django.contrib.auth.models import AbstractUser, UserManager
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.core.validators import MaxLengthValidator
from django.db import models
from django.db.models.functions import Lower

from apps.core.constants import Vibe

NEW_MEMBER_THRESHOLD = 3


class PartlyUserManager(UserManager):
    def get_by_natural_key(self, username):
        return self.get(**{f"{self.model.USERNAME_FIELD}__iexact": username})


class User(AbstractUser):
    email = models.EmailField("email address")
    display_name = models.CharField(max_length=60, blank=True)
    campus_tag = models.CharField(
        "campus / neighbourhood",
        max_length=80,
        blank=True,
        db_index=True,
        help_text="e.g. COEP, Viman Nagar, Hostel Block C",
    )
    bio = models.TextField(blank=True, validators=[MaxLengthValidator(280)])
    vibe_tags = ArrayField(
        models.CharField(max_length=30, choices=Vibe.choices),
        default=list,
        blank=True,
        size=8,
    )
    trust_score = models.DecimalField(max_digits=4, decimal_places=1, default=Decimal("50.0"))
    hosted_completed_count = models.PositiveIntegerField(default=0)
    attended_count = models.PositiveIntegerField(default=0)
    no_show_count = models.PositiveIntegerField(default=0)

    REQUIRED_FIELDS = ["email"]

    objects = PartlyUserManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(Lower("email"), name="accounts_user_email_ci_unique"),
            models.UniqueConstraint(Lower("username"), name="accounts_user_username_ci_unique"),
        ]
        indexes = [GinIndex(fields=["vibe_tags"], name="accounts_user_vibes_gin")]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    @property
    def name(self):
        return self.display_name or self.username

    @property
    def initials(self):
        parts = self.name.split()
        return "".join(p[0] for p in parts[:2]).upper() or "?"

    @property
    def is_new_member(self):
        history = self.hosted_completed_count + self.attended_count + self.no_show_count
        return history < NEW_MEMBER_THRESHOLD

    def vibe_tag_pairs(self):
        """[(value, label), ...] for templates (value drives the pill colour)."""
        labels = dict(Vibe.choices)
        return [(t, labels.get(t, t)) for t in self.vibe_tags]
