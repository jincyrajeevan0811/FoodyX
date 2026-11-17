from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q


class PhoneEmailUsernameBackend(ModelBackend):
    """Sign in with a username, email address or mobile number."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None
        User = get_user_model()
        ident = username.strip()
        users = User.objects.filter(
            Q(username__iexact=ident) | Q(email__iexact=ident) | Q(phone=ident)
        )
        for user in users:
            if user.check_password(password) and self.user_can_authenticate(user):
                return user
        # Run the hasher once to reduce timing differences.
        User().set_password(password)
        return None
