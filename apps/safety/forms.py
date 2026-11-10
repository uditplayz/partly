from django import forms

from .models import Report


class ReportForm(forms.Form):
    reason = forms.ChoiceField(choices=Report.Reason.choices)
    details = forms.CharField(
        required=False, strip=True, max_length=600,
        widget=forms.Textarea(attrs={"rows": 4, "placeholder": "What happened? Anything that helps us look into it."}),
    )
