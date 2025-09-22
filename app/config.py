import sys
import os
from dotenv import load_dotenv
import logging
import structlog


def load_configurations(app):
    load_dotenv()
    
    # WhatsApp Business API Configuration
    app.config["ACCESS_TOKEN"] = os.getenv("ACCESS_TOKEN")
    app.config["YOUR_PHONE_NUMBER"] = os.getenv("YOUR_PHONE_NUMBER")
    app.config["APP_ID"] = os.getenv("APP_ID")
    app.config["APP_SECRET"] = os.getenv("APP_SECRET")
    app.config["RECIPIENT_WAID"] = os.getenv("RECIPIENT_WAID")
    app.config["VERSION"] = os.getenv("VERSION", "v18.0")
    app.config["PHONE_NUMBER_ID"] = os.getenv("PHONE_NUMBER_ID")
    app.config["VERIFY_TOKEN"] = os.getenv("VERIFY_TOKEN")
    
    # OpenAI Configuration
    app.config["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")
    app.config["OPENAI_ASSISTANT_ID"] = os.getenv("OPENAI_ASSISTANT_ID")
    
    # Supabase Configuration
    app.config["SUPABASE_PROJECT_ID"] = os.getenv("SUPABASE_PROJECT_ID")
    app.config["SUPABASE_PUBLISHABLE_KEY"] = os.getenv("SUPABASE_PUBLISHABLE_KEY")
    app.config["SUPABASE_URL"] = os.getenv("SUPABASE_URL")
    
    # Google Cloud Services Configuration
    app.config["VERTEX_AI_PROJECT"] = os.getenv("VERTEX_AI_PROJECT")
    app.config["GOOGLE_APPLICATION_CREDENTIALS"] = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    
    # Google Document AI Processors
    app.config["OCR_PROCESSOR"] = os.getenv("OCR_PROCESSOR")
    app.config["PAYSLIP_PROCESSOR"] = os.getenv("PAYSLIP_PROCESSOR")
    app.config["BANK_PROCESSOR"] = os.getenv("BANK_PROCESSOR")
    app.config["IDENTITY_PROCESSOR"] = os.getenv("IDENTITY_PROCESSOR")
    app.config["FORM_PROCESSOR"] = os.getenv("FORM_PROCESSOR")
    
    # Google Cloud Storage Configuration
    app.config["GOOGLE_CLOUD_STORAGE_BUCKET"] = os.getenv("GOOGLE_CLOUD_STORAGE_BUCKET")
    
    # Application Configuration
    app.config["LOG_LEVEL"] = os.getenv("LOG_LEVEL", "INFO")
    app.config["MAX_FILE_SIZE_MB"] = int(os.getenv("MAX_FILE_SIZE_MB", "16"))
    app.config["DOCUMENT_AI_CONFIDENCE_THRESHOLD"] = float(os.getenv("DOCUMENT_AI_CONFIDENCE_THRESHOLD", "0.7"))
    app.config["CONVERSATION_TIMEOUT_HOURS"] = int(os.getenv("CONVERSATION_TIMEOUT_HOURS", "24"))


def configure_logging():
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    
    # Configure structlog for structured logging
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer()
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    
    # Configure standard logging
    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stdout,
    )
