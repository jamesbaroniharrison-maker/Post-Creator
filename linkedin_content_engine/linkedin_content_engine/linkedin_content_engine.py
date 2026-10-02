"""Personal LinkedIn Content Engine - Reflex app entrypoint.

Multiple focused pages (request: "don't want everything to be on one big page")
instead of the original single dashboard page.

Login is back (request: remote access via Tailscale means the dashboard is no longer
guaranteed to only be reachable from this one machine) - see CLAUDE.md.
"""

import reflex as rx
import reflex_local_auth

from . import models  # noqa: F401 - registers tables for Alembic autogenerate
from .dashboard.pages.home import home_page
from .dashboard.pages.posts import posts_page
from .dashboard.pages.settings import settings_page
from .dashboard.pages.statistics import statistics_page
from .dashboard.pages.topic_bank import topic_bank_page
from .dashboard.pages.voice import voice_page

# Baroni sunflower mark as the browser-tab favicon, replacing Reflex's default -
# rx.App has no dedicated favicon param in this version, so it's a plain head <link>.
app = rx.App(
    stylesheets=["/design_tokens.css"],
    head_components=[rx.el.link(rel="icon", href="/logos/baroni-favicon.svg", type="image/svg+xml")],
)
app.add_page(home_page, route="/")
app.add_page(posts_page, route="/posts")
app.add_page(topic_bank_page, route="/topic-bank")
app.add_page(statistics_page, route="/statistics")
app.add_page(voice_page, route="/voice")
app.add_page(settings_page, route="/settings")
app.add_page(reflex_local_auth.pages.login_page, route=reflex_local_auth.routes.LOGIN_ROUTE)
# No public registration route by design - this is a single-user system; the one
# account is created directly, not via self-service signup.
