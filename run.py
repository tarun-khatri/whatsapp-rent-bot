import logging
import asyncio
from app import create_app

app = create_app()

if __name__ == "__main__":
    logging.info("Flask app started")
    # Run the app with asyncio support
    app.run(host="0.0.0.0", port=8000, debug=True)
