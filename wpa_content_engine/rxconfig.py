import reflex as rx

config = rx.Config(
    app_name="wpa_content_engine",
    db_url="sqlite:///wpa_content_engine.db",
    plugins=[
        rx.plugins.SitemapPlugin(),
        rx.plugins.TailwindV4Plugin(),
    ]
)