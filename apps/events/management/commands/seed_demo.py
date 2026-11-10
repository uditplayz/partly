"""Seed realistic demo events for local development: python manage.py seed_demo [--reset]."""
import random
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.core.constants import Vibe
from apps.events.models import Event

DEMO_PREFIX = "demo_"
DEMO_PASSWORD = "partly-demo-pass"

HOSTS = [
    ("demo_aditi", "Aditi", "COEP"),
    ("demo_kabir", "Kabir", "Viman Nagar"),
    ("demo_meera", "Meera", "Koregaon Park"),
    ("demo_rohan", "Rohan", "FC Road"),
    ("demo_sana", "Sana", "Baner"),
    ("demo_vikram", "Vikram", "Hostel Block C"),
]

AREAS = [
    "Viman Nagar", "Koregaon Park", "Kalyani Nagar", "Baner", "Aundh",
    "FC Road", "Kothrud", "Hostel Block C", "Hinjewadi Phase 1", "Camp",
]

IDEAS = {
    Vibe.HOUSE_PARTY: [("Rooftop house party", 40, 6), ("Friday night mixer", 60, 5), ("Housewarming, come through", 25, 6)],
    Vibe.JAM: [("Acoustic jam: bring your guitar", 12, 4), ("Open mic + chai", 20, 3), ("Bollywood unplugged night", 15, 4)],
    Vibe.WORKSHOP: [("Intro to film photography", 10, 2), ("Pottery for absolute beginners", 8, 3), ("Resume roast + tips", 16, 2)],
    Vibe.STUDY: [("DSA grind session", 6, 3), ("Silent study at the café", 4, 3), ("GRE quant prep circle", 8, 2)],
    Vibe.CHAI_SMOKE: [("Cutting chai break", 6, 1), ("Late night tapri run", 8, 1)],
    Vibe.DRINKS: [("Pre-game before the gig", 14, 3), ("Wine & board games", 10, 3), ("Craft beer tasting", 12, 3)],
    Vibe.GAMING: [("FIFA tournament", 16, 3), ("Valorant 5-stack scrims", 10, 3), ("Catan marathon", 6, 4)],
}

FEE_NOTES = ["BYOB, ₹150 for snacks via UPI", "Pay at the door via UPI", "Covers mixers + pizza", ""]


class Command(BaseCommand):
    help = "Create about 40 published demo events (fee waived) from 6 demo hosts."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete existing demo hosts and events first.")
        parser.add_argument("--force", action="store_true", help="Allow running with DEBUG=False.")
        parser.add_argument("--seed", type=int, default=42)

    @transaction.atomic
    def handle(self, *args, reset=False, force=False, seed=42, **options):
        if not settings.DEBUG and not force:
            raise CommandError("Refusing to seed demo data with DEBUG=False (pass --force to override).")

        if reset:
            deleted, _ = Event.objects.filter(host__username__startswith=DEMO_PREFIX).delete()
            User.objects.filter(username__startswith=DEMO_PREFIX).delete()
            self.stdout.write(f"Removed {deleted} demo events and their hosts.")
        elif Event.objects.filter(host__username__startswith=DEMO_PREFIX).exists():
            self.stdout.write(self.style.WARNING("Demo events already exist. Use --reset to recreate them."))
            return

        rng = random.Random(seed)
        hosts = [self._host(*h) for h in HOSTS]
        now = timezone.localtime()
        ideas = [(vibe, idea) for vibe, items in IDEAS.items() for idea in items]

        events = []
        for i in range(40):
            vibe, (title, capacity, hours) = ideas[i % len(ideas)]
            start = self._start_for(i, now, rng)
            paid = rng.random() < 0.35
            fee = Decimal(rng.choice([100, 150, 200, 250, 300, 500])) if paid else Decimal("0")
            events.append(Event(
                host=hosts[i % len(hosts)],
                title=title,
                description=f"{title}. Small crowd, good vibes. Message the host if you have questions.",
                vibe_category=vibe,
                area_name=rng.choice(AREAS),
                exact_address=f"Flat {rng.randint(1, 20)}{rng.choice('ABCD')}, Demo Residency, Lane {rng.randint(1, 9)}",
                start_time=start,
                end_time=start + timedelta(hours=hours),
                rsvp_deadline=start - timedelta(hours=1),
                capacity=max(2, capacity + rng.randint(-2, 4)),
                max_plus_ones=rng.choice([0, 0, 1, 2]),
                requires_host_approval=vibe in (Vibe.HOUSE_PARTY, Vibe.DRINKS) or rng.random() < 0.2,
                is_free_entry=not paid,
                venue_entry_fee_inr=fee,
                entry_fee_notes=rng.choice(FEE_NOTES) if paid else "",
                platform_fee_status=Event.FeeStatus.WAIVED,
                status=Event.Status.PUBLISHED,
                published_at=timezone.now(),
            ))
        for event in events:
            event.save()  # save() (not bulk_create) so each gets a slug
        self.stdout.write(self.style.SUCCESS(
            f"Seeded {len(events)} events from {len(hosts)} hosts. Demo login: demo_aditi / {DEMO_PASSWORD}"
        ))

    def _host(self, username, name, campus):
        user = User(username=username, email=f"{username}@demo.partly.local", display_name=name, campus_tag=campus)
        user.set_password(DEMO_PASSWORD)
        user.save()
        return user

    def _start_for(self, i, now, rng):
        """Spread over 14 days, with guaranteed 'tonight' and 'this weekend' entries."""
        if i < 4:  # tonight
            day, hour = now.date(), max(now.hour + 1, 19) + i % 3
        elif i < 10:  # the coming Fri/Sat
            offset = (4 - now.weekday()) % 7 + (i % 2)
            day, hour = now.date() + timedelta(days=offset), rng.choice([18, 19, 20, 21])
        else:
            day, hour = now.date() + timedelta(days=rng.randint(1, 14)), rng.choice([7, 10, 15, 17, 18, 19, 20, 21])
        hour = min(hour, 22)
        start = timezone.make_aware(datetime.combine(day, time(hour, rng.choice([0, 0, 30]))))
        return max(start, timezone.now() + timedelta(minutes=30))
