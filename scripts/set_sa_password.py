#!/usr/bin/env python3
"""
Usage: python scripts/set_sa_password.py <email> <new_password>

Sets (or resets) the password for a SUPER_ADMIN account so they can log in
via the separate super-admin panel (/sa/login).
"""
import asyncio
import sys

sys.path.insert(0, ".")

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.modules.user_management.models import User, UserRole


async def set_password(email: str, password: str) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if not user:
            print(f"ERROR: No user found with email '{email}'")
            sys.exit(1)

        if user.role != UserRole.SUPER_ADMIN:
            print(f"ERROR: User '{email}' has role '{user.role}', not SUPER_ADMIN.")
            print("Only SUPER_ADMIN accounts can use the super-admin panel.")
            sys.exit(1)

        user.password_hash = hash_password(password)
        await db.commit()
        print(f"OK: Password set for super-admin '{email}'")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python scripts/set_sa_password.py <email> <new_password>")
        sys.exit(1)

    email, password = sys.argv[1], sys.argv[2]

    if len(password) < 8:
        print("ERROR: Password must be at least 8 characters")
        sys.exit(1)

    asyncio.run(set_password(email, password))
