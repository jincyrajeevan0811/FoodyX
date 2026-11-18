"""Create plans, a super admin and a fully-populated demo restaurant.

    python manage.py seed_demo            # first time
    python manage.py seed_demo --fresh    # delete the demo restaurants and seed again
"""
import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from restaurant.models import (
    Area, Category, Coupon, Customer, Device, InventoryItem, MenuItem, Order, OrderItem, Payment, Restaurant, Table,
    WaiterCall,
)
from restaurant.services import add_items, complete_order, mark_billed, record_payments
from saas.models import ActivityLog, Plan, PlatformPayment, PlatformSettings, Subscription
from saas.services import bootstrap_restaurant

User = get_user_model()

PLANS = [
    dict(name="Basic", tagline="Single-counter essentials for cafés and small eateries.", price_monthly=999,
         price_yearly=9990, max_staff=3, max_tables=12, max_devices=2, sort_order=1,
         features=["insights"],
         highlights="3 staff logins · 2 devices\nFast billing & KOT\nTables & menu with HSN\nReports & daily item sales\nQR digital menu"),
    dict(name="Average", tagline="For busy restaurants that want QR, delivery and loyalty.", price_monthly=2499,
         price_yearly=24990, max_staff=10, max_tables=40, max_devices=6, sort_order=2, is_popular=True,
         features=["kitchen", "delivery", "rider", "customers", "qr_ordering", "online_store", "online_payments",
                   "split_billing", "insights"],
         highlights="Everything in Basic\n10 staff logins\nQR table ordering & payment\nKitchen display system\nOnline store & home delivery\nSplit billing\nCustomers & loyalty"),
    dict(name="Medium", tagline="Multi-area restaurants and hotels with full control.", price_monthly=4999,
         price_yearly=49990, max_staff=0, max_tables=0, max_devices=0, sort_order=3,
         features=["kitchen", "delivery", "rider", "customers", "inventory", "marketing", "qr_ordering",
                   "online_store", "online_payments", "split_billing", "insights", "multi_area"],
         highlights="Everything in Average\nUnlimited staff & devices\nInventory & stock alerts\nMarketing, coupons & SEO\nHotel rooms & multiple areas\nSmart insights"),
    dict(name="Premium", tagline="Chains, groups and franchises.", price_monthly=0, price_yearly=0,
         is_custom_pricing=True, max_staff=0, max_tables=0, max_devices=0, sort_order=4,
         features=["kitchen", "delivery", "rider", "customers", "inventory", "marketing", "qr_ordering",
                   "online_store", "online_payments", "split_billing", "insights", "multi_area"],
         highlights="Everything in Medium\nMulti-outlet rollout\nDedicated success manager\nCustom SLAs & training"),
]

