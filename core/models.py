from django.contrib.auth.models import AbstractUser
from django.db import models

from .modules import PLATFORM_ROLES, ROLE_CHOICES, ROLE_LABELS


class User(AbstractUser):
    """A single user model for platform staff and restaurant staff."""

    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="owner")
    phone = models.CharField(max_length=15, unique=True, null=True, blank=True)
    restaurant = models.ForeignKey(
        "restaurant.Restaurant",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="staff",
    )
    pin = models.CharField("Quick-switch PIN", max_length=4, blank=True)
    is_online = models.BooleanField(default=False, help_text="Riders: available for deliveries")
    current_session_key = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["first_name", "username"]

    def __str__(self):
        return self.display_name

    def save(self, *args, **kwargs):
        # `createsuperuser` makes a platform super admin, not a restaurant owner.
        if self.is_superuser and not self.restaurant_id and self.role not in PLATFORM_ROLES:
            self.role = "super_admin"
        if self.phone == "":
            self.phone = None
        super().save(*args, **kwargs)

    @property
    def display_name(self):
        full = self.get_full_name().strip()
        return full or self.username

    @property
    def initials(self):
        name = self.display_name
        parts = [p for p in name.replace("_", " ").split() if p]
        if len(parts) >= 2:
            return (parts[0][0] + parts[1][0]).upper()
        return name[:1].upper()

    @property
    def role_label(self):
        return ROLE_LABELS.get(self.role, self.role)

    @property
    def is_platform(self):
        return self.is_superuser or self.role in PLATFORM_ROLES

    @property
    def is_super_admin(self):
        return self.is_superuser or self.role == "super_admin"
