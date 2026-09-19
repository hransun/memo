"""Entry point: uvicorn app:app. Read memo/application.py for application setup."""
from memo.application import create_app

app = create_app()

# Compatibility for existing local scripts and regression tests.
database = app.state.store.connection
UPLOADS = app.state.service.uploads
TOKEN = app.state.token
