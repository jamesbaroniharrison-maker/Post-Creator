import dotenv
import reflex as rx

# Every entrypoint imports `config` from this module, so loading .env here (rather than
# in each script) guarantees API keys are in os.environ before anything reads them.
dotenv.load_dotenv()

config = rx.Config(
    app_name="wpa_content_engine",
    db_url="sqlite:///wpa_content_engine.db",
    plugins=[
        rx.plugins.SitemapPlugin(),
        rx.plugins.TailwindV4Plugin(),
    ]
)