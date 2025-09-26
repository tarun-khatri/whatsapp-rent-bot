import logging
import os
import asyncio
from app import create_app

app = create_app()

if __name__ == "__main__":
    # Get port from environment variable (Railway sets this)
    port = int(os.environ.get("PORT", 8000))
    debug = os.environ.get("FLASK_ENV", "production") == "development"
    
    logging.info(f"Flask app starting on port {port}")
    # Run the app with asyncio support
    app.run(host="0.0.0.0", port=port, debug=debug)
