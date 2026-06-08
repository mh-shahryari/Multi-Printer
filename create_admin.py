#!/usr/bin/env python3
"""
اسکریپت ساخت ادمین اولیه
اجرا: python create_admin.py
"""

import sys
import os

# اطمینان از مسیر پروژه
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from config import settings  # noqa: trigger SECRET_KEY check
from core.database import init_db
from models import User


def main():
    print()
    print("=" * 50)
    print("  PrintGuard - Create Admin User")
    print("=" * 50)
    print()

    # راه‌اندازی دیتابیس
    init_db()
    print("  [OK] Database initialized")
    print()

    # بررسی ادمین موجود
    existing_admins = [u for u in User.all() if u.get("role") == "admin"]
    if existing_admins:
        print("  Admin users already exist:")
        for u in existing_admins:
            print(f"    - {u['username']} ({u['email']})")
        print()
        choice = input("  Create another admin? (y/N): ").strip().lower()
        if choice != "y":
            print("  Cancelled.")
            return

    # دریافت اطلاعات
    print("  Enter admin details:")
    print()
    
    username = input("  Username: ").strip()
    if not username:
        print("  [ERROR] Username is required")
        return

    # بررسی تکراری
    if User.find_by_identifier(username):
        print(f"  [ERROR] Username '{username}' already exists")
        
        # پیشنهاد: تغییر نقش کاربر موجود
        user = User.find_by_identifier(username)
        if user and user.get("role") != "admin":
            choice = input(f"  Promote '{username}' to admin? (y/N): ").strip().lower()
            if choice == "y":
                from models import User as UserModel
                u = UserModel.get(user["id"])
                if u.set_role("admin") and u.set_verified(True):
                    print(f"  [OK] '{username}' promoted to admin and verified!")
                else:
                    print("  [ERROR] Failed to promote user")
        return

    email = input("  Email: ").strip()
    if not email:
        print("  [ERROR] Email is required")
        return

    if User.find_by_email(email):
        print(f"  [ERROR] Email '{email}' already exists")
        return

    password = input("  Password: ").strip()
    if not password or len(password) < 6:
        print("  [ERROR] Password must be at least 6 characters")
        return

    confirm = input("  Confirm password: ").strip()
    if password != confirm:
        print("  [ERROR] Passwords do not match")
        return

    # ساخت کاربر
    user = User.create(
        username=username,
        email=email,
        password=password,
        role="admin",
        is_verified=True,
    )

    if user:
        print()
        print("  " + "=" * 40)
        print("  ✓ Admin user created successfully!")
        print(f"  Username: {username}")
        print(f"  Email:    {email}")
        print(f"  Role:     admin")
        print(f"  Verified: Yes")
        print("  " + "=" * 40)
        print()
        print("  You can now login at http://localhost:5053/login")
        print()
    else:
        print("  [ERROR] Failed to create admin user")
        print("  Check the logs for details.")


if __name__ == "__main__":
    main()
