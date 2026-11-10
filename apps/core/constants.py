from django.db import models


class Vibe(models.TextChoices):
    """Shared vibe vocabulary: event categories and profile vibe tags."""

    HOUSE_PARTY = "HOUSE_PARTY", "House Party"
    JAM = "JAM", "Jam Session"
    WORKSHOP = "WORKSHOP", "Workshop"
    STUDY = "STUDY", "Study Sesh"
    CHAI_SMOKE = "CHAI_SMOKE", "Smoke/Chai Break"
    DRINKS = "DRINKS", "Drinks/Pre-game"
    GAMING = "GAMING", "Gaming"
