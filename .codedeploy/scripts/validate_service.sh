#!/bin/bash
set -e

if ! systemctl is-active --quiet of-launch; then
  echo "ERROR: of-launch service not active"
  systemctl status of-launch
  exit 1
fi

for i in {1..10}; do
  if curl -sf -o /dev/null -w "%{http_code}" http://127.0.0.1:5000/ 2>&1 | grep -qE "^(200|302)"; then
    echo "Health check passed on attempt $i"
    exit 0
  fi
  echo "Attempt $i: waiting for app..."
  sleep 3
done

echo "ERROR: health check failed after 10 attempts"
docker logs "$(docker ps -qf "name=of-launch-app" | head -1)" --tail 50 2>&1 || true
exit 1
