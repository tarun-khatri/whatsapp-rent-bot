import logging
import structlog
import asyncio
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from flask import current_app

from ..models.tenant import (
    Tenant, ConversationState, DocumentType, WhatsAppStatus,
    ConversationStateModel, ConversationStateCreate, ConversationStateUpdate
)
from ..services.supabase_service import supabase_service
from ..services.whatsapp_service import whatsapp_service
from ..services.vertex_ai_service import vertex_ai_service
from ..services.document_ai_service import document_ai_service
from ..services.guarantor_service import guarantor_service
from ..services.guarantor_conversation_service import guarantor_conversation_service
from ..services.ai_conversation_service import ai_conversation_service
from ..utils.phone_utils import normalize_phone_number, extract_phone_from_whatsapp_id

logger = structlog.get_logger(__name__)


class ConversationFlowService:
    def __init__(self):
        self.timeout_hours = 24  # Default value
        self._initialized = False

    def _ensure_initialized(self):
        """Ensure the service is initialized with Flask app context."""
        if not self._initialized:
            try:
                self.timeout_hours = current_app.config.get("CONVERSATION_TIMEOUT_HOURS", 24)
                self._initialized = True
            except Exception as e:
                logger.error("Failed to initialize conversation flow service", error=str(e))
                # Use default value if can't access config
                self.timeout_hours = 24
                self._initialized = True

    async def handle_incoming_message(self, wa_id: str, message_body: str, message_type: str, media_data: bytes = None) -> str:
        """
        Handle incoming WhatsApp message and return appropriate response.
        
        Args:
            wa_id: WhatsApp ID of the sender
            message_body: Text content of the message
            message_type: Type of message (text, image, document, etc.)
            media_data: Raw media data if applicable
            
        Returns:
            Response message to send back
        """
        
        # First check if this is a guarantor message
        phone_number = extract_phone_from_whatsapp_id(wa_id)
        guarantor = await guarantor_service.get_guarantor_by_phone(phone_number)
        
        if guarantor:
            # Handle guarantor message with AI
            return await self._handle_guarantor_with_ai(phone_number, message_body, message_type, media_data)
        
        # Continue with regular tenant flow
        self._ensure_initialized()
        try:
            # Extract and normalize phone number
            phone = extract_phone_from_whatsapp_id(wa_id)
            if not phone:
                return "מצטער, לא הצלחתי לזהות את מספר הטלפון שלך. אנא פנה לצוות התמיכה."

            # Get or create conversation state
            conversation_state = await self._get_or_create_conversation_state(phone)
            
            # Check for timeout
            if await self._is_conversation_timed_out(conversation_state):
                await self._reset_conversation_state(phone)
                conversation_state = await self._get_or_create_conversation_state(phone)

            # Handle based on current state
            if conversation_state.current_state == ConversationState.GREETING:
                return await self._handle_greeting_state_with_ai(phone, message_body, conversation_state)
            elif conversation_state.current_state == ConversationState.CONFIRMATION:
                return await self._handle_confirmation_state_with_ai(phone, message_body, conversation_state)
            elif conversation_state.current_state == ConversationState.PERSONAL_INFO:
                return await self._handle_personal_info_state_with_ai(phone, message_body, conversation_state)
            elif conversation_state.current_state == ConversationState.DOCUMENTS:
                return await self._handle_documents_state_with_ai(phone, message_body, message_type, media_data, conversation_state)
            elif conversation_state.current_state == ConversationState.GUARANTOR_1:
                return await self._handle_guarantor_state_with_ai(phone, message_body, conversation_state, 1)
            elif conversation_state.current_state == ConversationState.GUARANTOR_2:
                return await self._handle_guarantor_state_with_ai(phone, message_body, conversation_state, 2)
            elif conversation_state.current_state == ConversationState.COMPLETED:
                return await self._handle_completed_state_with_ai(phone, message_body, conversation_state)
            else:
                return "מצטער, אירעה שגיאה. אנא פנה לצוות התמיכה."

        except Exception as e:
            logger.error("Error handling incoming message", wa_id=wa_id, error=str(e))
            return "מצטער, אירעה שגיאה. אנא נסה שוב או פנה לצוות התמיכה."

    async def _get_or_create_conversation_state(self, phone: str) -> ConversationStateModel:
        """Get existing conversation state or create new one."""
        try:
            # Try to get existing state
            state = await supabase_service.get_conversation_state(phone)
            if state:
                return state

            # Create new state
            new_state = ConversationStateCreate(
                phone_number=phone,
                current_state=ConversationState.GREETING,
                context_data={},
                last_message_time=datetime.utcnow()
            )
            
            return await supabase_service.create_conversation_state(new_state)
            
        except Exception as e:
            logger.error("Error getting or creating conversation state", phone=phone, error=str(e))
            raise

    async def _is_conversation_timed_out(self, conversation_state: ConversationStateModel) -> bool:
        """Check if conversation has timed out."""
        self._ensure_initialized()
        if not conversation_state.last_message_time:
            return False
        
        # Use timezone-aware datetime for comparison
        from datetime import timezone
        timeout_threshold = datetime.now(timezone.utc) - timedelta(hours=self.timeout_hours)
        return conversation_state.last_message_time < timeout_threshold

    async def _reset_conversation_state(self, phone: str):
        """Reset conversation state to start over."""
        try:
            await supabase_service.delete_conversation_state(phone)
            logger.info("Conversation state reset", phone=phone)
        except Exception as e:
            logger.error("Error resetting conversation state", phone=phone, error=str(e))

    async def _update_conversation_state(self, phone: str, new_state: ConversationState, context_data: Dict[str, Any] = None):
        """Update conversation state."""
        try:
            updates = ConversationStateUpdate(
                current_state=new_state,
                context_data=context_data or {},
                last_message_time=datetime.utcnow()
            )
            
            await supabase_service.update_conversation_state(phone, updates)
            logger.info("Conversation state updated", phone=phone, new_state=new_state)
            
        except Exception as e:
            logger.error("Error updating conversation state", phone=phone, error=str(e))
            raise

    async def _handle_greeting_state(self, phone: str, message_body: str, conversation_state: ConversationStateModel) -> str:
        """Handle greeting state - find tenant and send personalized greeting."""
        try:
            # Check if this is a lookup_required case (user already got manual lookup message)
            if conversation_state.context_data.get("lookup_required"):
                # User is responding to manual lookup request
                logger.info("Handling manual lookup response", phone=phone, message=message_body)
                
                # Check if user provided meaningful information
                if len(message_body.strip()) > 10:  # Has substantial content
                    # User provided details - move to a waiting state or manual review
                    await self._update_conversation_state(phone, ConversationState.GREETING, {
                        "lookup_required": True,
                        "user_details": message_body.strip(),
                        "status": "manual_review_needed"
                    })
                    
                    return """תודה על המידע שסיפקת. 

אני מעביר את הפרטים לצוות שלנו לבדיקה ידנית

נחזור אליך בהקדם האפשרי עם הפרטים הנכונים ונמשיך בתהליך ההרשמה

תודה על הסבלנות! 😊"""
                
                else:
                    # User didn't provide enough details
                    return """אנא שלח פרטים מלאים יותר כדי שאוכל לעזור לך:

• השם המלא שלך
• מספר הטלפון
• שם הנכס/הכתובת

זה יעזור לי למצוא את הפרטים שלך במערכת 📋"""
            
            # Regular greeting flow - try to find tenant
            tenant = await supabase_service.find_tenant_by_phone(phone)
            
            if tenant:
                # Update tenant status
                await supabase_service.update_tenant_whatsapp_status(tenant.id, WhatsAppStatus.IN_PROGRESS)
                
                # Update conversation state with tenant info
                context_data = {
                    "tenant_id": tenant.id,
                    "tenant_name": tenant.full_name,
                    "property_name": tenant.property_name,
                    "apartment_number": tenant.apartment_number,
                    "number_of_rooms": tenant.number_of_rooms,
                    "monthly_rent_amount": tenant.monthly_rent_amount,
                    "move_in_date": tenant.move_in_date.isoformat() if tenant.move_in_date else None
                }
                
                await self._update_conversation_state(phone, ConversationState.CONFIRMATION, context_data)
                
                # Send personalized greeting with property details
                greeting_message = f"""שלום {tenant.full_name}, זה יוני ממגורית. אנחנו שמחים שהחלטת להצטרף למשפחת מגורית ב{tenant.property_name}.

אנא אשר את הפרטים הבאים:
• מספר דירה: {tenant.apartment_number}
• מספר חדרים: {tenant.number_of_rooms}
• תאריך כניסה: {tenant.move_in_date.strftime('%d/%m/%Y') if tenant.move_in_date else 'לא מוגדר'}
• שכר דירה חודשי: ₪{tenant.monthly_rent_amount:,.0f}

הפרטים נכונים? השיב 'כן' או 'אישור' אם הכל תקין, או ספר לי מה צריך לשנות."""
                
                return greeting_message
            else:
                # Tenant not found - ask for manual lookup (ONLY ONCE)
                await self._update_conversation_state(phone, ConversationState.GREETING, {
                    "lookup_required": True,
                    "lookup_message_sent": True
                })
                
                return """שלום! זה יוני ממגורית 😊

לא מצאתי את הפרטים שלך במערכת האוטומטית

אנא שלח לי את הפרטים הבאים כדי שאוכל למצוא אותך במערכת:
• השם המלא שלך
• מספר הטלפון
• שם הנכס או הכתובת"""

        except Exception as e:
            logger.error("Error handling greeting state", phone=phone, error=str(e))
            return "מצטער, אירעה שגיאה. אנא פנה לצוות התמיכה."

    async def _handle_confirmation_state(self, phone: str, message_body: str, conversation_state: ConversationStateModel) -> str:
        """Handle confirmation state - validate tenant details."""
        try:
            logger.info("Handling confirmation state", message=message_body)
            
            # Use Vertex AI to validate response with full context
            validation_result = await vertex_ai_service.validate_human_response(
                "האם הפרטים נכונים?",
                message_body,
                {
                    **conversation_state.context_data,
                    "conversation_phase": "confirmation",
                    "bot_name": "Yoni",
                    "company": "Megurit",
                    "tenant_name": conversation_state.context_data.get("tenant_name", "Unknown"),
                    "property_name": conversation_state.context_data.get("property_name", "Unknown"),
                    "apartment_number": conversation_state.context_data.get("apartment_number", "Unknown"),
                    "monthly_rent": conversation_state.context_data.get("monthly_rent", "Unknown")
                }
            )
            
            logger.info("Vertex AI validation result", result=validation_result)
            
            if not validation_result.get("is_valid", False):
                return validation_result.get("feedback", "אנא השיב 'כן' או 'לא'.")
            
            parsed_data = validation_result.get("parsed_data", {})
            
            if parsed_data.get("confirmed", False):
                # Details confirmed - move to personal info
                await self._update_conversation_state(phone, ConversationState.PERSONAL_INFO, {
                    **conversation_state.context_data,
                    "current_field": "occupation"
                })
                
                return "מעולה! הפרטים נכונים. עכשיו נמשיך לשלב הבא.\n\nמה העיסוק שלך?"
                
            elif parsed_data.get("confirmed", False) is False:
                # Details need correction
                return "אין בעיה. אנא ספר לי מה צריך לשנות בפרטים ששלחתי."
                
            else:
                # Unclear response
                return "אנא השיב 'כן' אם הפרטים נכונים, או 'לא' אם צריך לשנות משהו."

        except Exception as e:
            logger.error("Error handling confirmation state", phone=phone, error=str(e))
            return "מצטער, אירעה שגיאה. אנא נסה שוב."

    async def _handle_personal_info_state(self, phone: str, message_body: str, conversation_state: ConversationStateModel) -> str:
        """Handle personal info collection state."""
        try:
            current_field = conversation_state.context_data.get("current_field", "occupation")
            
            # Use Vertex AI to validate and parse response
            question = f"מה ה{current_field} שלך?"
            if current_field == "number_of_children":
                question = "כמה ילדים יש לך?"
            
            validation_result = await vertex_ai_service.validate_human_response(
                question,
                message_body,
                conversation_state.context_data
            )
            
            if not validation_result.get("is_valid", False):
                return validation_result.get("feedback", "אנא שלח תגובה תקינה.")
            
            parsed_data = validation_result.get("parsed_data", {})
            
            # Update tenant information based on current field
            tenant_id = conversation_state.context_data.get("tenant_id")
            if tenant_id:
                if current_field == "occupation":
                    from app.models.tenant import TenantUpdate
                    await supabase_service.update_tenant(tenant_id, TenantUpdate(occupation=parsed_data.get("occupation", message_body)))
                    await self._update_conversation_state(phone, ConversationState.PERSONAL_INFO, {
                        **conversation_state.context_data,
                        "current_field": "family_status"
                    })
                    return "תודה! עכשיו אנא ספר לי מה המצב המשפחתי שלך (רווק/נשוי/גרוש/אלמן)."
                    
                elif current_field == "family_status":
                    from app.models.tenant import TenantUpdate
                    family_status = parsed_data.get("family_status", message_body)
                    await supabase_service.update_tenant(tenant_id, TenantUpdate(family_status=family_status))
                    await self._update_conversation_state(phone, ConversationState.PERSONAL_INFO, {
                        **conversation_state.context_data,
                        "current_field": "number_of_children"
                    })
                    return "תודה! כמה ילדים יש לך?"
                    
                elif current_field == "number_of_children":
                    from app.models.tenant import TenantUpdate
                    number_of_children = parsed_data.get("number_of_children", 0)
                    logger.info("Updating number of children", 
                               extra={"tenant_id": tenant_id, "number_of_children": number_of_children, "parsed_data": parsed_data})
                    await supabase_service.update_tenant(tenant_id, TenantUpdate(number_of_children=number_of_children))
                    
                    # Get tenant occupation to determine document sequence
                    tenant = await supabase_service.get_tenant_by_id(tenant_id)
                    tenant_occupation = tenant.occupation if tenant else None
                    
                    # Move to documents state with ID_CARD as first document
                    await self._update_conversation_state(phone, ConversationState.DOCUMENTS, {
                        **conversation_state.context_data,
                        "current_document": DocumentType.ID_CARD.value,
                        "tenant_occupation": tenant_occupation  # Store occupation for later use
                    })
                    
                    return "מעולה! עכשיו נתחיל לאסוף את המסמכים הנדרשים.\n\nאנא שלח את תמונת תעודת הזהות שלך (Teudat Zehut)."
            
            return "מצטער, אירעה שגיאה. אנא נסה שוב."

        except Exception as e:
            logger.error("Error handling personal info state", phone=phone, error=str(e))
            return "מצטער, אירעה שגיאה. אנא נסה שוב."

    async def _handle_documents_state(self, phone: str, message_body: str, message_type: str, media_data: bytes, conversation_state: ConversationStateModel) -> str:
        """Handle document collection state."""
        try:
            current_document = conversation_state.context_data.get("current_document")
            tenant_id = conversation_state.context_data.get("tenant_id")
            
            if not current_document or not tenant_id:
                return "מצטער, אירעה שגיאה. אנא פנה לצוות התמיכה."
            
            # Check if current document is payslips or pnl and verify occupation-based document type
            if current_document in ["payslips", "pnl"]:
                # Get tenant occupation from database
                tenant = await supabase_service.get_tenant_by_id(tenant_id)
                if tenant and tenant.occupation:
                    # Use Vertex AI to analyze occupation and determine correct document type
                    correct_document_type = await self._analyze_occupation_for_document_type(tenant.occupation)
                    
                    # If the current document doesn't match the occupation, update it
                    if (correct_document_type == DocumentType.PNL and current_document != "pnl") or \
                       (correct_document_type == DocumentType.PAYSLIPS and current_document != "payslips"):
                        
                        logger.info("Correcting document type based on occupation", 
                                   extra={
                                       "tenant_occupation": tenant.occupation,
                                       "current_document": current_document,
                                       "correct_document_type": correct_document_type.value
                                   })
                        
                        # Update conversation state with correct document type
                        await self._update_conversation_state(phone, ConversationState.DOCUMENTS, {
                            **conversation_state.context_data,
                            "current_document": correct_document_type.value
                        })
                        
                        # Return the correct message for the corrected document type
                        return self._get_document_request_message(correct_document_type.value)
            
            # Skip automatic document detection for now to avoid errors
            # TODO: Implement proper document type detection
            
            # Check if this is a media message (document upload)
            if message_type in ["image", "document"] and media_data:
                return await self._process_document_upload(phone, media_data, DocumentType(current_document), tenant_id, conversation_state)
            
            # Handle text responses
            validation_result = await vertex_ai_service.validate_human_response(
                f"אנא שלח את {current_document}",
                message_body,
                conversation_state.context_data
            )
            
            if not validation_result.get("is_valid", False):
                return validation_result.get("feedback", "אנא שלח את המסמך הנדרש.")
            
            parsed_data = validation_result.get("parsed_data", {})
            
            if parsed_data.get("document_uploaded", False):
                return "תודה! המסמך התקבל. אנא שלח את המסמך הבא."
            else:
                return self._get_document_request_message(current_document)

        except Exception as e:
            logger.error("Error handling documents state", phone=phone, error=str(e))
            return "מצטער, אירעה שגיאה בעיבוד המסמך. אנא נסה שוב."

    async def _detect_document_type(self, media_data: bytes) -> DocumentType:
        """Detect document type using OCR and AI."""
        try:
            # Use Document AI to extract text by processing as ID card first
            from app.services.document_ai_service import document_ai_service
            from app.models.tenant import DocumentType
            
            # Process the document to get text extraction
            result = await document_ai_service.process_document(
                file_data=media_data,
                document_type=DocumentType.ID_CARD,  # Start with ID card as default
                tenant_info={}  # Empty tenant info for detection
            )
            
            if not result or not result.get("extracted_data", {}).get("text"):
                return DocumentType.ID_CARD  # Default fallback
            
            text = result["extracted_data"]["text"]
            
            # Use Vertex AI for intelligent document type detection
            from app.services.vertex_ai_service import vertex_ai_service
            
            detection_prompt = f"""
Analyze this document text and determine what type of document it is:

Document text:
{text}

Classify this document as one of these types:
1. ID_CARD - Israeli identity card (תעודת זהות)
2. SEPHACH - Israeli ID card appendix (ספח)
3. PAYSLIPS - Salary payslip (תלוש משכורת)
4. PNL - Profit and Loss statement (דוח רווח והפסד)
5. BANK_STATEMENTS - Bank statement (דוח בנק)

Look for these indicators:
- ID_CARD: "תעודת זהות", "מספר זהות", personal information
- SEPHACH: "ספח", family information, children, spouse
- PAYSLIPS: "תלוש משכורת", "שכר", salary information, company name
- PNL: "רווח והפסד", "הכנסות", "הוצאות", business financial data
- BANK_STATEMENTS: "דוח בנק", "חשבון", bank transactions

Return ONLY the document type (e.g., "PAYSLIPS" or "PNL").
"""
            
            try:
                response = await vertex_ai_service.generate_response(detection_prompt)
                response_clean = response.strip().upper()
                
                # Map response to DocumentType
                if "PAYSLIPS" in response_clean:
                    return DocumentType.PAYSLIPS
                elif "PNL" in response_clean:
                    return DocumentType.PNL
                elif "SEPHACH" in response_clean:
                    return DocumentType.SEPHACH
                elif "BANK_STATEMENTS" in response_clean:
                    return DocumentType.BANK_STATEMENTS
                elif "ID_CARD" in response_clean:
                    return DocumentType.ID_CARD
                else:
                    # Fallback to keyword detection
                    return self._fallback_document_detection(text)
                    
            except Exception as e:
                logger.error("Error in AI document detection", error=str(e))
                return self._fallback_document_detection(text)
                
        except Exception as e:
            logger.error("Error detecting document type", error=str(e))
            return DocumentType.ID_CARD  # Default fallback
    
    def _fallback_document_detection(self, text: str) -> DocumentType:
        """Fallback keyword-based document detection."""
        text_lower = text.lower()
        
        # Simple keyword-based detection
        if any(keyword in text_lower for keyword in ["תלוש משכורת", "payslip", "שכר", "משכורת"]):
            return DocumentType.PAYSLIPS
        elif any(keyword in text_lower for keyword in ["רווח והפסד", "pnl", "הכנסות", "הוצאות", "רווח נקי"]):
            return DocumentType.PNL
        elif any(keyword in text_lower for keyword in ["ספח", "sephach", "משפחה", "ילדים"]):
            return DocumentType.SEPHACH
        elif any(keyword in text_lower for keyword in ["תעודת זהות", "identity card", "מספר זהות"]):
            return DocumentType.ID_CARD
        elif any(keyword in text_lower for keyword in ["דוח בנק", "bank statement", "חשבון בנק"]):
            return DocumentType.BANK_STATEMENTS
        else:
            # Default to ID card if unclear
            return DocumentType.ID_CARD

    async def _process_document_upload(self, phone: str, media_data: bytes, document_type: DocumentType, tenant_id: str, conversation_state: ConversationStateModel) -> str:
        """Process uploaded document."""
        try:
            # Don't auto-detect document type - use the expected document type from conversation state
            # This prevents the bot from changing document types when user sends wrong document
            logger.info("Processing document with expected type", expected_type=document_type.value)
            
            # Get tenant information
            tenant = await supabase_service.get_tenant_by_id(tenant_id)
            if not tenant:
                return "מצטער, לא מצאתי את הפרטים שלך. אנא פנה לצוות התמיכה."
            
            # Process document with Document AI
            # Pass tenant info with ID number for validation
            tenant_info = tenant.dict()
            tenant_info["id"] = tenant.id_number.strip() if tenant.id_number else None  # Use ID number instead of UUID
            processing_result = await document_ai_service.process_document(
                media_data, document_type, tenant_info
            )
            
            # Update document status
            await supabase_service.update_tenant_documents_status(
                tenant_id, document_type, 
                processing_result["processing_status"],
                processing_result.get("file_url")
            )
            
            # Check if document is valid
            if processing_result["validation_result"].get("is_valid", False):
                # If this is an ID card, extract and store the ID number
                if document_type == DocumentType.ID_CARD:
                    extracted_data = processing_result.get("extracted_data", {})
                    id_number = extracted_data.get("id_number")
                    if id_number:
                        try:
                            # Update tenant record with extracted ID number
                            from app.models.tenant import TenantUpdate
                            await supabase_service.update_tenant(tenant_id, TenantUpdate(id_number=id_number))
                            logger.info("ID number extracted and stored", tenant_id=tenant_id, id_number=id_number)
                        except Exception as e:
                            logger.error("Failed to store ID number", tenant_id=tenant_id, id_number=id_number, error=str(e))
                
                # Move to next document based on occupation
                tenant = await supabase_service.get_tenant_by_id(tenant_id)
                tenant_occupation = tenant.occupation if tenant else None
                next_document = await self._get_next_document(document_type, tenant_occupation, conversation_state.context_data)
                
                # Create contextual success message
                success_message = self._create_document_success_message(document_type, next_document, tenant)
                
                if next_document:
                    await self._update_conversation_state(phone, ConversationState.DOCUMENTS, {
                        **conversation_state.context_data,
                        "current_document": next_document.value
                    })
                    return success_message
                else:
                    # All documents collected - move to guarantor
                    await self._update_conversation_state(phone, ConversationState.GUARANTOR_1, {
                        **conversation_state.context_data,
                        "current_guarantor": 1
                    })
                    return success_message
            else:
                # Document rejected - provide specific feedback
                errors = processing_result["validation_result"].get("errors", [])
                warnings = processing_result["validation_result"].get("warnings", [])
                
                # Create contextual error message
                error_message = self._create_document_error_message(document_type, errors, warnings)
                return error_message

        except Exception as e:
            logger.error("Error processing document upload", phone=phone, document_type=document_type, error=str(e))
            return "מצטער, אירעה שגיאה בעיבוד המסמך. אנא נסה שוב."

    def _create_document_success_message(self, document_type, next_document, tenant) -> str:
        """Create contextual success message based on document type and next steps."""
        try:
            # Get document type in Hebrew
            document_names = {
                DocumentType.ID_CARD: "תעודת זהות",
                DocumentType.PAYSLIPS: "תלושי שכר",
                DocumentType.BANK_STATEMENTS: "העתקי בנק",
                DocumentType.PNL: "דוח רווח והפסד",
                DocumentType.SEPHACH: "טופס ספח"
            }
            
            current_doc_name = document_names.get(document_type, document_type.value)
            
            if next_document:
                next_doc_name = document_names.get(next_document, next_document.value)
                
                # Create contextual message based on what was just processed
                if document_type == DocumentType.ID_CARD:
                    return f"""✅ מעולה! {current_doc_name} התקבל ואושר בהצלחה!

עכשיו אני צריך את {next_doc_name} שלך.

{self._get_document_request_message(next_doc_name)}

אם יש לך שאלות, אני כאן לעזור! 😊"""
                
                elif document_type == DocumentType.PAYSLIPS:
                    return f"""✅ תלושי השכר התקבלו ואושרו!

עכשיו אני צריך את {next_doc_name} שלך.

{self._get_document_request_message(next_doc_name)}

אנחנו כמעט בסיום! 🎉"""
                
                elif document_type == DocumentType.BANK_STATEMENTS:
                    return f"""✅ העתקי הבנק התקבלו ואושרו!

עכשיו אני צריך את {next_doc_name} שלך.

{self._get_document_request_message(next_doc_name)}

אנחנו כמעט בסיום! 🎉"""
                
                else:
                    return f"""✅ {current_doc_name} התקבל ואושר!

עכשיו אני צריך את {next_doc_name} שלך.

{self._get_document_request_message(next_doc_name)}"""
            
            else:
                # All documents collected
                return f"""🎉 מעולה! כל המסמכים התקבלו ואושרו בהצלחה!

עכשיו נצטרך מידע על הערבים שלך.

**הערב הראשון:**
אנא שלח את השם ומספר הטלפון של הערב הראשון.

אנחנו כמעט בסיום התהליך! 🚀"""
                
        except Exception as e:
            logger.error("Error creating document success message", error=str(e))
            return f"מעולה! {document_type.value} התקבל ואושר."

    def _create_document_error_message(self, document_type, errors, warnings) -> str:
        """Create contextual error message based on document type and specific errors."""
        try:
            # Get document type in Hebrew
            document_names = {
                DocumentType.ID_CARD: "תעודת זהות",
                DocumentType.PAYSLIPS: "תלושי שכר", 
                DocumentType.BANK_STATEMENTS: "העתקי בנק",
                DocumentType.PNL: "דוח רווח והפסד",
                DocumentType.SEPHACH: "טופס ספח"
            }
            
            doc_name = document_names.get(document_type, document_type.value)
            
            # Check for specific error types
            if any("doesn't match expected" in error or "name mismatch" in error.lower() for error in errors):
                return f"""❌ {doc_name} לא אושרה

השם במסמך לא תואם לשם שלך במערכת.

**מה לעשות:**
• וודא ששלחת את {doc_name} הנכונה
• אם זה השם הנכון, פנה לצוות התמיכה
• נסה לצלם מחדש עם תאורה טובה

אנא שלח שוב את {doc_name}."""
            
            elif any("ID number" in error for error in errors):
                return f"""❌ {doc_name} לא אושרה

מספר הזהות לא תקין או לא ברור.

**מה לעשות:**
• וודא שהתמונה ברורה וחדה
• מספר הזהות חייב להיות קריא
• נסה לצלם מחדש עם תאורה טובה
• הימנע מברקים או צללים

אנא שלח שוב את {doc_name}."""
            
            elif any("not found" in error for error in errors):
                return f"""❌ {doc_name} לא אושרה

לא הצלחתי לקרוא את המידע במסמך.

**מה לעשות:**
• וודא שהתמונה ברורה וחדה
• כל הטקסט חייב להיות קריא
• נסה לצלם מחדש עם תאורה טובה
• הימנע מברקים או צללים

אנא שלח שוב את {doc_name}."""
            
            else:
                # Generic error with specific feedback
                error_details = "\n".join([f"• {error}" for error in errors[:3]])  # Show first 3 errors
                return f"""❌ {doc_name} לא אושרה

{error_details}

**מה לעשות:**
• וודא שהתמונה ברורה וחדה
• כל הטקסט חייב להיות קריא
• נסה לצלם מחדש עם תאורה טובה

אנא שלח שוב את {doc_name}."""
                
        except Exception as e:
            logger.error("Error creating document error message", error=str(e))
            return f"המסמך לא אושר. אנא שלח שוב את {document_type.value}."

    async def _get_next_document(self, current_document: DocumentType, tenant_occupation: str = None, conversation_context: Dict[str, Any] = None) -> Optional[DocumentType]:
        """Get the next document type in sequence based on occupation."""
        # Base sequence
        base_sequence = [
            DocumentType.ID_CARD,
            DocumentType.SEPHACH,
        ]
        
        # Get occupation from conversation context if not provided
        if not tenant_occupation and conversation_context:
            tenant_occupation = conversation_context.get("tenant_occupation")
        
        # Add financial documents based on occupation
        if tenant_occupation:
            # Use Vertex AI to analyze occupation and determine document type
            document_type = await self._analyze_occupation_for_document_type(tenant_occupation)
            base_sequence.append(document_type)
        else:
            # If occupation unknown, ask for either payslips or PNL
            # We'll let the user choose by asking for either one
            base_sequence.append(DocumentType.PAYSLIPS)  # Default to payslips first
        
        # Always end with bank statements
        base_sequence.append(DocumentType.BANK_STATEMENTS)
        
        try:
            current_index = base_sequence.index(current_document)
            if current_index < len(base_sequence) - 1:
                return base_sequence[current_index + 1]
            return None
        except ValueError:
            return None

    async def _analyze_occupation_for_document_type(self, occupation: str) -> DocumentType:
        """Use Vertex AI to analyze occupation and determine if person needs payslips or PNL."""
        try:
            from app.services.vertex_ai_service import vertex_ai_service
            
            prompt = f"""
Analyze this occupation and determine what financial document this person should provide:

Occupation: "{occupation}"

Determine if this person is:
1. SALARIED EMPLOYEE - receives regular salary from employer → needs PAYSLIPS
2. SELF-EMPLOYED/BUSINESS OWNER - runs their own business → needs PNL (Profit & Loss statement)

Consider these indicators:
- Salaried: employee, worker, manager, engineer, teacher, doctor (employed by company)
- Self-employed: business owner, freelancer, consultant, contractor, entrepreneur, shop owner

Return ONLY one word: "PAYSLIPS" or "PNL"
"""
            
            response = await vertex_ai_service.generate_response(prompt)
            response_clean = response.strip().upper()
            
            if "PNL" in response_clean:
                logger.info("Vertex AI determined PNL needed", occupation=occupation, response=response_clean)
                return DocumentType.PNL
            else:
                logger.info("Vertex AI determined payslips needed", occupation=occupation, response=response_clean)
                return DocumentType.PAYSLIPS
                
        except Exception as e:
            logger.error("Error analyzing occupation with Vertex AI", occupation=occupation, error=str(e))
            # Fallback to keyword matching
            occupation_lower = occupation.lower()
            if any(keyword in occupation_lower for keyword in ["עצמאי", "self-employed", "business", "עסק", "freelance", "freelancer", "entrepreneur", "consultant"]):
                return DocumentType.PNL
            else:
                return DocumentType.PAYSLIPS

    def _get_document_request_message(self, document_type: str) -> str:
        """Get the request message for a document type."""
        messages = {
            DocumentType.ID_CARD.value: "אנא שלח את תמונת תעודת הזהות שלך (Teudat Zehut).",
            DocumentType.SEPHACH.value: "אנא שלח את הטופס ספח (Sephach).",
            DocumentType.PAYSLIPS.value: "אנא שלח את 3 תלושי השכר האחרונים שלך (כקובץ PDF או תמונות).",
            DocumentType.PNL.value: "אנא שלח את דוח רווח והפסד (PNL) החתום על ידי רואה חשבון.",
            DocumentType.BANK_STATEMENTS.value: "אנא שלח את דוחות הבנק של 3 החודשים האחרונים."
        }
        
        return messages.get(document_type, "אנא שלח את המסמך הנדרש.")

    async def _handle_guarantor_state(self, phone: str, message_body: str, conversation_state: ConversationStateModel, guarantor_num: int) -> str:
        """Handle guarantor information collection."""
        try:
            # Use Vertex AI to parse name and phone from the message
            prompt = f"""Extract the name and phone number from this Hebrew text:

Text: {message_body}

Return as JSON:
{{
    "name": "Full name in Hebrew",
    "phone": "Phone number with country code"
}}

Return ONLY the JSON object."""
            
            response = await vertex_ai_service.generate_response(prompt)
            
            # Parse the response
            import json
            try:
                # Clean response
                cleaned_response = response.strip()
                if cleaned_response.startswith("```json"):
                    cleaned_response = cleaned_response[7:]
                if cleaned_response.endswith("```"):
                    cleaned_response = cleaned_response[:-3]
                
                parsed_data = json.loads(cleaned_response)
                guarantor_name = parsed_data.get("name", "").strip()
                guarantor_phone = parsed_data.get("phone", "").strip()
                
                logger.info("Parsed guarantor info", extra={
                    "guarantor_name": guarantor_name,
                    "guarantor_phone": guarantor_phone,
                    "guarantor_num": guarantor_num
                })
                
                if not guarantor_name or not guarantor_phone:
                    return "אנא שלח את השם המלא ומספר הטלפון של הערב."
                    
            except json.JSONDecodeError:
                logger.warning("Failed to parse guarantor info JSON", extra={"response": response})
                return "אנא שלח את השם ומספר הטלפון בפורמט: שם מלא, מספר טלפון"
            
            # Normalize phone number
            normalized_phone = normalize_phone_number(guarantor_phone)
            
            # Get tenant information
            tenant_id = conversation_state.context_data.get("tenant_id")
            if not tenant_id:
                return "שגיאה: לא נמצא מידע על השוכר."
            
            # Get tenant details
            tenant = await supabase_service.get_tenant_by_id(tenant_id)
            if not tenant:
                return "שגיאה: לא נמצא מידע על השוכר."
            
            # Create guarantor record
            logger.info("Creating guarantor", extra={
                "tenant_id": tenant_id,
                "guarantor_number": guarantor_num,
                "guarantor_name": guarantor_name,
                "guarantor_phone": normalized_phone
            })
            
            guarantor_result = await guarantor_service.create_guarantor(
                tenant_id=tenant_id,
                guarantor_number=guarantor_num,
                full_name=guarantor_name,
                phone_number=normalized_phone
            )
            
            logger.info("Guarantor creation result", extra={
                "success": guarantor_result["success"],
                "guarantor_id": guarantor_result.get("guarantor", {}).get("id") if guarantor_result["success"] else None,
                "error": guarantor_result.get("error") if not guarantor_result["success"] else None
            })
            
            if not guarantor_result["success"]:
                return f"שגיאה ביצירת ערב: {guarantor_result.get('error', 'Unknown error')}"
            
            # Send message to guarantor
            await self._send_guarantor_collection_message(guarantor_result["guarantor"], tenant)
            
            # Check if this was an existing guarantor
            was_existing = guarantor_result.get("was_existing", False)
            
            if guarantor_num == 1:
                # Move to guarantor 2
                await self._update_conversation_state(phone, ConversationState.GUARANTOR_2, {
                    **conversation_state.context_data,
                    "current_guarantor": 2,
                    "guarantor1_id": guarantor_result["guarantor"]["id"]
                })
                
                if was_existing:
                    return f"פרטי הערב הראשון עודכנו ונשלח הודעה לערב. עכשיו אנא שלח את השם ומספר הטלפון של הערב השני."
                else:
                    return f"תודה! פרטי הערב הראשון התקבלו ונשלח הודעה לערב. עכשיו אנא שלח את השם ומספר הטלפון של הערב השני."
                
            elif guarantor_num == 2:
                # Mark process as completed
                await self._update_conversation_state(phone, ConversationState.COMPLETED, {
                    **conversation_state.context_data,
                    "guarantor2_id": guarantor_result["guarantor"]["id"],
                    "process_completed": True
                })
                
                if was_existing:
                    return "מעולה! פרטי הערב השני עודכנו. שני הערבים קיבלו הודעות ונשלחו אליהם הוראות לשליחת המסמכים. התהליך הושלם בהצלחה!"
                else:
                    return "מעולה! כל הפרטים התקבלו. שני הערבים קיבלו הודעות ונשלחו אליהם הוראות לשליחת המסמכים. התהליך הושלם בהצלחה!"
            
        except Exception as e:
            logger.error("Error handling guarantor state", phone=phone, guarantor_num=guarantor_num, error=str(e))
            return "מצטער, אירעה שגיאה. אנא נסה שוב."
    
    async def _send_guarantor_collection_message(self, guarantor: Dict[str, Any], tenant):
        """Send collection message to guarantor."""
        try:
            # Send introduction message
            intro_message = f"""שלום {guarantor['full_name']},

הוספת כערב עבור {tenant.full_name} ב-{tenant.property_name}.

אני אעזור לך לשלוח את המסמכים הנדרשים. בואו נתחיל עם המסמך הראשון:

אנא שלח את תעודת הזהות שלך."""
            
            await whatsapp_service.send_text_message(guarantor["phone_number"], intro_message)
            
            # Create guarantor conversation state - set to DOCUMENTS state directly
            await guarantor_service.update_guarantor_conversation_state(
                guarantor["id"],
                guarantor["phone_number"],
                "DOCUMENTS",
                {"current_document": "id_card", "tenant_name": tenant.full_name}
            )
            
            # Update guarantor status
            await guarantor_service.update_guarantor_status(guarantor["id"], "in_progress")
            
            logger.info("Guarantor collection message sent", extra={
                "guarantor_id": guarantor["id"],
                "guarantor_name": guarantor["full_name"],
                "tenant_name": tenant.full_name
            })
            
        except Exception as e:
            logger.error("Error sending guarantor collection message", extra={"error": str(e)})

    async def _handle_completed_state(self, phone: str, message_body: str, conversation_state: ConversationStateModel) -> str:
        """Handle completed state - process is finished."""
        return "התהליך הושלם בהצלחה! תודה שהצטרפת למשפחת מגורית. אם יש לך שאלות נוספות, אנא פנה לצוות התמיכה."

    # AI-Powered Handler Methods
    async def _handle_guarantor_with_ai(self, phone_number: str, message_body: str, message_type: str, media_data: bytes = None) -> str:
        """Handle guarantor message with AI responses."""
        try:
            # Store user message in history
            await ai_conversation_service._store_message_history(
                phone_number, "guarantor", "user_message", message_body, "GUARANTOR_MESSAGE"
            )
            
            # Get guarantor data first
            from app.services.supabase_service import supabase_service
            guarantor = await supabase_service.find_guarantor_by_phone(phone_number)
            
            # Process the message using existing logic
            result = await guarantor_conversation_service.process_guarantor_message(
                phone_number, message_type, media_data
            )
            
            # Check if document processing was successful
            if result.get("success") and result.get("message"):
                logger.info("Document processing successful, letting AI handle confirmation", extra={
                    "phone_number": phone_number,
                    "result_message": result.get("message")
                })
                # Let the AI handle the confirmation message instead of pre-written message
                # Continue to AI response generation
            
            # If document processing didn't return a direct message, generate AI response
            logger.info("Document processing didn't return direct message, generating AI response", extra={
                "phone_number": phone_number,
                "result_success": result.get("success", False)
            })
            
            # Get guarantor context data
            guarantor_context = {}
            if guarantor:
                # Get tenant information for context
                tenant = await supabase_service.get_tenant_by_id(guarantor.tenant_id)
                if tenant:
                    guarantor_context = {
                        "guarantor_name": guarantor.full_name,
                        "tenant_name": tenant.full_name,
                        "property_name": tenant.property_name,
                        "apartment_number": tenant.apartment_number
                    }
                
                # Get current document from conversation state
                conversation_state = await guarantor_service.get_guarantor_conversation_state(phone_number)
                current_document = conversation_state.get("context_data", {}).get("current_document", "id_card")
                guarantor_context["current_document"] = current_document
                print(f"DEBUG: Current document for guarantor: {current_document}")
            
            # Add document approval/rejection status to context
            if result.get("success") and result.get("message"):
                guarantor_context["document_just_approved"] = True
                # Extract next document from the result message
                result_message = result.get("message", "")
                if "next document" in result_message:
                    # Extract the next document name from the message
                    # Format: "Document id_card approved, next document sephach requested"
                    parts = result_message.split("next document ")
                    if len(parts) > 1:
                        next_doc = parts[1].split(" ")[0]
                        guarantor_context["next_document"] = next_doc
                        print(f"DEBUG: Extracted next document: {next_doc}")
                else:
                    print(f"DEBUG: No 'next document' found in message: {result_message}")
            elif not result.get("success") and result.get("message"):
                # Document was rejected - pass rejection context to AI
                guarantor_context["document_just_rejected"] = True
                guarantor_context["rejection_reason"] = result.get("message", "Document validation failed")
                print(f"DEBUG: Document rejected - {result.get('message', 'Unknown error')}")
            
            # Generate AI response
            ai_response = await ai_conversation_service.generate_response(
                phone_number=phone_number,
                user_message=message_body,
                conversation_type="guarantor",
                current_state="GUARANTOR_MESSAGE",
                context_data=guarantor_context
            )
            
            return ai_response
            
        except Exception as e:
            logger.error("Error handling guarantor with AI", extra={
                "phone_number": phone_number,
                "error": str(e)
            })
            return "מצטער, אירעה שגיאה. אנא נסה שוב."

    async def _handle_greeting_state_with_ai(self, phone: str, message_body: str, conversation_state: ConversationStateModel) -> str:
        """Handle greeting state with AI responses."""
        try:
            # Store user message in history
            await ai_conversation_service._store_message_history(
                phone, "tenant", "user_message", message_body, conversation_state.current_state, conversation_state.context_data
            )
            
            # Use the enhanced greeting logic that prevents duplicate messages
            response = await self._handle_greeting_state(phone, message_body, conversation_state)
            
            # Check if this is a manual lookup case - use the hardcoded response
            if conversation_state.context_data.get("lookup_required"):
                # For manual lookup cases, use the response directly (no AI modification needed)
                return response
            
            # IMPORTANT: Get the UPDATED conversation state after processing greeting
            updated_conversation_state = await self._get_or_create_conversation_state(phone)
            
            # For regular tenant greeting, generate AI response with UPDATED state
            ai_response = await ai_conversation_service.generate_response(
                phone_number=phone,
                user_message=message_body,
                conversation_type="tenant",
                current_state=updated_conversation_state.current_state,
                context_data=updated_conversation_state.context_data
            )
            
            return ai_response
            
        except Exception as e:
            logger.error("Error handling greeting state with AI", extra={
                "phone": phone,
                "error": str(e)
            })
            return await self._handle_greeting_state(phone, message_body, conversation_state)

    async def _handle_confirmation_state_with_ai(self, phone: str, message_body: str, conversation_state: ConversationStateModel) -> str:
        """Handle confirmation state with AI responses."""
        try:
            # Store user message in history
            await ai_conversation_service._store_message_history(
                phone, "tenant", "user_message", message_body, conversation_state.current_state, conversation_state.context_data
            )
            
            # Process using existing logic
            response = await self._handle_confirmation_state(phone, message_body, conversation_state)
            
            # IMPORTANT: Get the UPDATED conversation state after processing confirmation
            updated_conversation_state = await self._get_or_create_conversation_state(phone)
            
            # Check if we moved to PERSONAL_INFO state - if so, don't generate AI response
            # to avoid duplicate confirmation requests
            if updated_conversation_state.current_state == ConversationState.PERSONAL_INFO:
                # We've moved to personal info collection, use the direct response
                return response
            
            # Generate AI response with UPDATED state only if we're still in CONFIRMATION
            ai_response = await ai_conversation_service.generate_response(
                phone_number=phone,
                user_message=message_body,
                conversation_type="tenant",
                current_state=updated_conversation_state.current_state,
                context_data=updated_conversation_state.context_data
            )
            
            return ai_response
            
        except Exception as e:
            logger.error("Error handling confirmation state with AI", extra={
                "phone": phone,
                "error": str(e)
            })
            return await self._handle_confirmation_state(phone, message_body, conversation_state)

    async def _handle_personal_info_state_with_ai(self, phone: str, message_body: str, conversation_state: ConversationStateModel) -> str:
        """Handle personal info state with AI responses and proper business logic."""
        try:
            current_field = conversation_state.context_data.get("current_field", "occupation")
            tenant_id = conversation_state.context_data.get("tenant_id")
            
            logger.info("Processing personal info with AI", extra={
                "phone": phone,
                "current_field": current_field,
                "message": message_body,
                "tenant_id": tenant_id,
                "conversation_state": conversation_state.current_state,
                "context_data": conversation_state.context_data
            })
            
            # Store user message in history
            await ai_conversation_service._store_message_history(
                phone, "tenant", "user_message", message_body, conversation_state.current_state, conversation_state.context_data
            )
            
            # Check if this might be a confirmation response that got misrouted
            # Look for confirmation words in the message
            confirmation_words = ["yes", "yeah", "yep", "sure", "ok", "alright", "correct", "right", "perfect", 
                                "sounds good", "that's correct", "i confirm", "confirmed", "agreed", "looks good",
                                "כן", "נכון", "אישור", "בסדר", "טוב", "מושלם", "נשמע טוב", "זה נכון", "אני מאשר"]
            
            message_lower = message_body.lower().strip()
            is_confirmation_response = any(word in message_lower for word in confirmation_words)
            
            if is_confirmation_response and current_field == "occupation":
                # This looks like a confirmation response that got misrouted to personal info
                # Redirect back to asking for occupation properly
                logger.info("Detected confirmation response in personal info state, redirecting to occupation question", extra={
                    "phone": phone,
                    "message": message_body,
                    "current_field": current_field
                })
                
                # Generate AI response asking for occupation
                ai_response = await ai_conversation_service.generate_response(
                    phone_number=phone,
                    user_message=message_body,
                    conversation_type="tenant",
                    current_state=conversation_state.current_state,
                    context_data=conversation_state.context_data
                )
                return ai_response
            
            # Use Vertex AI to validate and parse response
            question = f"מה ה{current_field} שלך?"
            if current_field == "number_of_children":
                question = "כמה ילדים יש לך?"
            elif current_field == "family_status":
                question = "מה המצב המשפחתי שלך?"
            elif current_field == "occupation":
                question = "מה העיסוק שלך?"
            
            logger.info("Validating user response", extra={
                "phone": phone,
                "current_field": current_field,
                "question": question,
                "user_response": message_body
            })
            
            validation_result = await vertex_ai_service.validate_human_response(
                question,
                message_body,
                conversation_state.context_data
            )
            
            if not validation_result.get("is_valid", False):
                logger.warning("Invalid response from user", extra={
                    "phone": phone,
                    "message": message_body,
                    "validation_result": validation_result
                })
                return validation_result.get("feedback", "אנא שלח תגובה תקינה.")
            
            parsed_data = validation_result.get("parsed_data", {})
            
            # Enhanced validation: make sure we have meaningful data
            if not parsed_data or all(v is None for v in parsed_data.values()):
                logger.warning("Validation returned empty parsed_data", extra={
                    "phone": phone,
                    "current_field": current_field,
                    "validation_result": validation_result
                })
                
                # Create fallback data based on current field
                if current_field == "occupation":
                    parsed_data = {"occupation": message_body.strip()}
                elif current_field == "family_status":
                    parsed_data = {"family_status": message_body.strip()}
                elif current_field == "number_of_children":
                    # Try to extract number
                    import re
                    numbers = re.findall(r'\d+', message_body)
                    parsed_data = {"number_of_children": int(numbers[0]) if numbers else 0}
                else:
                    parsed_data = {"extracted_info": message_body.strip()}
            
            # Update tenant information based on current field
            if tenant_id:
                if current_field == "occupation":
                    occupation_value = parsed_data.get("occupation", message_body)
                    logger.info("Updating occupation", extra={
                        "tenant_id": tenant_id,
                        "occupation": occupation_value,
                        "parsed_data": parsed_data
                    })
                    
                    from app.models.tenant import TenantUpdate
                    await supabase_service.update_tenant(tenant_id, TenantUpdate(occupation=occupation_value))
                    await self._update_conversation_state(phone, ConversationState.PERSONAL_INFO, {
                        **conversation_state.context_data,
                        "current_field": "family_status"
                    })
                    
                elif current_field == "family_status":
                    family_status_value = parsed_data.get("family_status", message_body)
                    logger.info("Updating family status", extra={
                        "tenant_id": tenant_id,
                        "family_status": family_status_value,
                        "parsed_data": parsed_data
                    })
                    
                    from app.models.tenant import TenantUpdate
                    await supabase_service.update_tenant(tenant_id, TenantUpdate(family_status=family_status_value))
                    await self._update_conversation_state(phone, ConversationState.PERSONAL_INFO, {
                        **conversation_state.context_data,
                        "current_field": "number_of_children"
                    })
                    
                elif current_field == "number_of_children":
                    number_of_children = parsed_data.get("number_of_children", 0)
                    logger.info("Updating number of children", extra={
                        "tenant_id": tenant_id,
                        "number_of_children": number_of_children,
                        "parsed_data": parsed_data
                    })
                    
                    from app.models.tenant import TenantUpdate
                    await supabase_service.update_tenant(tenant_id, TenantUpdate(number_of_children=number_of_children))
                    
                    # Get tenant occupation to determine document sequence
                    tenant = await supabase_service.get_tenant_by_id(tenant_id)
                    tenant_occupation = tenant.occupation if tenant else None
                    
                    # Move to documents state with ID_CARD as first document
                    await self._update_conversation_state(phone, ConversationState.DOCUMENTS, {
                        **conversation_state.context_data,
                        "current_document": DocumentType.ID_CARD.value,
                        "tenant_occupation": tenant_occupation
                    })
            
            # Get updated conversation state for AI
            updated_conversation_state = await self._get_or_create_conversation_state(phone)
            
            # Generate AI response with updated context
            ai_response = await ai_conversation_service.generate_response(
                phone_number=phone,
                user_message=message_body,
                conversation_type="tenant",
                current_state=updated_conversation_state.current_state,
                context_data=updated_conversation_state.context_data
            )
            
            logger.info("AI personal info response generated", extra={
                "phone": phone,
                "response_length": len(ai_response),
                "new_state": updated_conversation_state.current_state,
                "new_field": updated_conversation_state.context_data.get("current_field")
            })
            
            return ai_response
            
        except Exception as e:
            logger.error("Error handling personal info state with AI", extra={
                "phone": phone,
                "error": str(e)
            })
            return await self._handle_personal_info_state(phone, message_body, conversation_state)

    async def _handle_documents_state_with_ai(self, phone: str, message_body: str, message_type: str, media_data: bytes, conversation_state: ConversationStateModel) -> str:
        """Handle documents state with AI responses."""
        try:
            # Store user message in history
            await ai_conversation_service._store_message_history(
                phone, "tenant", "user_message", message_body, conversation_state.current_state, conversation_state.context_data
            )
            
            # Process using existing logic
            response = await self._handle_documents_state(phone, message_body, message_type, media_data, conversation_state)
            
            # Check if we have a specific contextual response (error messages, success messages)
            # But allow AI responses for text messages when user is in documents state
            if any(keyword in response for keyword in ["❌", "✅", "לא אושרה", "התקבל ואושר", "מעולה"]):
                # Use the contextual response instead of generic AI
                return response
            
            # For document request messages, only use hardcoded if it's a direct document request
            # Allow AI to handle conversational responses
            if "אנא שלח את" in response and message_type in ["image", "document"]:
                # This is a direct document request for media upload
                return response
            
            # Generate AI response only for generic cases
            ai_response = await ai_conversation_service.generate_response(
                phone_number=phone,
                user_message=message_body,
                conversation_type="tenant",
                current_state=conversation_state.current_state,
                context_data=conversation_state.context_data
            )
            
            return ai_response
            
        except Exception as e:
            logger.error("Error handling documents state with AI", extra={
                "phone": phone,
                "error": str(e)
            })
            return await self._handle_documents_state(phone, message_body, message_type, media_data, conversation_state)

    async def _handle_guarantor_state_with_ai(self, phone: str, message_body: str, conversation_state: ConversationStateModel, guarantor_number: int) -> str:
        """Handle guarantor state with AI responses."""
        try:
            # Store user message in history
            await ai_conversation_service._store_message_history(
                phone, "tenant", "user_message", message_body, conversation_state.current_state, conversation_state.context_data
            )
            
            # Process using existing logic
            response = await self._handle_guarantor_state(phone, message_body, conversation_state, guarantor_number)
            
            # Generate AI response
            ai_response = await ai_conversation_service.generate_response(
                phone_number=phone,
                user_message=message_body,
                conversation_type="tenant",
                current_state=conversation_state.current_state,
                context_data=conversation_state.context_data
            )
            
            return ai_response
            
        except Exception as e:
            logger.error("Error handling guarantor state with AI", extra={
                "phone": phone,
                "guarantor_number": guarantor_number,
                "error": str(e)
            })
            return await self._handle_guarantor_state(phone, message_body, conversation_state, guarantor_number)

    async def _handle_completed_state_with_ai(self, phone: str, message_body: str, conversation_state: ConversationStateModel) -> str:
        """Handle completed state with AI responses."""
        try:
            # Store user message in history
            await ai_conversation_service._store_message_history(
                phone, "tenant", "user_message", message_body, conversation_state.current_state, conversation_state.context_data
            )
            
            # Process using existing logic
            response = await self._handle_completed_state(phone, message_body, conversation_state)
            
            # Generate AI response
            ai_response = await ai_conversation_service.generate_response(
                phone_number=phone,
                user_message=message_body,
                conversation_type="tenant",
                current_state=conversation_state.current_state,
                context_data=conversation_state.context_data
            )
            
            return ai_response
            
        except Exception as e:
            logger.error("Error handling completed state with AI", extra={
                "phone": phone,
                "error": str(e)
            })
            return await self._handle_completed_state(phone, message_body, conversation_state)


# Global instance
conversation_flow_service = ConversationFlowService()