MENU = {
    "Breakfast": [("Appam with Stew", 120, "veg", "Soft lace appams with coconut vegetable stew"),
                  ("Puttu & Kadala", 90, "veg", "Steamed rice cylinders with black chickpea curry"),
                  ("Masala Dosa", 80, "veg", "Crispy dosa, potato masala, chutneys"),
                  ("Egg Roast", 70, "egg", "Kerala style egg roast")],
    "Starters": [("Chicken 65", 220, "non_veg", "Fiery fried chicken bites"),
                 ("Paneer Tikka", 240, "veg", "Tandoor-charred cottage cheese"),
                 ("Beef Fry", 260, "non_veg", "Slow-roasted beef with coconut slivers"),
                 ("Gobi Manchurian", 180, "veg", "Indo-Chinese cauliflower")],
    "Biriyani": [("Chicken Biriyani", 260, "non_veg", "Malabar dum biriyani"),
                 ("Beef Biriyani", 280, "non_veg", "Thalassery style"),
                 ("Veg Biriyani", 200, "veg", "Seasonal vegetables, fragrant rice"),
                 ("Fish Biriyani", 320, "non_veg", "Seer fish, mild spices")],
    "Mains": [("Kerala Fish Curry", 290, "non_veg", "Tangy kudampuli fish curry"),
              ("Butter Chicken", 300, "non_veg", "Creamy tomato gravy"),
              ("Dal Tadka", 160, "veg", "Yellow lentils, ghee tempering"),
              ("Veg Noodles", 170, "veg", "Wok-tossed noodles"),
              ("Nettoli Fry", 210, "non_veg", "Crispy anchovies")],
    "Breads": [("Malabar Porotta", 25, "veg", "Flaky layered porotta"),
               ("Butter Naan", 45, "veg", "Tandoor naan"),
               ("Chapati", 20, "veg", "Whole wheat")],
    "Hot Drinks": [("Masala Chai", 30, "veg", ""), ("Filter Coffee", 40, "veg", ""), ("Sulaimani", 25, "veg", "Spiced black tea with lime")],
    "Cool Drinks": [("Fresh Lime Soda", 60, "veg", ""), ("Mango Lassi", 90, "veg", ""), ("Avil Milk", 110, "veg", "Kozhikode favourite")],
    "Desserts": [("Payasam", 80, "veg", "Palada pradhaman"), ("Gulab Jamun", 70, "veg", "Two pieces, warm"),
                 ("Falooda", 140, "veg", "Rose, ice cream, nuts")],
}
STATIONS = {"Hot Drinks": "Beverages", "Cool Drinks": "Beverages", "Desserts": "Beverages", "Breads": "Tandoor"}
CUSTOMERS = ["Anjali Menon", "Rahul Nair", "Fathima Beevi", "Joseph Mathew", "Divya Pillai", "Arjun Das",
             "Sneha Kurian", "Vishnu Prasad", "Meera Iyer", "Thomas George", "Aisha Rahman", "Kiran Kumar"]
STAFF = [("Ravi", "Menon", "manager"), ("Arun", "Kumar", "captain"), ("Biju", "Thomas", "captain"),
         ("Sara", "Joseph", "cashier"), ("Suresh", "Babu", "kitchen"), ("Akhil", "Raj", "rider"),
         ("Nikhil", "Varma", "rider"), ("Latha", "Krishnan", "store_keeper"), ("Neha", "Paul", "admin")]


