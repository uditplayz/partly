from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from apps.core.constants import Vibe

from .models import User


class SignupForm(UserCreationForm):
    class Meta:
        model = User
        fields = ("display_name", "username", "email", "campus_tag")
        labels = {"display_name": "What should people call you?"}
        widgets = {
            "display_name": forms.TextInput(attrs={"autocomplete": "nickname", "placeholder": "Aditi"}),
            "username": forms.TextInput(attrs={"autocomplete": "username", "placeholder": "aditi.k"}),
            "email": forms.EmailInput(attrs={"autocomplete": "email", "placeholder": "you@college.edu"}),
            "campus_tag": forms.TextInput(attrs={"placeholder": "COEP / Viman Nagar"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].required = True
        self.fields["display_name"].required = True

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("That email already has an account. Try logging in.")
        return email

    def clean_username(self):
        username = self.cleaned_data.get("username", "")
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("That username is taken.")
        return super().clean_username()


class LoginForm(AuthenticationForm):
    username = forms.CharField(
        label="Email or username",
        widget=forms.TextInput(attrs={"autofocus": True, "autocomplete": "username"}),
    )


class ProfileForm(forms.ModelForm):
    vibe_tags = forms.MultipleChoiceField(
        choices=Vibe.choices,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Your vibes",
    )

    class Meta:
        model = User
        fields = ("display_name", "campus_tag", "bio", "vibe_tags")
        widgets = {"bio": forms.Textarea(attrs={"rows": 3, "maxlength": 280})}
