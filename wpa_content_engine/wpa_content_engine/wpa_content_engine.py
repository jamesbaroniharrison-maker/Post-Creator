"""WPA LinkedIn Content Engine - Reflex app entrypoint.

Multiple focused pages (request: "don't want everything to be on one big page")
instead of the original single dashboard page.
"""

import reflex as rx
import reflex_local_auth

from . import models  # noqa: F401 - registers tables for Alembic autogenerate
from .dashboard.pages.accepted import accepted_page
from .dashboard.pages.history import history_page
from .dashboard.pages.home import home_page
from .dashboard.pages.rejected import rejected_page
from .dashboard.pages.review import review_page
from .dashboard.pages.settings import settings_page
from .dashboard.pages.topic_bank import topic_bank_page

app = rx.App(stylesheets=["/design_tokens.css"])
app.add_page(home_page, route="/")
app.add_page(review_page, route="/review")
app.add_page(accepted_page, route="/accepted")
app.add_page(rejected_page, route="/rejected")
app.add_page(topic_bank_page, route="/topic-bank")
app.add_page(history_page, route="/history")
app.add_page(settings_page, route="/settings")
app.add_page(reflex_local_auth.pages.login_page, route=reflex_local_auth.routes.LOGIN_ROUTE)
# No public registration route by design - this is a single-user system (spec Â§9: "one
# user (her) to start"); her one account is created directly, not via self-service signup.
