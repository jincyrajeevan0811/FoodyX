import logging

from django.core.mail import EmailMessage, get_connection

logger = logging.getLogger(__name__)


def client_ip(request):
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def log_activity(request, action, detail="", restaurant=None, actor=None):
    from saas.models import ActivityLog

    if actor is None and request is not None and request.user.is_authenticated:
        actor = request.user
    if restaurant is None and actor is not None and getattr(actor, "restaurant_id", None):
        restaurant = actor.restaurant
    try:
        ActivityLog.objects.create(
            actor=actor, restaurant=restaurant, action=action, detail=detail[:2000], ip_address=client_ip(request)
        )
    except Exception:  # never break a request because logging failed
        logger.exception("Could not write activity log")


def send_platform_email(subject, body, to):
    """Send email with the SMTP settings saved in Platform settings."""
    from saas.models import PlatformSettings

    if not to:
        return False
    ps = PlatformSettings.load()
    try:
        if ps.smtp_ready:
            conn = get_connection(
                "django.core.mail.backends.smtp.EmailBackend",
                host=ps.smtp_host,
                port=ps.smtp_port,
                username=ps.smtp_username or None,
                password=ps.smtp_password or None,
                use_tls=ps.smtp_use_tls,
                timeout=15,
            )
            from_email = f"{ps.site_name} <{ps.smtp_from_email}>"
        else:
            conn = get_connection()
            from_email = None
        EmailMessage(subject, body, from_email, [to] if isinstance(to, str) else to, connection=conn).send()
        return True
    except Exception:
        logger.exception("Email sending failed")
        return False
