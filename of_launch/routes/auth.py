"""Login and logout."""

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from of_launch.utils.db import verify_user

auth = Blueprint("auth", __name__)


@auth.route("/login", methods=["GET", "POST"])
def login():
    if session.get("logged_in"):
        return redirect(url_for("main.index"))

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username and password:
            is_valid, role_or_message = verify_user(username, password)
            if is_valid:
                session["logged_in"] = True
                session["username"] = username
                session["role"] = role_or_message
                return redirect(url_for("main.index"))
            flash(f"Login failed: {role_or_message}", "error")
        else:
            flash("Please enter both username and password.", "error")

    return render_template("login.html")


@auth.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out successfully.", "success")
    return redirect(url_for("auth.login"))
