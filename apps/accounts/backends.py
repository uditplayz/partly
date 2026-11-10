from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailOrUsernameBackend(ModelBackend):
    """Log in with either username or email (both case-insensitive)."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None
        User = get_user_model()
        lookup = "email__iexact" if "@" in username else "username__iexact"
        try:
            user = User._default_manager.get(**{lookup: username.strip()})
        except User.DoesNotExist:
            User().set_password(password)  # mitigate timing attacks, like ModelBackend
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