class Command(BaseCommand):
    help = "Seed plans, a super admin and a demo restaurant with realistic data."

    def add_arguments(self, parser):
        parser.add_argument("--fresh", action="store_true", help="Delete demo restaurants first.")

    @transaction.atomic
    def handle(self, *args, **opts):
        rng = random.Random(42)
        if opts["fresh"]:
            Restaurant.objects.filter(slug__in=["foodyx", "spice-garden", "cafe-mocha"]).delete()
            User.objects.filter(phone__startswith="90000000").delete()

        ps = PlatformSettings.load()
        ps.site_name = ps.site_name or "FoodyX"
        ps.support_email = ps.support_email or "support@foodyx.app"
        ps.sales_email = ps.sales_email or "sales@foodyx.app"
        ps.seo_title = ps.seo_title or "FoodyX — Restaurant POS, QR ordering & delivery software"
        ps.seo_description = ps.seo_description or (
            "Run your restaurant from one screen: billing, KOT, tables, QR ordering, delivery, inventory and reports.")
        ps.save()

        plans = {}
        for spec in PLANS:
            plan, _ = Plan.objects.update_or_create(name=spec["name"], defaults=spec)
            plans[plan.name] = plan
        self.stdout.write(self.style.SUCCESS(f"Plans ready: {', '.join(plans)}"))

        if not User.objects.filter(username="admin").exists():
            admin = User.objects.create_superuser("admin", "admin@foodyx.app", "admin123",
                                                  first_name="Platform", last_name="Admin", role="super_admin")
            self.stdout.write(self.style.SUCCESS("Super admin: admin / admin123"))
        else:
            admin = User.objects.get(username="admin")

        existing = Restaurant.objects.filter(slug__in=["foodyx", "spice-garden"]).first()
        if existing or User.objects.filter(phone__startswith="90000000").exists():
            name = existing.name if existing else "an older demo"
            self.stdout.write(self.style.WARNING(
                f"Demo data already exists ({name}). Nothing was changed.\n"
                "  Run `python manage.py seed_demo --fresh` to delete the demo restaurants and build them again."
            ))
            return

        # ---------------------------------------------------------- restaurant
        r = Restaurant.objects.create(
            name="FoodyX", slug="foodyx", business_type="restaurant", city="Kochi",
            tagline="Malabar flavours · since 2012", phone="9000000001", email="hello@foodyx.app",
            address="MG Road, Ernakulam, Kochi 682016", opening_hours="7:00 AM – 11:00 PM",
            service_charge_percent=Decimal("0"), charge_gst=True, gst_percent=Decimal("5"),
            delivery_fee=Decimal("30"), min_order_amount=Decimal("150"),
            seo_title="FoodyX Kochi — order Malabar food online",
            seo_description="Biriyani, appam, fish curry and more. Order online for takeaway or delivery.",
        )
        Subscription.objects.create(restaurant=r, plan=plans["Medium"], status="active", billing_cycle="monthly",
                                    started_at=timezone.now() - timedelta(days=20),
                                    current_period_end=timezone.now() + timedelta(days=10))
        owner = User.objects.create_user("dalvy", "owner@foodyx.app", "demo123", first_name="Dalvy",
                                         last_name="Mathew", phone="9000000001", role="owner", restaurant=r)
        staff = {"owner": [owner]}
        for i, (first, last, role) in enumerate(STAFF, start=2):
            u = User.objects.create_user(f"{first.lower()}.fx", f"{first.lower()}@foodyx.app", "demo123",
                                         first_name=first, last_name=last, phone=f"900000000{i}" if i < 10 else f"90000000{i}",
                                         role=role, restaurant=r, pin=f"{1000 + i}", is_online=(role == "rider"))
            staff.setdefault(role, []).append(u)

        main = Area.objects.create(restaurant=r, name="Main dining", sort_order=0)
        terrace = Area.objects.create(restaurant=r, name="Terrace", sort_order=1)
        rooms = Area.objects.create(restaurant=r, name="Hotel rooms", kind="room", sort_order=2)
        tables = []
        for i in range(1, 11):
            tables.append(Table.objects.create(restaurant=r, area=main, name=f"T{i}", seats=4 if i % 3 else 6, sort_order=i))
        for i in range(11, 15):
            tables.append(Table.objects.create(restaurant=r, area=terrace, name=f"T{i}", seats=2, sort_order=i))
        for i in (101, 102, 103, 104):
            Table.objects.create(restaurant=r, area=rooms, name=f"R{i}", seats=2, sort_order=i)

        items = []
        for ci, (cat_name, dishes) in enumerate(MENU.items()):
            cat = Category.objects.create(restaurant=r, name=cat_name, sort_order=ci)
            for name, price, ftype, desc in dishes:
                items.append(MenuItem.objects.create(
                    restaurant=r, category=cat, name=name, price=Decimal(price), food_type=ftype, description=desc,
                    station=STATIONS.get(cat_name, "Main kitchen"), hsn_code="996331",
                    is_featured=name in ("Chicken Biriyani", "Appam with Stew", "Kerala Fish Curry", "Avil Milk"),
                ))

        customers = []
        for i, name in enumerate(CUSTOMERS):
            customers.append(Customer.objects.create(restaurant=r, name=name, phone=f"98470{i:05d}",
                                                     birthday=timezone.localdate() - timedelta(days=365 * 28 + i * 23)))

        # --------------------------------------------------- history (14 days)
        now = timezone.now()
        popular = items[:]
        weights = [6 if m.is_featured else (3 if m.price < 100 else 2) for m in popular]
        waiters = staff["captain"] + staff["manager"]
        for day in range(14, 0, -1):
            for _ in range(rng.randint(14, 24)):
                hour = rng.choice([8, 9, 12, 13, 13, 14, 19, 20, 20, 21, 21])
                created = (now - timedelta(days=day)).replace(hour=hour, minute=rng.randint(0, 59))
                kind = rng.choices(["dine_in", "takeaway", "delivery"], [7, 2, 1])[0]
                source = rng.choices(["pos", "qr", "online"], [7, 2, 1])[0] if kind != "delivery" else "online"
                cust = rng.choice(customers) if rng.random() < .55 else None
                o = Order.objects.create(
                    restaurant=r, order_type=kind, source=source, status="accepted",
                    table=rng.choice(tables) if kind == "dine_in" else None, guests=rng.randint(1, 5),
                    customer=cust, customer_name=cust.name if cust else "", customer_phone=cust.phone if cust else "",
                    delivery_address="Panampilly Nagar, Kochi" if kind == "delivery" else "",
                    created_by=rng.choice(waiters) if source == "pos" else None, created_at=created,
                    number=f"{created:%d%m}-{rng.randint(100, 999)}{rng.randint(0, 9)}",
                )
                cart = [{"menu_item": m, "qty": rng.randint(1, 3), "note": ""}
                        for m in set(rng.choices(popular, weights, k=rng.randint(1, 4)))]
                add_items(o, cart, o.created_by, send=True)
                o.items.update(kot_status="served", created_at=created)
                if rng.random() < .04:
                    o.status = "cancelled"
                    o.save()
                    continue
                if rng.random() < .15:
                    o.discount = (o.subtotal * Decimal("0.1")).quantize(Decimal("0.01"))
                    o.recalc()
                if kind == "delivery":
                    o.rider = rng.choice(staff["rider"])
                    o.delivery_status = "delivered"
                    o.save()
                mark_billed(o)
                method = rng.choices(["cash", "upi", "card"], [4, 5, 1])[0]
                record_payments(o, [(method, o.total, None, "COD" if kind == "delivery" and method == "cash" else "")],
                                staff["cashier"][0])
                Order.objects.filter(pk=o.pk).update(billed_at=created + timedelta(minutes=40),
                                                     completed_at=created + timedelta(minutes=45))
                Payment.objects.filter(order=o).update(created_at=created + timedelta(minutes=45))
        for t in Table.objects.filter(restaurant=r):
            t.status, t.locked_by = "free", None
            t.save()

        # ------------------------------------------------------ live service
        def live(table, dishes, by, status="accepted", minutes=10, kot="new", source="pos"):
            o = Order.objects.create(restaurant=r, table=table, order_type="dine_in", source=source, status=status,
                                     guests=2, created_by=by, created_at=now - timedelta(minutes=minutes))
            add_items(o, [{"menu_item": m, "qty": q, "note": n} for m, q, n in dishes], by, send=kot != "pending")
            o.items.update(kot_status=kot, sent_at=now - timedelta(minutes=minutes))
            if table:
                table.status = "occupied" if status != "awaiting" else table.status
                table.locked_by = by if status != "awaiting" else None
                table.locked_at = now
                table.save()
            return o

        by_name = {m.name: m for m in items}
        cap1, cap2 = staff["captain"]
        live(tables[0], [(by_name["Chicken Biriyani"], 2, ""), (by_name["Fresh Lime Soda"], 2, "less sugar")], cap1, minutes=6)
        live(tables[2], [(by_name["Appam with Stew"], 3, ""), (by_name["Beef Fry"], 1, "extra spicy")], cap2, "preparing", 14, "preparing")
        live(tables[4], [(by_name["Kerala Fish Curry"], 1, ""), (by_name["Malabar Porotta"], 4, "")], cap1, "ready", 24, "ready")
        b = live(tables[6], [(by_name["Butter Chicken"], 1, ""), (by_name["Butter Naan"], 3, ""), (by_name["Mango Lassi"], 2, "")], cap2, "served", 48, "served")
        mark_billed(b)
        live(tables[8], [(by_name["Masala Dosa"], 2, ""), (by_name["Filter Coffee"], 2, "")], None, "awaiting", 2, "pending", source="qr")
        tables[10].status = "reserved"
        tables[10].save()
        tables[12].status = "cleaning"
        tables[12].save()
        WaiterCall.objects.create(restaurant=r, table=tables[2], reason="Need water")

        d = Order.objects.create(restaurant=r, order_type="delivery", source="online", status="accepted",
                                 customer=customers[0], customer_name=customers[0].name, customer_phone=customers[0].phone,
                                 delivery_address="12/B, Kadavanthra, Kochi", created_at=now - timedelta(minutes=18))
        add_items(d, [{"menu_item": by_name["Beef Biriyani"], "qty": 2, "note": ""}], None)
        tk = Order.objects.create(restaurant=r, order_type="takeaway", source="pos", status="accepted",
                                  customer_name="Walk-in", created_by=staff["cashier"][0], created_at=now - timedelta(minutes=5))
        add_items(tk, [{"menu_item": by_name["Chicken 65"], "qty": 1, "note": ""}, {"menu_item": by_name["Sulaimani"], "qty": 2, "note": ""}], staff["cashier"][0])

        # ------------------------------------------- inventory, coupons, devices
        for name, unit, qty, reorder, cost in [
            ("Basmati rice", "kg", 42, 20, 110), ("Chicken", "kg", 8, 15, 210), ("Beef", "kg", 12, 10, 380),
            ("Seer fish", "kg", 4, 5, 720), ("Coconut oil", "l", 18, 10, 190), ("Milk", "l", 22, 15, 56),
            ("Paneer", "kg", 3, 4, 360), ("Onion", "kg", 35, 20, 32), ("Tea powder", "kg", 2, 1, 480),
            ("Takeaway boxes", "pcs", 140, 100, 6),
        ]:
            InventoryItem.objects.create(restaurant=r, name=name, unit=unit, quantity=qty, reorder_level=reorder,
                                         cost_per_unit=cost, supplier="Ernakulam Market")
        Coupon.objects.create(restaurant=r, code="WELCOME10", description="10% off your first order",
                              discount_type="percent", value=10, min_order=200, max_discount=100)
        Coupon.objects.create(restaurant=r, code="FEAST50", description="₹50 off above ₹600", discount_type="flat",
                              value=50, min_order=600)
        Device.objects.create(restaurant=r, name="Counter printer", kind="bill_printer", connection="usb", paper_width="80")
        Device.objects.create(restaurant=r, name="Kitchen KOT printer", kind="kot_printer", connection="lan",
                              address="192.168.1.50", station="Main kitchen")

        # ------------------------------------------------ platform payments
        gst = ps.gst_percent
        for months_ago in (2, 1, 0):
            amount = plans["Medium"].price_monthly
            p = PlatformPayment.objects.create(
                restaurant=r, plan=plans["Medium"], billing_cycle="monthly", amount=amount,
                gst_amount=(amount * gst / 100).quantize(Decimal("0.01")),
                total=amount + (amount * gst / 100).quantize(Decimal("0.01")), method="razorpay",
                razorpay_payment_id=f"pay_demo{months_ago}", status="paid",
                invoice_no=f"FX-DEMO-{3 - months_ago:04d}",
                paid_at=now - timedelta(days=30 * months_ago + 20),
            )
            PlatformPayment.objects.filter(pk=p.pk).update(created_at=p.paid_at)

        # --------------------------------------------- a second (trial) client
        cafe = Restaurant.objects.create(name="Cafe Mocha", slug="cafe-mocha", business_type="cafe", city="Thrissur",
                                         phone="9000000020")
        Subscription.objects.create(restaurant=cafe, plan=plans["Average"], status="trial",
                                    current_period_end=now + timedelta(days=5))
        User.objects.create_user("mocha.owner", "owner@cafemocha.in", "demo123", first_name="Priya", last_name="Varghese",
                                 phone="9000000020", role="owner", restaurant=cafe)
        bootstrap_restaurant(cafe)

        ActivityLog.objects.create(actor=admin, restaurant=r, action="Restaurant onboarded", detail="FoodyX on Medium")
        ActivityLog.objects.create(actor=admin, restaurant=cafe, action="Restaurant onboarded", detail="Cafe Mocha on Average trial")

        self.stdout.write(self.style.SUCCESS("Demo data ready."))
        self.stdout.write("  Super admin   → admin / admin123                (/platform/)")
        self.stdout.write("  Owner         → 9000000001 / demo123            (/app/)")
        self.stdout.write("  Captain       → 9000000003 / demo123")
        self.stdout.write("  Cashier       → 9000000005 / demo123")
        self.stdout.write("  Kitchen       → 9000000006 / demo123")
        self.stdout.write("  Rider         → 9000000007 / demo123")
        self.stdout.write("  Online store  → /s/foodyx/")
