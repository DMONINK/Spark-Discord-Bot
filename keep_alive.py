"""
Spark Bot - Keep Alive Module
Lightweight Flask server to keep bot alive on Replit free tier
"""

from flask import Flask
import logging

logger = logging.getLogger(__name__)

app = Flask(__name__)


@app.route('/')
def home():
    """Health check endpoint"""
    return "⚡ Spark Bot is alive!", 200


@app.route('/ping')
def ping():
    """Ping endpoint for UptimeRobot"""
    return {"status": "online"}, 200


def run():
    """Start the Flask server"""
    try:
        app.run(host='0.0.0.0', port=8080, debug=False)
    except Exception as e:
        logger.error(f"Keep-alive server error: {e}")


if __name__ == "__main__":
    run()
