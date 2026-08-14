"""WPA LinkedIn Content Engine - Reflex app entrypoint."""

import reflex as rx
import reflex_local_auth

from . import models  # noqa: F401 - registers tables for Alembic autogenerate
from .dashboard.page import dashboard_page

app = rx.App(stylesheets=["/design_tokens.css"])
app.add_page(dashboard_page, route="/")
app.add_page(reflex_local_auth.pages.login_page, route=reflex_local_auth.routes.LOGIN_ROUTE)
# No public registration route by design - this is a single-user system (spec Â§9: "one
# user (her) to start"); her one account is created directly, not via self-service signup.
