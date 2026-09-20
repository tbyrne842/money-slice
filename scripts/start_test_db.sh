#!/usr/bin/env bash
# Starts the local MongoDB container (from docker-compose.yml) and waits
# until it's actually accepting connections before exiting - useful to
# run before `pytest` if you want tests to hit a real instance, or before
# a manual import/mongosh session.
set -euo pipefail
 
cd "$(dirname "$0")/.."  # run from project root regardless of cwd
 
echo "Starting mongo container..."
docker compose -f docker/mongo_db.yaml up -d mongo
 
echo "Waiting for MongoDB to accept connections..."
for i in $(seq 1 30); do
    if docker compose exec -T mongo mongosh --quiet --eval "db.adminCommand('ping')" >/dev/null 2>&1; then
        echo "MongoDB is up (mongodb://localhost:27017)"
        exit 0
    fi
    sleep 1
done
 
echo "MongoDB did not become ready in time. Check logs with:"
echo "  docker compose logs mongo"
exit 1
 