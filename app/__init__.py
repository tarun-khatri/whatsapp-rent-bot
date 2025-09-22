import os
import structlog
from flask import Flask
from app.config import load_configurations, configure_logging
from .views import webhook_blueprint

logger = structlog.get_logger(__name__)


def create_app():
    app = Flask(__name__)

    # Load configurations and logging settings
    load_configurations(app)
    configure_logging()

    # Set start time for monitoring
    app.config["START_TIME"] = structlog.get_logger().info("Application started")

    # Import and register blueprints
    app.register_blueprint(webhook_blueprint)

    # Import services (they will initialize lazily when first used)
    try:
        from .services.supabase_service import supabase_service
        from .services.whatsapp_service import whatsapp_service
        from .services.vertex_ai_service import vertex_ai_service
        from .services.document_ai_service import document_ai_service
        from .services.conversation_flow_service import conversation_flow_service
        
        logger.info("All services imported successfully (will initialize on first use)")
    except Exception as e:
        logger.error("Failed to import services", error=str(e))
        # Don't fail app creation, but log the error

    return app
