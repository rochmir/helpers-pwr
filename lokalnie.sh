#!/bin/sh
# Test lokalny w Dockerze (Linux/macOS/Git Bash). Zmiany w app/ widać od razu (live reload).
cd "$(dirname "$0")" || exit 1
echo "Strona: http://localhost:${HELPERS_PORT:-8000}"
echo "Panel:  http://localhost:${HELPERS_PORT:-8000}/login  (login: admin, hasło: dev)  (Ctrl+C zatrzymuje)"
exec docker compose -f docker-compose.local.yml up --build
