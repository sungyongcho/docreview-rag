"""Hugging Face Docker Space entrypoint; canned mode is the default."""

from app.release import create_release_app

app = create_release_app()
