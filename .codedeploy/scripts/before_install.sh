#!/bin/bash
set -e

APP_DIR="/opt/of-launch"

mkdir -p "$APP_DIR"

rm -f "$APP_DIR/docker-compose.yml" "$APP_DIR/.image_tag"

chown ubuntu:ubuntu "$APP_DIR"
