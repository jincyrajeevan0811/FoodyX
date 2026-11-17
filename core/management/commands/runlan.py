"""Run the development server so phones on the same Wi-Fi can open it.

    python manage.py runlan            # listens on 0.0.0.0:8000
    python manage.py runlan 8080       # another port

Use this when testing table QR codes or the online store from a phone.
"""
from django.core.management.commands.runserver import Command as RunserverCommand

from core.utils import lan_ip


class Command(RunserverCommand):
    help = "Start the development server on your local network (0.0.0.0) for testing QR codes on phones."

    def handle(self, *args, **options):
        addrport = options.get("addrport") or "8000"
        if ":" not in addrport:
            addrport = f"0.0.0.0:{addrport}"
        options["addrport"] = addrport
        port = addrport.rsplit(":", 1)[-1]
        ip = lan_ip()
        self.stdout.write(self.style.SUCCESS(
            f"\n  FoodyX on your network → http://{ip}:{port}/\n"
            f"  On this computer        → http://127.0.0.1:{port}/\n"
            "  Phones must be on the same Wi-Fi. If a phone can't connect, allow Python\n"
            "  through Windows Defender Firewall (Private networks) when Windows asks.\n"
        ))
        super().handle(*args, **options)
