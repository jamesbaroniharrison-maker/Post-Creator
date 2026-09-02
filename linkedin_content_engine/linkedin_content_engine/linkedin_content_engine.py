"""Personal LinkedIn Content Engine - Reflex app entrypoint.

Multiple focused pages (request: "don't want everything to be on one big page")
instead of the original single dashboard page.

No login/auth - this app is localhost-only, single-user, single-machine (request:
"it's locally hosted, removed the login page"). If it's ever exposed beyond
localhost, auth needs to come back before that happens.
"""

import reflex as rx

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
