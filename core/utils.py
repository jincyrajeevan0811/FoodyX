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


LOCAL_HOSTS = {"127.0.0.1", "localhost", "0.0.0.0", "::1", "[::1]"}


def lan_ip():
    """This computer's address on the local Wi-Fi/LAN (e.g. 192.168.1.20).

    Opening a UDP socket towards a public address sends no packets; it only
    makes the OS pick the network interface it would use.
    """
    import socket

    for target in ("8.8.8.8", "10.255.255.255"):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.connect((target, 80))
                ip = s.getsockname()[0]
            finally:
                s.close()
            if ip and not ip.startswith("127."):
                return ip
        except OSError:
            continue
    return "127.0.0.1"


def public_base_url(request):
    """Base URL that guests' phones can open (used for QR codes and share links).

    1. The Site address saved in Platform settings, if any.
    2. When the app is opened as localhost/127.0.0.1, the computer's LAN IP
       with the same port, so a phone on the same Wi-Fi can reach it.
    3. Otherwise the address the request came in on.
    """
    from saas.models import PlatformSettings

    site = (PlatformSettings.load().site_url or "").strip().rstrip("/")
    if site:
        return site
    host = request.get_host()
    hostname, _, port = host.rpartition(":") if host.count(":") == 1 else (host, "", "")
    if not hostname:
        hostname, port = host, ""
    if hostname in LOCAL_HOSTS:
        return f"{request.scheme}://{lan_ip()}{':' + port if port else ''}"
    return request.build_absolute_uri("/")[:-1]


def is_local_request(request):
    host = request.get_host().split(":")[0]
    return host in LOCAL_HOSTS
