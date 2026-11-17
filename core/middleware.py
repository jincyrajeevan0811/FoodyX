from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect

from .modules import SINGLE_DEVICE_ROLES


class SingleDeviceMiddleware:
    """A captain's login works on one device at a time.

    When the same login signs in somewhere else, the older session is
    signed out the next time it makes a request.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            user is not None
            and user.is_authenticated
            and user.role in SINGLE_DEVICE_ROLES
            and user.current_session_key
            and request.session.session_key
            and request.session.session_key != user.current_session_key
        ):
            logout(request)
            messages.warning(
                request,
                "This login is now in use on another device. Every person needs their own login.",
            )
            return redirect("core:login")
        return self.get_response(request)
