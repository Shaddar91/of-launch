"""Deployment history page with filters and pagination."""

import zoneinfo
from datetime import datetime, timedelta

from flask import Blueprint, flash, redirect, render_template, request

from of_launch.config import clusters, settings
from of_launch.utils.auth import login_required
from of_launch.utils.db import read_deployment_records

history = Blueprint("history", __name__)


def _time_filters(time_range, start_date, end_date):
    now = datetime.now()
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    ranges = {
        "today": (start_of_day, now),
        "yesterday": (start_of_day - timedelta(days=1), start_of_day - timedelta(microseconds=1)),
        "last_2_days": (now - timedelta(days=2), now),
        "last_7_days": (now - timedelta(days=7), now),
        "last_1_months": (now - timedelta(days=30), now),
    }
    if time_range in ranges:
        start, end = ranges[time_range]
        return {"deployment_time_start": start, "deployment_time_end": end}
    filters = {}
    if time_range == "custom":
        for key, value, label in (
            ("deployment_time_start", start_date, "start"),
            ("deployment_time_end", end_date, "end"),
        ):
            if value:
                try:
                    filters[key] = datetime.fromisoformat(value)
                except ValueError:
                    flash(f"Invalid {label} date format", "error")
    return filters


@history.route("/deployment-history")
@login_required
def deployment_history():
    page = request.args.get("page", 1, type=int)
    per_page = min(100, max(5, request.args.get("per_page", settings.PER_PAGE_DEFAULT, type=int)))

    filters = {}
    for param, field in (
        ("environment", "environment"),
        ("service", "service_name"),
        ("deployment_type", "deployment_type"),
    ):
        value = request.args.get(param)
        if value:
            filters[field] = value
    filters.update(
        _time_filters(
            request.args.get("time_range"), request.args.get("start_date"), request.args.get("end_date")
        )
    )

    success, records, total_count, total_pages, message = read_deployment_records(
        filters=filters or None, page=page, per_page=per_page
    )
    if not success:
        flash(f"Failed to fetch deployment history: {message}", "error")
        return redirect("/")

    tz = zoneinfo.ZoneInfo(settings.DISPLAY_TIMEZONE)
    serialized_records = [
        {
            "user": row["user"],
            "environment": row["environment"],
            "service": row.get("service_name", "Unknown"),
            "image_tag": row["image_tag"],
            "deployment_type": row.get("deployment_type", "frontend"),
            "status": row.get("status", "triggered"),
            "deployment_time": row["deployment_time"].astimezone(tz).strftime("%Y-%m-%d %H:%M:%S"),
        }
        for row in records
    ]

    has_prev = page > 1
    has_next = page < total_pages
    pagination_info = {
        "page": page,
        "per_page": per_page,
        "total_count": total_count,
        "total_pages": total_pages,
        "has_prev": has_prev,
        "has_next": has_next,
        "prev_num": page - 1 if has_prev else None,
        "next_num": page + 1 if has_next else None,
        "page_range": list(range(max(1, page - 2), min(total_pages, page + 2) + 1)),
        "start_record": (page - 1) * per_page + 1 if total_count > 0 else 0,
        "end_record": min(page * per_page, total_count),
    }

    return render_template(
        "deployment_history.html",
        records=serialized_records,
        available_environments=clusters.environments(),
        available_services=clusters.service_names(),
        pagination=pagination_info,
    )
