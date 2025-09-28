import logging
import json
import asyncio
import threading
import structlog
from flask import Blueprint, request, jsonify, current_app

from .decorators.security import signature_required
from .utils.whatsapp_utils import (
    process_whatsapp_message,
    is_valid_whatsapp_message,
)

logger = structlog.get_logger(__name__)
webhook_blueprint = Blueprint("webhook", __name__)


def handle_message():
    """
    Handle incoming webhook events from the WhatsApp API.

    This function processes incoming WhatsApp messages and other events,
    such as delivery statuses. If the event is a valid message, it gets
    processed. If the incoming payload is not a recognized WhatsApp event,
    an error is returned.

    Every message send will trigger 4 HTTP requests to your webhook: message, sent, delivered, read.

    Returns:
        response: A tuple containing a JSON response and an HTTP status code.
    """
    body = request.get_json()
    logger.info("Received webhook request", body=body)

    # Check if it's a WhatsApp status update
    if (
        body.get("entry", [{}])[0]
        .get("changes", [{}])[0]
        .get("value", {})
        .get("statuses")
    ):
        logger.info("Received a WhatsApp status update")
        
        # Check for failed media downloads
        statuses = body.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {}).get("statuses", [])
        for status in statuses:
            if status.get("status") == "failed":
                errors = status.get("errors", [])
                for error in errors:
                    if error.get("code") == 131052:  # Media download error
                        logger.error("Media download failed", 
                                   recipient_id=status.get("recipient_id"),
                                   error_code=error.get("code"),
                                   error_title=error.get("title"),
                                   error_message=error.get("message"))
                        
                        # Send AI-generated error message to user about failed media download
                        try:
                            from .services.whatsapp_service import whatsapp_service
                            from .services.ai_conversation_service import ai_conversation_service
                            
                            # Get the recipient ID and format it properly
                            recipient_id = status.get("recipient_id")
                            if recipient_id:
                                # Add + prefix if not present
                                if not recipient_id.startswith("+"):
                                    recipient_id = "+" + recipient_id
                                
                                # Capture the app instance from current context
                                app_instance = current_app._get_current_object()
                                
                                # Create new event loop for this thread
                                def send_ai_error_message():
                                    loop = asyncio.new_event_loop()
                                    asyncio.set_event_loop(loop)
                                    try:
                                        # Push app context to the thread using the captured app instance
                                        with app_instance.app_context():
                                            # Generate AI-powered error message
                                            ai_error_response = loop.run_until_complete(
                                                ai_conversation_service.generate_media_error_response(
                                                    phone_number=recipient_id,
                                                    user_message="media_upload_failed",
                                                    error_context={
                                                        "error_type": "webhook_media_download_failed",
                                                        "error_code": error.get("code"),
                                                        "error_title": error.get("title"),
                                                        "retry_attempts": 0,  # This is from webhook, no retries attempted
                                                        "suggestions": [
                                                            "נסה לשלוח תמונה קטנה יותר (פחות מ-1MB)",
                                                            "נסה תמונה בפורמט JPEG או PNG",
                                                            "ודא שהתמונה לא פגומה",
                                                            "נסה לצלם מחדש במקום לשלוח מהגלריה"
                                                        ]
                                                    }
                                                )
                                            )
                                            
                                            loop.run_until_complete(whatsapp_service.send_text_message(recipient_id, ai_error_response))
                                            logger.info("AI error message sent to user", recipient_id=recipient_id)
                                    finally:
                                        loop.close()
                                
                                # Send in background thread
                                thread = threading.Thread(target=send_ai_error_message)
                                thread.start()
                                
                        except Exception as send_error:
                            logger.error("Failed to send AI-generated media download error message", error=str(send_error))
        
        return jsonify({"status": "ok"}), 200

    try:
        if is_valid_whatsapp_message(body):
            # Capture the app instance from current context
            app_instance = current_app._get_current_object()
            
            # Process message asynchronously in a new thread with app context
            def process_async():
                # Create new event loop for this thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    # Push app context to the thread using the captured app instance
                    with app_instance.app_context():
                        loop.run_until_complete(process_whatsapp_message(body))
                finally:
                    loop.close()
            
            thread = threading.Thread(target=process_async)
            thread.start()
            
            return jsonify({"status": "ok"}), 200
        else:
            # if the request is not a WhatsApp API event, return an error
            logger.warning("Invalid WhatsApp message received", body=body)
            return (
                jsonify({"status": "error", "message": "Not a WhatsApp API event"}),
                404,
            )
    except json.JSONDecodeError:
        logger.error("Failed to decode JSON")
        return jsonify({"status": "error", "message": "Invalid JSON provided"}), 400
    except Exception as e:
        logger.error("Error handling webhook message", error=str(e))
        return jsonify({"status": "error", "message": "Internal server error"}), 500


# Required webhook verification for WhatsApp
def verify():
    # Parse params from the webhook verification request
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    
    logger.info("Webhook verification request", mode=mode, token=token[:10] + "..." if token else None)
    
    # Check if a token and mode were sent
    if mode and token:
        # Check the mode and token sent are correct
        if mode == "subscribe" and token == current_app.config["VERIFY_TOKEN"]:
            # Respond with 200 OK and challenge token from the request
            logger.info("Webhook verification successful")
            return challenge, 200
        else:
            # Responds with '403 Forbidden' if verify tokens do not match
            logger.warning("Webhook verification failed - token mismatch")
            return jsonify({"status": "error", "message": "Verification failed"}), 403
    else:
        # Responds with '400 Bad Request' if verify tokens do not match
        logger.warning("Webhook verification failed - missing parameters")
        return jsonify({"status": "error", "message": "Missing parameters"}), 400


@webhook_blueprint.route("/webhook", methods=["GET"])
def webhook_get():
    return verify()

@webhook_blueprint.route("/webhook", methods=["POST"])
@signature_required
def webhook_post():
    return handle_message()


@webhook_blueprint.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint for monitoring."""
    try:
        # Check if all required services are configured
        required_configs = [
            "ACCESS_TOKEN", "PHONE_NUMBER_ID", "VERIFY_TOKEN",
            "SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY"
        ]
        
        missing_configs = []
        for config in required_configs:
            if not current_app.config.get(config):
                missing_configs.append(config)
        
        if missing_configs:
            return jsonify({
                "status": "unhealthy",
                "message": f"Missing configurations: {', '.join(missing_configs)}"
            }), 503
        
        return jsonify({
            "status": "healthy",
            "message": "All services are operational"
        }), 200
        
    except Exception as e:
        logger.error("Health check failed", error=str(e))
        return jsonify({
            "status": "unhealthy",
            "message": "Health check failed"
        }), 500


@webhook_blueprint.route("/status", methods=["GET"])
def status():
    """Status endpoint for monitoring conversation states."""
    try:
        # This would typically require authentication in production
        # For now, return basic status information
        
        return jsonify({
            "status": "operational",
            "services": {
                "whatsapp": "connected",
                "supabase": "connected",
                "document_ai": "configured",
                "vertex_ai": "configured"
            },
            "timestamp": current_app.config.get("START_TIME", "unknown")
        }), 200
        
    except Exception as e:
        logger.error("Status check failed", error=str(e))
        return jsonify({
            "status": "error",
            "message": "Status check failed"
        }), 500


