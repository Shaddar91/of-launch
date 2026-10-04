"""Deploy dashboard page."""

from flask import Blueprint, redirect, render_template, session, url_for

from of_launch.config import settings
from of_launch.utils.auth import login_required

main = Blueprint("main", __name__)


@main.route("/")
@login_required
def index():
    return redirect(url_for("main.deploy"))


@main.route("/deploy")
@login_required
def deploy():
    return render_template(
        "deploy.html",
        username=session.get("username"),
        role=session.get("role", settings.ROLE_SHARED_EXECUTOR),
        mock_mode=settings.MOCK_MODE,
    )
