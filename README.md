# FoodyX — Restaurant Management System

FoodyX is a Python **Django** web application for running restaurants, cafés, cloud kitchens and hotels.
It has two panels and a set of guest-facing pages:

| Area | URL | Who uses it |
|------|-----|-------------|
| Public website | `/` | Visitors — features, pricing, FAQ, sign-up |
| **Super Admin panel** | `/platform/` | FoodyX team — plans, restaurants, payments, access |
| **Restaurant panel** | `/app/` | Owner, Admin, Manager, Captain, Cashier, Kitchen, Rider, Store keeper |
| QR table menu | `/t/<table-token>/` | Guests at a table |
| Online store | `/s/<restaurant-slug>/` | Guests ordering takeaway / delivery |
| Order tracking | `/o/<order-id>/` | Guests |
| Raw data | `/django-admin/` | Super admin (Django admin) |

No REST API is included; everything is server-rendered Django templates.

---

## Quick start

Requires **Python 3.10+**.

```bash
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python manage.py makemigrations
python manage.py migrate
python manage.py seed_demo          # plans, super admin and a demo restaurant
python manage.py runserver
```

> If you see `no such table: ...`, the migrations have not been applied. Delete `db.sqlite3`
> (if it exists) and run `makemigrations`, `migrate` and `seed_demo` again.

Open http://127.0.0.1:8000/

### Testing QR codes and the online store on a phone

`127.0.0.1` only works on the computer itself, so a phone that scans a QR code pointing there shows
"refused to connect". To test from a phone on the same Wi-Fi, start the server with:

```bash
python manage.py runlan        # same as: python manage.py runserver 0.0.0.0:8000
```

It prints your network address (e.g. `http://192.168.1.20:8000/`). Table QR codes and the store
link automatically use that address while you are testing locally. If the phone still can't
connect, allow Python through Windows Defender Firewall for **Private networks**. In production,
set **Platform settings → Site address** and every QR code uses your real domain.

### Demo logins (created by `seed_demo`)

| Role | Login | Password | Lands on |
|------|-------|----------|----------|
| Super admin | `admin` | `admin123` | `/platform/` |
| Owner | `9000000001` | `demo123` | `/app/` |
| Manager | `9000000002` | `demo123` | |
| Captain (waiter) | `9000000003` | `demo123` | POS |
| Cashier | `9000000005` | `demo123` | |
| Kitchen | `9000000006` | `demo123` | Kitchen display |
| Rider | `9000000007` | `demo123` | Rider screen |
| Store keeper | `9000000009` | `demo123` | Inventory |
| Admin (restaurant) | `9000000010` | `demo123` | |

The demo restaurant is called **FoodyX**. Its online store is at `/s/foodyx/`. Table QR links are on **Tables & Rooms → Print QR codes**.

Run `python manage.py seed_demo --fresh` to rebuild the demo restaurant. To start with an empty platform,
skip `seed_demo` and run `python manage.py createsuperuser` — the superuser automatically becomes a
Super admin. Then create plans in **Plans & pricing**.

---

## Features

### Super Admin panel (`/platform/`)
- **Overview** — restaurants, trials, paying customers, MRR, collections, revenue chart, go-live checklist,
  plans expiring in 7 days, today's orders across all restaurants.
- **Restaurants & clients** — onboard a restaurant together with its owner login and subscription (trial or paid),
  **grant or pause access**, change plan, status and expiry, extend, reset the owner password, delete.
- **Role permissions per restaurant** — a module × role matrix that sets what each restaurant role can open.
- **Plans & pricing** — create plans (seeded as Basic, Average, Medium and Premium) with monthly and yearly prices,
  staff, table and device limits, and the features each plan unlocks.
- **Payments** — Razorpay and manual payments, GST, and printable tax invoices.
- **Users**, **Team & roles** (Super admin / Platform admin / Platform support), **Activity log**,
  **Platform settings** (site, Razorpay keys and webhook, SMTP, company GSTIN, SEO, Search Console),
  **Health check**.

### Restaurant panel (`/app/`)
- **Dashboard** — today's sales, orders, average order value, live orders, quick actions, top sellers, smart insights.
- **POS & Tables** — colour-coded tables (free, occupied, billed, reserved, cleaning), table locking so two captains
  can't enter the same table (the owner can still open it), dine-in, room service, takeaway and delivery,
  KOTs with notes, a warning for duplicate items, discounts and coupons, bill printing, split payments with change.
