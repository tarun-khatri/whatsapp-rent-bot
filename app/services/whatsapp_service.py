import logging
import structlog
import asyncio
import requests
import json
from typing import Dict, Any, Optional, List
from datetime import datetime
from flask import current_app

from ..models.tenant import WhatsAppMessage, WhatsAppResponse
from ..utils.phone_utils import normalize_phone_number, extract_phone_from_whatsapp_id

logger = structlog.get_logger(__name__)


class WhatsAppService:
    def __init__(self):
        self.access_token: Optional[str] = None
        self.phone_number_id: Optional[str] = None
        self.version: str = "v18.0"
        self.base_url: str = "https://graph.facebook.com"
        self._initialized = False

    def _ensure_initialized(self):
        """Ensure the service is initialized with Flask app context."""
        if not self._initialized:
            try:
                self.access_token = current_app.config.get("ACCESS_TOKEN")
                self.phone_number_id = current_app.config.get("PHONE_NUMBER_ID")
                self.version = current_app.config.get("VERSION", "v18.0")
                
                if not self.access_token or not self.phone_number_id:
                    raise ValueError("WhatsApp access token and phone number ID must be configured")
                
                self._initialized = True
                logger.info("WhatsApp service initialized successfully")
            except Exception as e:
                logger.error("Failed to initialize WhatsApp service", error=str(e))
                raise

    async def send_text_message(self, recipient: str, message: str) -> Dict[str, Any]:
        """
        Send a text message via WhatsApp Business API.
        
        Args:
            recipient: Phone number in international format
            message: Message text to send
            
        Returns:
            Dict containing API response
        """
        self._ensure_initialized()
        try:
            # Normalize phone number
            normalized_phone = normalize_phone_number(recipient)
            
            # Prepare message data
            message_data = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": normalized_phone,
                "type": "text",
                "text": {
                    "preview_url": False,
                    "body": message
                }
            }
            
            # Send message
            response = await self._make_api_request("POST", f"/{self.version}/{self.phone_number_id}/messages", message_data)
            
            logger.info("Text message sent successfully", recipient=normalized_phone, message_id=response.get("messages", [{}])[0].get("id"))
            return response
            
        except Exception as e:
            logger.error("Error sending text message", recipient=recipient, error=str(e))
            raise

    async def send_template_message(self, recipient: str, template_name: str, language_code: str = "he", components: List[Dict] = None) -> Dict[str, Any]:
        """
        Send a template message via WhatsApp Business API.
        
        Args:
            recipient: Phone number in international format
            template_name: Name of the template
            language_code: Language code (he, en, etc.)
            components: Template components (parameters, etc.)
            
        Returns:
            Dict containing API response
        """
        try:
            # Normalize phone number
            normalized_phone = normalize_phone_number(recipient)
            
            # Prepare template data
            template_data = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": normalized_phone,
                "type": "template",
                "template": {
                    "name": template_name,
                    "language": {
                        "code": language_code
                    }
                }
            }
            
            # Add components if provided
            if components:
                template_data["template"]["components"] = components
            
            # Send template message
            response = await self._make_api_request("POST", f"/{self.version}/{self.phone_number_id}/messages", template_data)
            
            logger.info("Template message sent successfully", recipient=normalized_phone, template=template_name, message_id=response.get("messages", [{}])[0].get("id"))
            return response
            
        except Exception as e:
            logger.error("Error sending template message", recipient=recipient, template=template_name, error=str(e))
            raise

    async def send_media_message(self, recipient: str, media_type: str, media_url: str, caption: str = None) -> Dict[str, Any]:
        """
        Send a media message via WhatsApp Business API.
        
        Args:
            recipient: Phone number in international format
            media_type: Type of media (image, document, audio, video)
            media_url: URL of the media file
            caption: Optional caption for the media
            
        Returns:
            Dict containing API response
        """
        try:
            # Normalize phone number
            normalized_phone = normalize_phone_number(recipient)
            
            # Prepare media data
            media_data = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": normalized_phone,
                "type": media_type,
                media_type: {
                    "link": media_url
                }
            }
            
            # Add caption if provided
            if caption:
                media_data[media_type]["caption"] = caption
            
            # Send media message
            response = await self._make_api_request("POST", f"/{self.version}/{self.phone_number_id}/messages", media_data)
            
            logger.info("Media message sent successfully", recipient=normalized_phone, media_type=media_type, message_id=response.get("messages", [{}])[0].get("id"))
            return response
            
        except Exception as e:
            logger.error("Error sending media message", recipient=recipient, media_type=media_type, error=str(e))
            raise

    async def send_interactive_message(self, recipient: str, interactive_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send an interactive message (buttons, lists, etc.) via WhatsApp Business API.
        
        Args:
            recipient: Phone number in international format
            interactive_data: Interactive message data
            
        Returns:
            Dict containing API response
        """
        try:
            # Normalize phone number
            normalized_phone = normalize_phone_number(recipient)
            
            # Prepare interactive data
            message_data = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": normalized_phone,
                "type": "interactive",
                "interactive": interactive_data
            }
            
            # Send interactive message
            response = await self._make_api_request("POST", f"/{self.version}/{self.phone_number_id}/messages", interactive_data)
            
            logger.info("Interactive message sent successfully", recipient=normalized_phone, message_id=response.get("messages", [{}])[0].get("id"))
            return response
            
        except Exception as e:
            logger.error("Error sending interactive message", recipient=recipient, error=str(e))
            raise

    async def send_button_message(self, recipient: str, header_text: str, body_text: str, footer_text: str, buttons: List[Dict[str, str]]) -> Dict[str, Any]:
        """
        Send a button message via WhatsApp Business API.
        
        Args:
            recipient: Phone number in international format
            header_text: Header text
            body_text: Body text
            footer_text: Footer text
            buttons: List of button objects with id and title
            
        Returns:
            Dict containing API response
        """
        try:
            # Prepare button data
            button_components = []
            for button in buttons:
                button_components.append({
                    "type": "reply",
                    "reply": {
                        "id": button["id"],
                        "title": button["title"]
                    }
                })
            
            interactive_data = {
                "type": "button",
                "header": {
                    "type": "text",
                    "text": header_text
                },
                "body": {
                    "text": body_text
                },
                "footer": {
                    "text": footer_text
                },
                "action": {
                    "buttons": button_components
                }
            }
            
            return await self.send_interactive_message(recipient, interactive_data)
            
        except Exception as e:
            logger.error("Error sending button message", recipient=recipient, error=str(e))
            raise

    async def send_list_message(self, recipient: str, header_text: str, body_text: str, footer_text: str, button_text: str, sections: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Send a list message via WhatsApp Business API.
        
        Args:
            recipient: Phone number in international format
            header_text: Header text
            body_text: Body text
            footer_text: Footer text
            button_text: Button text
            sections: List of sections with rows
            
        Returns:
            Dict containing API response
        """
        try:
            interactive_data = {
                "type": "list",
                "header": {
                    "type": "text",
                    "text": header_text
                },
                "body": {
                    "text": body_text
                },
                "footer": {
                    "text": footer_text
                },
                "action": {
                    "button": button_text,
                    "sections": sections
                }
            }
            
            return await self.send_interactive_message(recipient, interactive_data)
            
        except Exception as e:
            logger.error("Error sending list message", recipient=recipient, error=str(e))
            raise

    async def download_media(self, media_id: str, max_retries: int = 3, retry_delay: float = 1.0) -> bytes:
        """
        Download media file from WhatsApp Business API with retry logic.
        
        Args:
            media_id: Media ID from the webhook
            max_retries: Maximum number of retry attempts
            retry_delay: Delay between retries in seconds
            
        Returns:
            Media file data as bytes
            
        Raises:
            Exception: If all retry attempts fail
        """
        self._ensure_initialized()
        last_exception = None
        
        logger.info("Starting media download", extra={
            "media_id": media_id,
            "max_retries": max_retries,
            "access_token_configured": bool(self.access_token),
            "access_token_length": len(self.access_token) if self.access_token else 0
        })
        
        for attempt in range(max_retries + 1):
            try:
                logger.info("Attempting media download", 
                          media_id=media_id, 
                          attempt=attempt + 1, 
                          max_retries=max_retries + 1)
                
                # Get media URL first
                media_url_response = await self._make_api_request("GET", f"/{self.version}/{media_id}")
                media_url = media_url_response.get("url")
                
                logger.info("Media URL retrieved", extra={
                    "media_id": media_id,
                    "has_url": bool(media_url),
                    "url_domain": media_url.split('/')[2] if media_url else None
                })
                
                if not media_url:
                    raise ValueError("Media URL not found in response")
                
                # Download media file with detailed logging
                headers = {
                    "Authorization": f"Bearer {self.access_token}",
                    "User-Agent": "WhatsApp-Business-Bot/1.0"
                }
                
                logger.info("Starting media file download", extra={
                    "media_url_domain": media_url.split('/')[2],
                    "headers_count": len(headers)
                })
                
                response = requests.get(media_url, headers=headers, timeout=30)
                
                logger.info("Media download response", extra={
                    "status_code": response.status_code,
                    "content_type": response.headers.get('content-type'),
                    "content_length": response.headers.get('content-length'),
                    "response_size": len(response.content)
                })
                
                response.raise_for_status()
                
                logger.info("Media downloaded successfully", 
                          media_id=media_id, 
                          size=len(response.content), 
                          attempt=attempt + 1,
                          content_type=response.headers.get('content-type'))
                return response.content
                
            except requests.exceptions.HTTPError as e:
                last_exception = e
                logger.error("HTTP error during media download", extra={
                    "media_id": media_id,
                    "attempt": attempt + 1,
                    "status_code": e.response.status_code if e.response else None,
                    "error_response": e.response.text if e.response else None,
                    "will_retry": attempt < max_retries
                })
                
            except requests.exceptions.RequestException as e:
                last_exception = e
                logger.error("Request error during media download", extra={
                    "media_id": media_id,
                    "attempt": attempt + 1,
                    "error_type": type(e).__name__,
                    "error": str(e),
                    "will_retry": attempt < max_retries
                })
                
            except Exception as e:
                last_exception = e
                logger.error("Unexpected error during media download", extra={
                    "media_id": media_id,
                    "attempt": attempt + 1,
                    "error_type": type(e).__name__,
                    "error": str(e),
                    "will_retry": attempt < max_retries
                })
                
            # If this is not the last attempt, wait before retrying
            if attempt < max_retries:
                sleep_time = retry_delay * (2 ** attempt)  # Exponential backoff
                logger.info("Waiting before retry", extra={
                    "media_id": media_id,
                    "sleep_seconds": sleep_time,
                    "next_attempt": attempt + 2
                })
                await asyncio.sleep(sleep_time)
        
        # If we get here, all attempts failed
        logger.error("All media download attempts exhausted", extra={
            "media_id": media_id,
            "total_attempts": max_retries + 1,
            "final_error_type": type(last_exception).__name__,
            "final_error": str(last_exception)
        })
        
        raise last_exception

    async def mark_message_as_read(self, message_id: str) -> Dict[str, Any]:
        """
        Mark a message as read.
        
        Args:
            message_id: Message ID to mark as read
            
        Returns:
            Dict containing API response
        """
        try:
            read_data = {
                "messaging_product": "whatsapp",
                "status": "read",
                "message_id": message_id
            }
            
            response = await self._make_api_request("POST", f"/{self.version}/{self.phone_number_id}/messages", read_data)
            
            logger.info("Message marked as read", message_id=message_id)
            return response
            
        except Exception as e:
            logger.error("Error marking message as read", message_id=message_id, error=str(e))
            raise

    async def _make_api_request(self, method: str, endpoint: str, data: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Make an API request to WhatsApp Business API.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint
            data: Request data for POST requests
            
        Returns:
            Dict containing API response
        """
        try:
            url = f"{self.base_url}{endpoint}"
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }
            
            if method.upper() == "GET":
                response = requests.get(url, headers=headers, timeout=30)
            elif method.upper() == "POST":
                response = requests.post(url, headers=headers, json=data, timeout=30)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.HTTPError as e:
            # Handle specific HTTP errors
            if e.response.status_code == 400:
                error_data = e.response.json() if e.response.content else {}
                error_message = error_data.get('error', {}).get('message', 'Bad Request')
                error_code = error_data.get('error', {}).get('code', 400)
                
                logger.error("WhatsApp API 400 error", 
                           status_code=400, 
                           error_message=error_message, 
                           error_code=error_code,
                           endpoint=endpoint,
                           data=data)
                
                # Raise a more specific exception
                raise WhatsAppAPIError(f"WhatsApp API Error: {error_message} (Code: {error_code})")
            else:
                logger.error("WhatsApp API HTTP error", 
                           status_code=e.response.status_code, 
                           error=str(e),
                           endpoint=endpoint)
                raise WhatsAppAPIError(f"WhatsApp API HTTP Error: {e.response.status_code}")
                
        except requests.exceptions.RequestException as e:
            logger.error("WhatsApp API request failed", method=method, endpoint=endpoint, error=str(e))
            raise WhatsAppAPIError(f"WhatsApp API Request Failed: {str(e)}")
        except Exception as e:
            logger.error("Unexpected error in WhatsApp API request", method=method, endpoint=endpoint, error=str(e))
            raise WhatsAppAPIError(f"Unexpected WhatsApp API Error: {str(e)}")

    def parse_webhook_message(self, webhook_data: Dict[str, Any]) -> Optional[WhatsAppMessage]:
        """
        Parse incoming webhook message data.
        
        Args:
            webhook_data: Raw webhook data from WhatsApp
            
        Returns:
            Parsed WhatsAppMessage object or None if invalid
        """
        self._ensure_initialized()
        try:
            # Extract message data from webhook
            entry = webhook_data.get("entry", [])
            if not entry:
                return None
            
            changes = entry[0].get("changes", [])
            if not changes:
                return None
            
            value = changes[0].get("value", {})
            messages = value.get("messages", [])
            contacts = value.get("contacts", [])
            
            if not messages or not contacts:
                return None
            
            message = messages[0]
            contact = contacts[0]
            
            # Extract basic information
            wa_id = contact.get("wa_id")
            name = contact.get("profile", {}).get("name", "")
            
            # Extract message content based on type
            message_type = message.get("type", "text")
            message_body = ""
            media_url = None
            media_type = None
            
            if message_type == "text":
                message_body = message.get("text", {}).get("body", "")
            elif message_type in ["image", "document", "audio", "video"]:
                media_id = message.get(message_type, {}).get("id")
                if media_id:
                    media_url = f"media_id:{media_id}"
                    media_type = message_type
                message_body = message.get(message_type, {}).get("caption", "")
            
            return WhatsAppMessage(
                wa_id=wa_id,
                name=name,
                message_body=message_body,
                message_type=message_type,
                media_url=media_url,
                media_type=media_type
            )
            
        except Exception as e:
            logger.error("Error parsing webhook message", error=str(e))
            return None

    def is_valid_webhook_message(self, webhook_data: Dict[str, Any]) -> bool:
        """
        Check if webhook data contains a valid WhatsApp message.
        
        Args:
            webhook_data: Raw webhook data from WhatsApp
            
        Returns:
            True if valid message, False otherwise
        """
        try:
            # Check basic structure
            if not webhook_data.get("object") == "whatsapp_business_account":
                return False
            
            entry = webhook_data.get("entry", [])
            if not entry:
                return False
            
            changes = entry[0].get("changes", [])
            if not changes:
                return False
            
            value = changes[0].get("value", {})
            messages = value.get("messages", [])
            contacts = value.get("contacts", [])
            
            return len(messages) > 0 and len(contacts) > 0
            
        except Exception as e:
            logger.error("Error validating webhook message", error=str(e))
            return False

    async def send_typing_indicator(self, recipient: str) -> Dict[str, Any]:
        """
        Send typing indicator to show bot is typing.
        
        Args:
            recipient: Phone number in international format
            
        Returns:
            Dict containing API response
        """
        try:
            # Note: WhatsApp Business API doesn't support typing indicators
            # This is a placeholder for future implementation
            logger.info("Typing indicator requested", recipient=recipient)
            return {"status": "not_supported"}
            
        except Exception as e:
            logger.error("Error sending typing indicator", recipient=recipient, error=str(e))
            raise


class WhatsAppAPIError(Exception):
    """Custom exception for WhatsApp API errors."""
    pass


# Global instance
whatsapp_service = WhatsAppService()
