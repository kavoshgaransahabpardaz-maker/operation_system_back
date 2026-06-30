#!/usr/bin/env bash
# Generates all secret values needed for .env
# Run this once, then paste values into your .env file.
set -euo pipefail

echo "# Paste these into your .env"
echo ""
echo "SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
echo "REDIS_PASSWORD=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
echo "POSTGRES_PASSWORD=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
echo "TOKEN_ENCRYPTION_KEY=$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
