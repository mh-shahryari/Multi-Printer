# 🖨️ Multi Printer Monitoring

**پایش لحظه‌ای پرینترهای Toshiba، HP، Canon، Brother و دستگاه‌های سنسور دما/رطوبت (ECS100G) از طریق SNMP + HTTP.**

---

## ✨ ویژگی‌ها

### 🖨️ پرینترها
- **Toshiba e‑STUDIO** : 257, 306, 2505AC, 2050C, 3015AC, 3518A و سایر سری‌ها
- **HP LaserJet** : MFP M225dn, M401dn, M425dn, M506, M527, E52645 و JetDirect
- **Canon** : MF210, MF220, MF230, MF240, LBP2330K و سایر مدل‌های MF/LBP
- **Brother** : MFC‑8510DN, NC‑8300h و سری‌های مشابه

### 🌡️ سنسورها
- **ECS100G** : پایش لحظه‌ای دما و رطوبت (۲ پورت) با SNMP v1
- نمایش وضعیت سنسورها (فعال/غیرفعال)
- پنل اختصاصی با طراحی متفاوت از پرینترها

### 📊 پایش و مانیتورینگ
- **شمارنده‌های تفکیکی** : کل، رنگی، سیاه‌سفید، کپی، پرینت، فکس، اسکن
- **سطح تونر** : درصد دقیق + نمودار مصرف (Dot Count, Mega Dots)
- **سینی‌های کاغذ** : سطح، ظرفیت، اندازه کاغذ
- **سایز کاغذ** : تفکیک A4, A3, A4R, A5, B4 برای Toshiba
- **هشدارهای فعال** : نمایش کد و پیام خطاهای دستگاه
- **وضعیت درب** : تشخیص باز بودن درب پرینتر

### 📜 ثبت رویدادها
- **ثبت خودکار چاپ** : با تشخیص دلتای صفحات (جلوگیری از ثبت اشتباه)
- **تشخیص رنگ چاپ** : سیاه‌سفید، رنگی، مختلط
- **تشخیص سایز کاغذ** : Large (A3/B4), Small (A4/A5), Mixed
- **رویدادهای دستی** : ثبت سرویس دوره‌ای و شارژ/تعویض کارتریج
- **ذخیره مقادیر قبلی** : جلوگیری از ثبت کل شمارنده پس از ریست دستگاه

### 📈 نمودار و گزارش
- **نمودار مصرف روزانه** : ۳۰ روز اخیر با قابلیت فیلتر پرینتر
- **خروجی Excel** : گزارش کامل وضعیت پرینترها + لاگ رویدادها
- **خروجی CSV** : با پشتیبانی از بازه زمانی دلخواه
- **خروجی JSON** : برای مصرف API یا تحلیل‌های سفارشی

### 🎨 رابط کاربری
- **تم دارک/لایت** : با قابلیت تغییر و ذخیره‌سازی در localStorage
- **مرتب‌سازی کارت‌ها** : کشیدن و رها کردن (Drag & Drop) با ذخیره ترتیب
- **نوار کناری (Sidebar)** : گروه‌بندی بر اساس دفاتر (امامت، سروش، فلسطین، الهیه)
- **نمایش آنلاین/آفلاین** : با نشانگر رنگی
- **Badge نوع دستگاه** : رنگی، تک‌رنگ، دماسنج
- **واکنش‌گرا (Responsive)** : نمایش مناسب در صفحات کوچک
- **اعلان Toast** : پیام‌های موفقیت، خطا و هشدار

### 🔧 مدیریت پرینترها
- **افزودن دستی** : IP، نام، community
- **افزودن انبوه** : paste لیست پرینترها
- **کشف خودکار** : جستجوی SNMP در بازه‌های IP دلخواه
- **حذف پرینتر** : با تأیید
- **نام مستعار (Nickname)** : قابل ویرایش برای هر دستگاه
- **Pull دستی** : دکمه ⟳ Pull برای به‌روزرسانی فوری

