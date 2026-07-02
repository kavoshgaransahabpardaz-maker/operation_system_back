# BrokerAI — Intelligent Customs Brokerage Document Platform

AI-powered backend that automatically ingests shipment documents from email and uploads, classifies them with OpenAI, groups them into shipments, and provides a workspace dashboard for customs brokers.

- **API docs:** https://api.veritariffai.co/docs
- **Health check:** https://api.veritariffai.co/health

---

## Table of Contents

- [Features](#features)
- [Tech Stack](#tech-stack)
- [Local Development](#local-development)
- [Production Deployment](#production-deployment)
  - [1. Server Setup](#1-server-setup)
  - [2. Copy the Project](#2-copy-the-project)
  - [3. Configure Environment](#3-configure-environment)
  - [4. First Deploy (HTTP)](#4-first-deploy-http)
  - [5. Issue SSL Certificate](#5-issue-ssl-certificate)
  - [6. Switch to HTTPS](#6-switch-to-https)
  - [7. Verify](#7-verify)
- [Updating the Application](#updating-the-application)
- [Operations Reference](#operations-reference)
- [API Overview](#api-overview)
- [Architecture](#architecture)

---

## Features

- **Document ingestion** — upload via API or auto-collect from IMAP / Gmail / Microsoft 365 mailboxes
- **OCR pipeline** — pdfplumber for native PDFs, pytesseract fallback for scanned documents
- **AI classification** — OpenAI gpt-4o-mini classifies documents into 10 types (invoice, packing list, B/L, AWB, etc.)
- **Shipment matching** — regex + LLM extracts BL/AWB/container/PO numbers and groups documents into shipments
- **Duplicate detection** — SHA-256 content hashing rejects duplicate uploads with a 409
- **Workspace dashboard** — stats, recent imports, shipment detail, activity log
- **RBAC** — Admin / Manager / Operator roles, JWT auth
- **Multi-tenancy** — all data isolated by `org_id`

---

## Tech Stack

| Layer | Technology |
|---|---|
| API | Python 3.11 · FastAPI · uvicorn |
| Database | PostgreSQL 16 · SQLAlchemy 2.0 (asyncpg) |
| Task queue | Celery · Redis (4 queues: email, classification, matching, default) |
| Object storage | MinIO / S3-compatible (boto3) |
| AI | OpenAI API (gpt-4o-mini) |
| OCR | pdfplumber · pytesseract · Pillow |
| Auth | JWT (python-jose) · bcrypt · Fernet token encryption |
| Proxy | Nginx 1.27 · Let's Encrypt (certbot) |

---

## Local Development

**Requirements:** Docker, Docker Compose

```bash
# 1. Clone
git clone <repo-url> && cd operating_system_cb_back

# 2. Create local env
cp .env.example .env
# Edit .env — set at minimum SECRET_KEY, OPENAI_API_KEY, TOKEN_ENCRYPTION_KEY

# 3. Start all services with hot reload
docker compose up --build

# 4. Run migrations
docker compose exec api alembic upgrade head
```

| URL | Purpose |
|---|---|
| http://localhost:8000 | API |
| http://localhost:8000/docs | Swagger UI |
| http://localhost:9001 | MinIO console (minioadmin / minioadmin) |

**Run tests:**
```bash
docker compose run --rm api python -m pytest tests/ -q
# or with local venv:
.venv/bin/python -m pytest tests/ -q
```

**Generate a new migration after model changes:**
```bash
docker compose run --rm api alembic revision --autogenerate -m "description"
```

---

## Production Deployment

### Stack

| Service | Image | Role |
|---|---|---|
| **api** | `python:3.11-slim` (built locally) | FastAPI + uvicorn (4 workers) |
| **worker** | same image | Celery worker (4 concurrency) |
| **beat** | same image | Celery beat scheduler |
| **migrate** | same image | Alembic one-shot at startup |
| **db** | `postgres:16-alpine` | Primary database |
| **redis** | `redis:7-alpine` | Broker + result backend |
| **minio** | `minio/minio` | Object storage |
| **nginx** | `nginx:1.27-alpine` | TLS termination + reverse proxy |
| **certbot** | `certbot/certbot` | Let's Encrypt SSL, auto-renews every 12 h |

> **Important:** The image `brokerai:latest` is built locally on the server — it is not pulled from a registry. You must run `docker compose -f docker-compose.prod.yml build` before `up -d`.

---

### 1. Server Setup

A Debian/Ubuntu VPS with at least **2 GB RAM** and **20 GB disk**.

**DNS:** Add an A record for `api.veritariffai.co` pointing to the server's public IP. SSL issuance will fail if DNS has not propagated.

**Install Docker** (run as root):

```bash
curl -fsSL https://get.docker.com | sh
```

Verify:
```bash
docker --version         # Docker 26+
docker compose version   # Compose v2.x
```

---

### 2. Copy the Project

**Option A — rsync from local machine:**
```bash
rsync -av \
  --exclude='.venv' --exclude='__pycache__' --exclude='.env*' --exclude='*.pyc' \
  /path/to/operating_system_cb_back/ \
  root@YOUR_SERVER_IP:/opt/operation_system_back/
```

**Option B — git clone on the server:**
```bash
git clone <repo-url> /opt/operation_system_back
cd /opt/operation_system_back
```

---

### 3. Configure Environment

```bash
cp .env.production .env
nano .env
```

Fill in every value. Generate secrets with:

```bash
# SECRET_KEY
openssl rand -hex 32

# POSTGRES_PASSWORD, REDIS_PASSWORD
openssl rand -base64 24

# TOKEN_ENCRYPTION_KEY (Fernet key)
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Or generate all at once:
```bash
bash scripts/generate_secrets.sh
```

Key variables:

| Variable | Notes |
|---|---|
| `SECRET_KEY` | `openssl rand -hex 32` |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | DB credentials |
| `REDIS_PASSWORD` | Redis auth password |
| `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` | MinIO root credentials |
| `OPENAI_API_KEY` | Your OpenAI key (`sk-...`) |
| `TOKEN_ENCRYPTION_KEY` | 32-byte Fernet key |
| `IMAGE_TAG` | Docker image tag (default: `latest`) |

---

### 4. First Deploy (HTTP)

The default nginx config serves HTTP only so certbot can complete the ACME domain challenge.

```bash
cd /opt/operation_system_back

# Build image first (must be done on the server — not pulled from registry)
docker compose -f docker-compose.prod.yml build

# Start all services
docker compose -f docker-compose.prod.yml up -d
```

This automatically:
1. Starts postgres, redis, minio and waits for health checks
2. Runs `alembic upgrade head` via the `migrate` one-shot container
3. Starts api, worker, beat, nginx, certbot

Check everything is running:
```bash
docker compose -f docker-compose.prod.yml ps
```

Verify HTTP is responding:
```bash
curl http://api.veritariffai.co/health
# {"status":"ok"}
```

---

### 5. Issue SSL Certificate

```bash
docker compose -f docker-compose.prod.yml run --rm certbot certonly \
  --webroot \
  --webroot-path=/var/www/certbot \
  --email admin@veritariffai.co \
  --agree-tos \
  --no-eff-email \
  -d api.veritariffai.co
```

On success: `Successfully received certificate.`

---

### 6. Switch to HTTPS

```bash
cp nginx/conf.d/brokerai-ssl.conf nginx/conf.d/brokerai.conf
docker compose -f docker-compose.prod.yml exec nginx nginx -s reload
```

---

### 7. Verify

```bash
curl https://api.veritariffai.co/health
# {"status":"ok"}
```

Open in a browser: https://api.veritariffai.co/docs

---

## Updating the Application

```bash
cd /opt/operation_system_back

# Pull latest code
git pull

# Rebuild image on the server
docker compose -f docker-compose.prod.yml build api

# Run new migrations
docker compose -f docker-compose.prod.yml run --rm migrate

# Restart application containers (db/redis/minio keep running)
docker compose -f docker-compose.prod.yml up -d --no-deps api worker beat
```

Or use the deploy script:
```bash
bash scripts/deploy.sh
```

---

## Operations Reference

### Logs

```bash
docker compose -f docker-compose.prod.yml logs -f api       # API logs
docker compose -f docker-compose.prod.yml logs -f worker    # Celery worker
docker compose -f docker-compose.prod.yml logs -f nginx     # Nginx access/error
docker compose -f docker-compose.prod.yml logs -f certbot   # SSL renewal
```

### Database

```bash
# Open psql shell
docker compose -f docker-compose.prod.yml exec db \
  psql -U $POSTGRES_USER -d $POSTGRES_DB

# Backup
docker compose -f docker-compose.prod.yml exec db \
  pg_dump -U $POSTGRES_USER $POSTGRES_DB > backup_$(date +%Y%m%d).sql

# Restore
docker compose -f docker-compose.prod.yml exec -T db \
  psql -U $POSTGRES_USER $POSTGRES_DB < backup_20260101.sql
```

### SSL Certificate

Renewal is automatic (certbot container checks every 12 h).

Force manual renewal:
```bash
docker compose -f docker-compose.prod.yml exec certbot certbot renew --force-renewal
docker compose -f docker-compose.prod.yml exec nginx nginx -s reload
```

Check expiry:
```bash
docker compose -f docker-compose.prod.yml exec certbot certbot certificates
```

### Restart / Stop

```bash
docker compose -f docker-compose.prod.yml restart api       # Restart API only
docker compose -f docker-compose.prod.yml down              # Stop all (data kept)
docker compose -f docker-compose.prod.yml down -v           # Stop + DELETE all data
```

### Makefile shortcuts (dev)

```bash
make dev                         # Start dev environment
make test                        # Run test suite
make migrate                     # Run migrations
make makemigration msg="..."     # Generate migration
make secrets                     # Generate all secret values
make logs                        # Tail dev logs
make down                        # Stop dev containers
```

---

## API Overview

All endpoints are under `/api/v1`. Authentication uses `Bearer <JWT>` in the `Authorization` header.

| Module | Prefix | Key Endpoints |
|---|---|---|
| Auth & Users | `/api/v1/auth` | `POST /register`, `POST /login`, `GET /me`, `POST /password-reset` |
| Documents | `/api/v1/documents` | `POST /upload`, `GET /`, `GET /{id}`, `GET /{id}/duplicates` |
| Classification | `/api/v1/classifications` | `GET /{document_id}`, `POST /{document_id}/override` |
| Shipments | `/api/v1/shipments` | `GET /`, `GET /{id}`, `PATCH /{id}`, `POST /documents/{id}/reassociate` |
| Email | `/api/v1/email` | `POST /connections/imap`, `GET /connections`, `POST /connections/{id}/sync` |
| Workspace | `/api/v1/workspace` | `GET /dashboard`, `GET /shipments/{id}`, `GET /shipments/{id}/activity` |

Full interactive docs: https://api.veritariffai.co/docs

---

## Architecture

```
Internet
    │
    ▼
nginx:443  ── TLS (Let's Encrypt), rate limiting, proxy headers
    │
    ▼
api:8000   ── FastAPI / uvicorn (4 workers)
    │
    ├── db:5432       PostgreSQL  (internal network only)
    ├── redis:6379    Redis       (internal network only)
    └── minio:9000    MinIO       (internal network only)

worker     ── Celery worker, queues: email / classification / matching / default
beat       ── Celery beat (syncs mailboxes every 5 min)
certbot    ── Auto-renews Let's Encrypt cert every 12 h
```

**Document pipeline:**
```
Upload / Email
    │
    ▼
UPLOADED → OCR_PENDING → OCR_PROCESSING → CLASSIFIED → MATCHED
                                               │              │
                                         NEEDS_REVIEW   UNMATCHED
                                         (confidence < 0.70)
```

**Network isolation:** `db`, `redis`, and `minio` are on the `internal` Docker network — no external ports exposed. Only `nginx` faces the internet.

**Security:**
- API runs as non-root user (`brokerai`)
- `migrate` one-shot container must complete successfully before `api` starts
- Redis is password-protected in production
- OAuth tokens and IMAP passwords stored Fernet-encrypted in the database
