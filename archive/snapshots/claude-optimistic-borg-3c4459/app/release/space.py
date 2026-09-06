"""Hosting entry point: the application object a Space server imports."""

from app.release.app import create_release_app

app = create_release_app()