### ⚙️ فنی
- **تشخیص خودکار SNMP v1/v2c** : بدون نیاز به تنظیم دستی
- **کش نسخه SNMP** : کاهش زمان Pullهای بعدی
- **Retry خودکار** : برای OIDهای حیاتی (مقابله با timeout)
- **مدیریت هم‌زمانی** : Thread-safe با قفل‌های مناسب
- **جلوگیری از Duplicate Events** : کنترل اجرای هم‌زمان Pull
- **اعتبارسنجی OID** : ثبت خطاها در فایل log
- **اسکن OID** : در startup و به‌صورت هفتگی
- **WAL mode SQLite** : بهبود performance concurrent read/write

---

## 🔧 پیش‌نیازها

- Python 3.10 یا بالاتر
- دسترسی شبکه به پرینترها (پورت SNMP 161 باز باشد)
- (اختیاری) برای سنسورهای ECS100G: SNMP v1 فعال باشد
- (اختیاری) `openpyxl` برای خروجی Excel: `pip install openpyxl`

---

## 📦 نصب و راه‌اندازی

### 1. کلون مخزن
```bash
git clone https://github.com/mh-shahryari/multi-printer-monitoring.git
cd multi-printer-monitoring







🗂️ ساختار پروژه
text
multi-printer-monitoring/
│
├── run.py                         # نقطه ورود اصلی برنامه
├── requirements.txt               # وابستگی‌های پایتون
├── .gitignore
├── printers.json                  # لیست پرینترها (auto-generated)
├── oid_profiles.json              # پروفایل‌های OID اسکن شده (auto-generated)
├── logs.db                        # دیتابیس SQLite (auto-generated)
├── oid_validation_errors.txt      # خطاهای اعتبارسنجی (auto-generated)
│
├── config/
│   └── settings.py                # تنظیمات سراسری
│
├── core/
│   ├── __init__.py
│   ├── database.py                # عملیات SQLite
│   ├── store.py                   # داده‌های سراسری + PrevStore
│   ├── poller.py                  # چرخه pull
│   ├── device_classifier.py       # تشخیص نوع دستگاه (رنگی/تک‌رنگ/دماسنج)
│   ├── snmp/
│   │   ├── __init__.py
│   │   ├── protocol.py            # پیاده‌سازی SNMP v1/v2c
│   │   └── oid_map.py             # OIDهای اختصاصی Toshiba
│   ├── collectors/
│   │   ├── __init__.py
│   │   ├── base.py                # توابع مشترک
│   │   ├── toshiba.py             # کالکتور Toshiba
│   │   ├── hp.py                  # کالکتور HP
│   │   ├── canon.py               # کالکتور Canon
│   │   ├── brother.py             # کالکتور Brother
│   │   └── sensor.py              # کالکتور سنسور ECS100G
│   └── oid/
│       ├── __init__.py
│       ├── scanner.py             # اسکن OID
│       ├── catalog.py             # کاتالوگ OIDها
│       └── validator.py           # اعتبارسنجی OID
│
├── web/
│   ├── __init__.py                # Flask app factory
│   ├── dashboard.py               # Blueprint صفحه اصلی
│   ├── printers.py                # API مدیریت پرینترها
│   ├── logs.py                    # API رویدادها
│   ├── export_bp.py               # خروجی Excel/CSV
│   ├── discover.py                # کشف خودکار شبکه
│   ├── scan.py                    # اسکن OID
│   ├── stats.py                   # آمار روزانه
│   ├── system.py                  # وضعیت سیستم
│   └── validation.py              # اعتبارسنجی OID
│
├── templates/
│   ├── base.html                  # قالب اصلی
│   └── dashboard.html             # صفحه داشبورد
│
└── static/
    ├── css/
    │   └── style.css              # استایل‌های اصلی
    └── js/
        ├── chart.umd.min.js       # نمودار
        ├── Sortable.min.js        # Drag & Drop
        ├── dashboard.js           # منطق فرانت‌اند
        └── legacy-mode.js         # حالت نمایش قدیمی (Ctrl+Alt+5)





C:\Users\m.gazmeh\AppData\Roaming\Code\User\settings.json