- **Live Orders** (refreshes on its own), **Orders** (accept or reject QR and online orders), **Bills** (search,
  reprint, export to CSV, copy for WhatsApp).
- **Kitchen Display** — tickets with timers that turn amber and then red, station filter, sound for new orders.
- **Home Delivery & Rider** — assign or auto-assign riders, online/offline, OTP on delivery, cash on delivery.
- **Menu** (categories, veg/non-veg, availability switch, bulk actions, CSV import), **Tables & Rooms** (areas,
  bulk add, printable QR codes), **Customers & Loyalty**, **Inventory**, **Reports & Insights** (charts, daily item
  sales, payment split, CSV), **Marketing & SEO** (coupons, store link, SEO).
- **Staff & Roles** (own logins, 4-digit PIN, role permission matrix), **Hardware**, **Settings**,
  **Plan & Billing** (upgrade through Razorpay, invoices).

### Roles
Owner and Admin can do everything. Manager runs the floor. Captain takes table orders. Cashier handles bills and
payments. Kitchen uses the kitchen display. Rider handles deliveries. Store keeper manages stock.
What a person can open is **their role's permissions combined with their restaurant's plan**.
A captain's login works on one device at a time.

---

## Razorpay

1. **Subscriptions (platform):** in **Platform settings → Payments**, add the Key ID, Key secret and webhook secret.
   In the Razorpay dashboard, add the webhook URL `https://<your-domain>/webhooks/razorpay/` with the events
   `payment.captured`, `order.paid` and `payment.failed`.
2. **Guest payments (each restaurant):** the owner adds their own Razorpay keys in **Settings → Online payments**,
   so the money goes straight to the restaurant.

While `DEBUG` is on and no platform keys are saved, the plan checkout shows a **test checkout** button, so you can
try upgrades without a Razorpay account.

## Email

Until SMTP is saved in Platform settings, emails (welcome mails, password resets) are printed to the console.

---

## Deploy to Vercel

The repo includes `vercel.json`, WhiteNoise for static files and `DATABASE_URL` support.
Vercel runs Django as a serverless function, so it needs an external **PostgreSQL** database
(SQLite files are not kept between requests).

1. **Commit your migrations** (generated locally by `makemigrations`):
   `git add core/migrations saas/migrations restaurant/migrations && git commit -m "Add migrations" && git push`
2. **Create a free Postgres database**, e.g. on [Neon](https://neon.tech). Copy its connection string
   (`postgresql://user:pass@host/db?sslmode=require`).
3. **Create the tables and demo data** from your computer, pointing at that database:
   ```bash
   pip install -r requirements.txt
   # Windows PowerShell:  $env:DATABASE_URL="postgresql://..."
   # macOS / Linux:       export DATABASE_URL="postgresql://..."
   python manage.py migrate
   python manage.py seed_demo
   ```
4. **Import the GitHub repo in Vercel** (vercel.com → Add New → Project → FoodyX). Framework preset: *Other*.
5. **Add environment variables** in the Vercel project before deploying:

   | Name | Value |
   |------|-------|
   | `DATABASE_URL` | the Postgres connection string |
   | `FOODYX_SECRET_KEY` | a long random string |

6. **Deploy.** Your site is live at `https://<project-name>.vercel.app`. Then sign in as `admin` and set
   **Platform settings → Site address** to that URL so QR codes and emails use it.

## Production checklist

Set these environment variables:

```bash
export FOODYX_SECRET_KEY="a-long-random-string"
export FOODYX_DEBUG=0
export FOODYX_ALLOWED_HOSTS="foodyx.example.com"
export FOODYX_CSRF_TRUSTED_ORIGINS="https://foodyx.example.com"
python manage.py collectstatic
```

Serve with gunicorn or uWSGI behind nginx over HTTPS. SQLite is fine for a pilot; for production, switch
`DATABASES` in `foodyx/settings.py` to PostgreSQL or MySQL.

## Project layout

```
foodyx/       settings and root URLs
core/         custom User (roles), sign-in, public website, RBAC, Razorpay client, template tags, seed command
saas/         Super Admin: plans, subscriptions, platform payments, settings, activity log, webhook
restaurant/   restaurant panel: models, services (orders, payments, insights), views per module
storefront/   QR table menu, online store, guest payments, order tracking
templates/    all HTML (layouts, platform, restaurant, public, storefront)
static/       foodyx.css (design system) and foodyx.js
```
