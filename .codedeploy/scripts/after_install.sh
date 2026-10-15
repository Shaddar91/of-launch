#!/bin/bash
set -e

APP_DIR="/opt/of-launch"

if [ ! -f "$APP_DIR/.image_tag" ]; then
  echo "ERROR: .image_tag not found"
  exit 1
fi

if [ ! -f "$APP_DIR/docker-compose.yml" ]; then
  echo "ERROR: docker-compose.yml not found"
  exit 1
fi

chown -R ubuntu:ubuntu "$APP_DIR"
