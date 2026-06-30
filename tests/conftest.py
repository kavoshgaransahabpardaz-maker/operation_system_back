"""
Shared pytest fixtures for BrokerAI tests.

Strategy:
  - SQLite in-memory via aiosqlite (no PostgreSQL needed)
  - moto for S3
  - unittest.mock for OpenAI + Celery apply_async
  - FastAPI dependency overrides for auth + DB
"""
import os
import uuid
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ── env vars required by Settings before any app import ──────────────────────
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("DATABASE_URL_SYNC", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890abcdef")
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "testtesttesttesttesttesttest1234")  # 32 chars
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("S3_ACCESS_KEY_ID", "test")
os.environ.setdefault("S3_SECRET_ACCESS_KEY", "test")

from app.core.database import Base
from app.core import security as _security

# Python 3.14 breaks passlib bcrypt — patch with sha256 for tests
import hashlib as _hl

def _hash(pw: str) -> str:
    return "test:" + _hl.sha256(pw.encode()).hexdigest()

def _verify(plain: str, hashed: str) -> bool:
    return hashed == _hash(plain)

_security.hash_password = _hash
_security.verify_password = _verify

from app.core.security import create_access_token
hash_password = _hash

# Re-patch inside service module (it imported hash_password before our patch)
import app.modules.user_management.service as _um_svc
_um_svc.hash_password = _hash
_um_svc.verify_password = _verify

from app.modules.user_management.models import Organization, User, UserRole

# import all models so Base.metadata is complete
import app.modules.document_storage.models  # noqa
import app.modules.ocr_processing.models  # noqa
import app.modules.document_classification.models  # noqa
import app.modules.email_integration.models  # noqa
import app.modules.shipment_identification.models  # noqa
import app.models.activity_log  # noqa

# ── in-memory SQLite async engine ─────────────────────────────────────────────
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

@pytest_asyncio.fixture
async def engine():
    """Each test gets a fresh in-memory SQLite database for full isolation."""
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine) -> AsyncSession:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session


# ── seed data ─────────────────────────────────────────────────────────────────
@pytest_asyncio.fixture
async def test_org(db: AsyncSession) -> Organization:
    org = Organization(name="Test Org", slug=f"test-org-{uuid.uuid4().hex[:6]}")
    db.add(org)
    await db.commit()
    await db.refresh(org)
    return org


@pytest_asyncio.fixture
async def test_user(db: AsyncSession, test_org: Organization) -> User:
    user = User(
        email="admin@test.com",
        password_hash=hash_password("password123"),
        org_id=test_org.id,
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@pytest_asyncio.fixture
async def operator_user(db: AsyncSession, test_org: Organization) -> User:
    user = User(
        email="operator@test.com",
        password_hash=hash_password("password123"),
        org_id=test_org.id,
        role=UserRole.OPERATOR,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


# ── FastAPI app with overrides ────────────────────────────────────────────────
@pytest.fixture
def app_with_overrides(db: AsyncSession, test_user: User):
    from app.main import app
    from app.core.database import get_async_db
    from app.core.dependencies import get_current_user

    async def _override_db():
        yield db

    async def _override_user():
        return test_user

    app.dependency_overrides[get_async_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    yield app
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app_with_overrides) -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=app_with_overrides), base_url="http://test"
    ) as c:
        yield c


@pytest.fixture
def auth_token(test_user: User) -> str:
    return create_access_token({
        "sub": str(test_user.id),
        "org_id": str(test_user.org_id),
        "role": test_user.role,
    })


@pytest.fixture
def auth_headers(auth_token: str) -> dict:
    return {"Authorization": f"Bearer {auth_token}"}


# ── S3 mock ───────────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def mock_s3(monkeypatch):
    monkeypatch.setattr("app.core.storage.upload_file", lambda *a, **kw: "orgs/test/doc.pdf")
    monkeypatch.setattr("app.core.storage.upload_bytes", lambda *a, **kw: "orgs/test/doc.pdf")
    monkeypatch.setattr("app.core.storage.download_bytes", lambda *a, **kw: b"%PDF fake content")
    monkeypatch.setattr("app.core.storage.get_presigned_url", lambda *a, **kw: "https://s3.test/doc.pdf")
    monkeypatch.setattr("app.core.storage.ensure_bucket", lambda: None)


# ── Celery mock ───────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def mock_celery(monkeypatch):
    """Prevent Celery tasks from actually queuing during tests."""
    mock_task = MagicMock()
    mock_task.apply_async = MagicMock(return_value=MagicMock(id="fake-task-id"))
    monkeypatch.setattr(
        "app.agents.document_classifier.tasks.run_ocr_then_classify",
        mock_task,
    )
    monkeypatch.setattr(
        "app.agents.shipment_matcher.tasks.run_shipment_matching",
        mock_task,
    )
    monkeypatch.setattr(
        "app.agents.email_collector.tasks.sync_mailbox",
        mock_task,
    )
