"""
keep_alive.py
Lightweight Flask server so UptimeRobot can ping the Replit instance
and keep the bot alive on the free tier.
"""

import logging
import threading
from flask import Flask

log = logging.getLogger(__name__)

app = Flask(__name__)


@app.route("/")
def home():
    """Health check endpoint for UptimeRobot."""
    return "⚡ Spark Bot is alive and running!", 200


@app.route("/health")
def health():
    """Detailed health endpoint."""
    return {"status": "ok", "bot": "Spark", "version": "1.0.0"}, 200


def run():
    """Start the Flask server on port 8080."""
    app.run(host="0.0.0.0", port=8080, debug=False, use_reloader=False)


def keep_alive():
    """Launch the Flask server in a background daemon thread."""
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    log.info("Keep-alive server started on port 8080.")
