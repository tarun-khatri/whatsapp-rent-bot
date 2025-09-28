import logging
import structlog
import asyncio
from flask import current_app, jsonify
import json
import requests
import re

from ..services.whatsapp_service import whatsapp_service, WhatsAppAPIError
from ..services.conversation_flow_service import conversation_flow_service

logger = structlog.get_logger(__name__)


def log_http_response(response):
    logger.info("HTTP response received", 
                status_code=response.status_code,
                content_type=response.headers.get('content-type'),
                body=response.text)


def get_text_message_input(recipient, text):
    return json.dumps(
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }
    )


def process_text_for_whatsapp(text):
    """Process text for WhatsApp formatting."""
    # Remove brackets
    pattern = r"\【.*?\】"
    text = re.sub(pattern, "", text).strip()

    # Pattern to find double asterisks including the word(s) in between
    pattern = r"\*\*(.*?)\*\*"
    replacement = r"*\1*"
    whatsapp_style_text = re.sub(pattern, replacement, text)

    return whatsapp_style_text


async def process_whatsapp_message(body):
    """
    Process incoming WhatsApp message using the conversation flow service.
    """
    try:
        # Parse the webhook message
        parsed_message = whatsapp_service.parse_webhook_message(body)
        if not parsed_message:
            logger.warning("Failed to parse webhook message", body=body)
            return

        wa_id = parsed_message.wa_id
        name = parsed_message.name
        message_body = parsed_message.message_body
        message_type = parsed_message.message_type
        media_url = parsed_message.media_url

        logger.info("Processing WhatsApp message", 
                   wa_id=wa_id, name=name, message_type=message_type)

        # Download media if present
        media_data = None
        if media_url and media_url.startswith("media_id:"):
            media_id = media_url.replace("media_id:", "")
            try:
                media_data = await whatsapp_service.download_media(media_id)
                logger.info("Media downloaded successfully", media_id=media_id, size=len(media_data) if media_data else 0)
            except Exception as e:
                logger.error("Failed to download media after retries", media_id=media_id, error=str(e))
                # Generate AI-powered error message and ask user to resend
                try:
                    from ..services.ai_conversation_service import ai_conversation_service
                    
                    # Generate AI response for media download failure
                    ai_error_response = await ai_conversation_service.generate_media_error_response(
                        phone_number=wa_id,
                        user_message=message_body,
                        error_context={
                            "error_type": "media_download_failed",
                            "media_id": media_id,
                            "original_message": message_body,
                            "retry_attempts": 3
                        }
                    )
                    
                    await whatsapp_service.send_text_message(wa_id, ai_error_response)
                    return
                except Exception as send_error:
                    logger.error("Failed to send AI-generated media download error message", error=str(send_error))
                    # Fallback to simple message if AI fails
                    try:
                        fallback_message = "מצטער, לא הצלחתי להוריד את הקובץ. אנא נסה לשלוח שוב."
                        await whatsapp_service.send_text_message(wa_id, fallback_message)
                    except Exception as final_error:
                        logger.error("Failed to send fallback error message", error=str(final_error))

        # Handle the message through conversation flow
        response_message = await conversation_flow_service.handle_incoming_message(
            wa_id=wa_id,
            message_body=message_body,
            message_type=message_type,
            media_data=media_data
        )

        # Send response back to user (only if there's a response message)
        if response_message and response_message.strip():
            try:
                await whatsapp_service.send_text_message(wa_id, response_message)
                logger.info("WhatsApp message processed successfully", wa_id=wa_id)
            except WhatsAppAPIError as api_error:
                logger.error("WhatsApp API error - cannot send message", wa_id=wa_id, error=str(api_error))
                # Don't try to send error message if API is failing
                return
            except Exception as send_error:
                logger.error("Error sending WhatsApp message", wa_id=wa_id, error=str(send_error))
                # Try to send AI-generated error message
                try:
                    from ..services.ai_conversation_service import ai_conversation_service
                    
                    ai_error_response = await ai_conversation_service.generate_media_error_response(
                        phone_number=wa_id,
                        user_message=message_body,
                        error_context={
                            "error_type": "message_send_failed",
                            "original_message": message_body,
                            "retry_attempts": 0
                        }
                    )
                    
                    await whatsapp_service.send_text_message(wa_id, ai_error_response)
                except Exception as final_error:
                    logger.error("Failed to send AI-generated error message", error=final_error)

    except Exception as e:
        logger.error("Error processing WhatsApp message", error=str(e))
        # Send AI-generated error message to user
        try:
            wa_id = body["entry"][0]["changes"][0]["value"]["contacts"][0]["wa_id"]
            
            from ..services.ai_conversation_service import ai_conversation_service
            
            ai_error_response = await ai_conversation_service.generate_media_error_response(
                phone_number=wa_id,
                user_message="message_processing_failed",
                error_context={
                    "error_type": "message_processing_failed",
                    "original_message": "unknown",
                    "retry_attempts": 0
                }
            )
            
            await whatsapp_service.send_text_message(wa_id, ai_error_response)
        except WhatsAppAPIError as api_error:
            logger.error("WhatsApp API error - cannot send error message", error=str(api_error))
        except Exception as send_error:
            logger.error("Failed to send AI-generated error message", error=send_error)


def is_valid_whatsapp_message(body):
    """
    Check if the incoming webhook event has a valid WhatsApp message structure
    and is intended for this bot's phone number.
    """
    if not whatsapp_service.is_valid_webhook_message(body):
        return False
    
    # Validate that the message is for this bot's phone number
    try:
        configured_phone_id = current_app.config.get("PHONE_NUMBER_ID")
        webhook_phone_id = body["entry"][0]["changes"][0]["value"]["metadata"]["phone_number_id"]
        
        if configured_phone_id != webhook_phone_id:
            logger.info("Ignoring message for different phone number", 
                       configured_phone_id=configured_phone_id,
                       webhook_phone_id=webhook_phone_id)
            return False
            
        return True
        
    except (KeyError, IndexError) as e:
        logger.error("Failed to extract phone_number_id from webhook", error=str(e))
        return False


# Legacy functions for backward compatibility
def generate_response(response):
    """Legacy function - now handled by conversation flow service."""
    return response.upper()


def send_message(data):
    """Legacy function - now handled by WhatsApp service."""
    headers = {
        "Content-type": "application/json",
        "Authorization": f"Bearer {current_app.config['ACCESS_TOKEN']}",
    }

    url = f"https://graph.facebook.com/{current_app.config['VERSION']}/{current_app.config['PHONE_NUMBER_ID']}/messages"

    try:
        response = requests.post(
            url, data=data, headers=headers, timeout=10
        )
        response.raise_for_status()
    except requests.Timeout:
        logger.error("Timeout occurred while sending message")
        return jsonify({"status": "error", "message": "Request timed out"}), 408
    except requests.RequestException as e:
        logger.error("Request failed", error=str(e))
        return jsonify({"status": "error", "message": "Failed to send message"}), 500
    else:
        log_http_response(response)
        return response
