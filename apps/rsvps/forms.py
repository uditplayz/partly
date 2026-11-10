import re

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from .models import MAX_PLUS_ONES

MAX_INVITES_PER_SUBMIT = 20


class RSVPForm(forms.Form):
    plus_ones = forms.IntegerField(min_value=0, max_value=MAX_PLUS_ONES, required=False)
    note = forms.CharField(max_length=200, required=False, strip=True)
    age_confirmed = forms.BooleanField(required=False)

    def clean_plus_ones(self):
        return self.cleaned_data.get("plus_ones") or 0


class InviteForm(forms.Form):
    emails = forms.CharField(
        label="Email addresses",
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "riya@college.edu, kabir@gmail.com"}),
        help_text=f"Separate with commas or new lines. Up to {MAX_INVITES_PER_SUBMIT} at a time.",
    )

    def clean_emails(self):
        raw = [part.strip().lower() for part in re.split(r"[,;\s]+", self.cleaned_data["emails"]) if part.strip()]
        emails, invalid = [], []
        for address in dict.fromkeys(raw):  # de-duplicate, keep order
            try:
                validate_email(address)
                emails.append(address)
            except ValidationError:
                invalid.append(address)
        if invalid:
            raise forms.ValidationError("These don't look like email addresses: " + ", ".join(invalid[:5]))
        if not emails:
            raise forms.ValidationError("Add at least one email address.")
        if len(emails) > MAX_INVITES_PER_SUBMIT:
            raise forms.ValidationError(f"Invite at most {MAX_INVITES_PER_SUBMIT} people at a time.")
        return emails
