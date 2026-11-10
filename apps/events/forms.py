from decimal import Decimal

from django import forms
from django.db.models import F, Sum
from django.utils import timezone

from .models import MAX_PLUS_ONES, Event

DT_FORMAT = "%Y-%m-%dT%H:%M"


class DateTimeLocalInput(forms.DateTimeInput):
    input_type = "datetime-local"

    def __init__(self, **kwargs):
        super().__init__(format=DT_FORMAT, **kwargs)


class EventForm(forms.ModelForm):
    rsvp_deadline = forms.DateTimeField(
        required=False,
        input_formats=[DT_FORMAT],
        widget=DateTimeLocalInput(),
        label="RSVP deadline",
        help_text="Optional. Defaults to the start time.",
    )

    class Meta:
        model = Event
        fields = (
            "title", "vibe_category", "description",
            "area_name", "exact_address",
            "start_time", "end_time", "rsvp_deadline",
            "capacity", "max_plus_ones", "requires_host_approval", "min_age",
            "is_free_entry", "venue_entry_fee_inr", "entry_fee_notes",
        )
        labels = {
            "vibe_category": "Vibe",
            "exact_address": "Exact address",
            "max_plus_ones": "Plus-ones allowed per guest",
            "requires_host_approval": "I want to approve guests before they get the address",
            "is_free_entry": "Free entry",
            "venue_entry_fee_inr": "Cover charge (₹)",
            "entry_fee_notes": "Entry notes",
        }
        help_texts = {
            "capacity": "Between 2 and 100 people, including plus-ones.",
            "entry_fee_notes": "e.g. BYOB + ₹150 for snacks, UPI at the door",
        }
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "Rooftop jam: bring your guitar"}),
            "description": forms.Textarea(attrs={"rows": 4, "placeholder": "What's the plan? What should people bring?"}),
            "area_name": forms.TextInput(attrs={"placeholder": "Koregaon Park"}),
            "exact_address": forms.Textarea(attrs={"rows": 2, "placeholder": "Flat 4B, Sunshine Apts, Lane 6"}),
            "start_time": DateTimeLocalInput(),
            "end_time": DateTimeLocalInput(),
            "capacity": forms.NumberInput(attrs={"min": 2, "max": 100}),
            "max_plus_ones": forms.NumberInput(attrs={"min": 0, "max": MAX_PLUS_ONES}),
            "venue_entry_fee_inr": forms.NumberInput(attrs={"min": 0, "step": "1", "inputmode": "numeric"}),
            "entry_fee_notes": forms.TextInput(attrs={"maxlength": 140}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("start_time", "end_time"):
            self.fields[name].input_formats = [DT_FORMAT]
        self.fields["venue_entry_fee_inr"].required = False
        self.fields["min_age"].required = False
        self.fields["min_age"].empty_value = 0

    def clean_capacity(self):
        value = self.cleaned_data["capacity"]
        if not 2 <= value <= 100:
            raise forms.ValidationError("Capacity must be between 2 and 100.")
        if self.instance.pk:
            taken = self.instance.rsvps.filter(status="CONFIRMED").aggregate(n=Sum(F("plus_ones") + 1))["n"] or 0
            if value < taken:
                raise forms.ValidationError(f"{taken} spots are already confirmed, so capacity can't go below that.")
        return value

    def clean_max_plus_ones(self):
        value = self.cleaned_data["max_plus_ones"]
        if value > MAX_PLUS_ONES:
            raise forms.ValidationError(f"At most {MAX_PLUS_ONES} plus-ones per guest.")
        return value

    def clean(self):
        cd = super().clean()
        start, end = cd.get("start_time"), cd.get("end_time")
        if start and end and end <= start:
            self.add_error("end_time", "End time must be after the start.")
        if start and self.instance._state.adding and start <= timezone.now():
            self.add_error("start_time", "Pick a time in the future.")

        deadline = cd.get("rsvp_deadline")
        if start and not deadline:
            cd["rsvp_deadline"] = start
        elif start and deadline and deadline > start:
            self.add_error("rsvp_deadline", "The RSVP deadline can't be after the start.")

        if cd.get("vibe_category") == "DRINKS" and not cd.get("min_age"):
            self.add_error("min_age", "Events with drinks need an age rule (18 or 21 and over).")

        fee = cd.get("venue_entry_fee_inr") or Decimal("0")
        if cd.get("is_free_entry"):
            cd["venue_entry_fee_inr"] = Decimal("0")
        elif fee <= 0:
            self.add_error("venue_entry_fee_inr", "Add a cover charge, or mark the event as free.")
        else:
            cd["venue_entry_fee_inr"] = fee
        return cd
