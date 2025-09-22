"""
Guarantor Conversation Service

This service handles the conversation flow for guarantors including:
- Managing guarantor conversation states
- Processing guarantor messages
- Handling guarantor document uploads
- Managing guarantor document collection flow
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime

from app.services.guarantor_service import guarantor_service
from app.services.document_ai_service import document_ai_service
from app.services.whatsapp_service import whatsapp_service
from app.services.vertex_ai_service import vertex_ai_service
from app.models.tenant import DocumentType

logger = logging.getLogger(__name__)


class GuarantorConversationService:
    """Service for managing guarantor conversation flow."""
    
    def __init__(self):
        self.guarantor_service = guarantor_service
        self.document_ai_service = document_ai_service
        self.whatsapp_service = whatsapp_service
        self.vertex_ai_service = vertex_ai_service
    
    async def process_guarantor_message(self, phone_number: str, message_type: str, 
                                       content: Any = None) -> Dict[str, Any]:
        """Process incoming message from guarantor."""
        try:
            logger.info("Processing guarantor message", extra={
                "phone_number": phone_number,
                "message_type": message_type
            })
            
            # Get guarantor by phone number
            guarantor = await self.guarantor_service.get_guarantor_by_phone(phone_number)
            if not guarantor:
                logger.warning("Guarantor not found", extra={"phone_number": phone_number})
                return {
                    "success": False,
                    "message": "Guarantor not found. Please contact the tenant."
                }
            
            # Get conversation state
            conversation_state = await self.guarantor_service.get_guarantor_conversation_state(phone_number)
            current_state = conversation_state.get("current_state", "GREETING") if conversation_state else "GREETING"
            
            logger.info("Guarantor conversation state", extra={
                "guarantor_id": guarantor["id"],
                "current_state": current_state,
                "guarantor_number": guarantor["guarantor_number"]
            })
            
            # Route to appropriate handler
            if current_state == "GREETING":
                # If it's the first message from guarantor, send greeting and move to documents
                if message_type == "text" and content and any(word in content.lower() for word in ["שלום", "היי", "hello", "hi"]):
                    return await self._handle_guarantor_greeting(guarantor, message_type, content)
                else:
                    # Send greeting message and move to documents state
                    return await self._handle_guarantor_greeting(guarantor, message_type, content)
            elif current_state == "PERSONAL_INFO":
                return await self._handle_guarantor_personal_info(guarantor, message_type, content)
            elif current_state == "DOCUMENTS":
                return await self._handle_guarantor_documents(guarantor, message_type, content)
            elif current_state == "COMPLETED":
                return await self._handle_guarantor_completed(guarantor, message_type, content)
            else:
                # Default to documents state for any unknown state (since guarantors should be in documents state)
                logger.info("Unknown state, defaulting to documents", extra={
                    "current_state": current_state,
                    "guarantor_id": guarantor["id"]
                })
                return await self._handle_guarantor_documents(guarantor, message_type, content)
                
        except Exception as e:
            logger.error("Error processing guarantor message", extra={"error": str(e)})
            return {
                "success": False,
                "message": "An error occurred. Please try again."
            }
    
    async def _handle_guarantor_greeting(self, guarantor: Dict[str, Any], message_type: str, content: Any) -> Dict[str, Any]:
        """Handle guarantor greeting and initial setup."""
        try:
            # Get tenant information
            from app.services.supabase_service import supabase_service
            tenant = await supabase_service.get_tenant_by_id(guarantor["tenant_id"])
            if not tenant:
                return {
                    "success": False,
                    "message": "Tenant information not found."
                }
            
            # Check if this is a text message (greeting from guarantor)
            if message_type == "text" and content:
                # Respond to guarantor's greeting
                response_message = f"""שלום {guarantor['full_name']},

הוספת כערב עבור {tenant.full_name} ב-{tenant.property_name}.

אני אעזור לך לשלוח את המסמכים הנדרשים. בואו נתחיל עם המסמך הראשון:

אנא שלח את תעודת הזהות שלך."""
                
                # Send message
                await self.whatsapp_service.send_text_message(guarantor["phone_number"], response_message)
            
            # Update conversation state to DOCUMENTS with first document
            await self.guarantor_service.update_guarantor_conversation_state(
                guarantor["id"], 
                guarantor["phone_number"], 
                "DOCUMENTS",
                {"current_document": "id_card", "tenant_name": tenant.full_name}
            )
            
            # Update guarantor status
            await self.guarantor_service.update_guarantor_status(guarantor["id"], "in_progress")
            
            return {
                "success": True,
                "message": "Greeting sent to guarantor"
            }
            
        except Exception as e:
            logger.error("Error handling guarantor greeting", extra={"error": str(e)})
            return {
                "success": False,
                "message": "Error sending greeting message"
            }
    
    async def _handle_guarantor_personal_info(self, guarantor: Dict[str, Any], message_type: str, content: Any) -> Dict[str, Any]:
        """Handle guarantor personal information collection."""
        try:
            if message_type == "text":
                # Parse personal information from text
                personal_info = await self._parse_guarantor_personal_info(content)
                
                if personal_info:
                    # Update guarantor with personal info
                    await self._update_guarantor_personal_info(guarantor["id"], personal_info)
                    
                    # Move to documents state
                    await self.guarantor_service.update_guarantor_conversation_state(
                        guarantor["id"],
                        guarantor["phone_number"],
                        "DOCUMENTS",
                        {"personal_info_collected": True}
                    )
                    
                    # Send documents request message
                    documents_message = """מעולה! עכשיו אנא שלח את המסמכים הבאים:

1. תעודת זהות
2. ספח (Sephach)
3. תלושי משכורת או דוח רווח והפסד
4. דוח בנק

אנא שלח כל מסמך בנפרד."""
                    
                    await self.whatsapp_service.send_text_message(guarantor["phone_number"], documents_message)
                    
                    return {
                        "success": True,
                        "message": "Personal info collected, documents requested"
                    }
                else:
                    # Ask for personal info again
                    info_message = """אנא שלח את הפרטים הבאים:
- שם מלא
- מספר טלפון
- כתובת אימייל

בפורמט: שם מלא, טלפון, אימייל"""
                    
                    await self.whatsapp_service.send_text_message(guarantor["phone_number"], info_message)
                    return {
                        "success": True,
                        "message": "Requested personal info again"
                    }
            
            return {
                "success": False,
                "message": "Please send your personal information as text."
            }
            
        except Exception as e:
            logger.error("Error handling guarantor personal info", extra={"error": str(e)})
            return {
                "success": False,
                "message": "Error processing personal information"
            }
    
    async def _handle_guarantor_documents(self, guarantor: Dict[str, Any], message_type: str, content: Any) -> Dict[str, Any]:
        """Handle guarantor document uploads."""
        try:
            logger.info("Handling guarantor documents", extra={
                "guarantor_id": guarantor["id"],
                "message_type": message_type,
                "has_content": bool(content)
            })
            
            if message_type in ["image", "document"]:
                # Get current conversation state
                conversation_state = await self.guarantor_service.get_guarantor_conversation_state(guarantor["phone_number"])
                current_document = conversation_state.get("context_data", {}).get("current_document", "id_card")
                
                logger.info("Processing guarantor document", extra={
                    "current_document": current_document,
                    "guarantor_id": guarantor["id"]
                })
                
                # Process document using the document AI service
                from app.models.tenant import DocumentType
                document_type_map = {
                    "id_card": DocumentType.ID_CARD,
                    "sephach": DocumentType.SEPHACH,
                    "payslips": DocumentType.PAYSLIPS,
                    "bank_statements": DocumentType.BANK_STATEMENTS
                }
                
                doc_type = document_type_map.get(current_document, DocumentType.ID_CARD)
                
                # Process document using document AI service
                result = await self.document_ai_service.process_guarantor_document(
                    content, doc_type, guarantor
                )
                
                logger.info("Document processing result", extra={
                    "is_valid": result.get("validation_result", {}).get("is_valid", False),
                    "has_file_url": bool(result.get("file_url")),
                    "errors": result.get("validation_result", {}).get("errors", [])
                })
                
                if result.get("validation_result", {}).get("is_valid", False):
                    # Update documents status
                    await self.guarantor_service.update_guarantor_documents_status(
                        guarantor["id"],
                        current_document,
                        "validated",
                        result.get("file_url")
                    )
                    
                    # Get next document
                    next_document = await self._get_next_guarantor_document(current_document)
                    
                    if next_document:
                        # Update conversation state with next document
                        await self.guarantor_service.update_guarantor_conversation_state(
                            guarantor["id"],
                            guarantor["phone_number"],
                            "DOCUMENTS",
                            {
                                **conversation_state.get("context_data", {}),
                                "current_document": next_document
                            }
                        )
                        
                        # Send next document request
                        next_message = await self._get_guarantor_document_request_message(next_document)
                        
                        return {
                            "success": True,
                            "message": f"מעולה! {current_document} התקבל ואושר. {next_message}"
                        }
                    else:
                        # All documents collected
                        await self._send_guarantor_completion_message(guarantor)
                        
                        # Update conversation state
                        await self.guarantor_service.update_guarantor_conversation_state(
                            guarantor["id"],
                            guarantor["phone_number"],
                            "COMPLETED",
                            {"all_documents_collected": True}
                        )
                        
                        # Update guarantor status
                        await self.guarantor_service.update_guarantor_status(guarantor["id"], "completed")
                        
                        return {
                            "success": True,
                            "message": "All documents collected, guarantor completed"
                        }
                else:
                    # Document rejected - provide specific feedback
                    errors = result.get("validation_result", {}).get("errors", [])
                    warnings = result.get("validation_result", {}).get("warnings", [])
                    
                    error_message = "המסמך לא אושר. "
                    if errors:
                        error_message += " ".join(errors)
                    if warnings:
                        error_message += " " + " ".join(warnings)
                    
                    return {
                        "success": False,
                        "message": f"{error_message} אנא שלח שוב את {current_document}."
                    }
            else:
                return {
                    "success": False,
                    "message": "אנא שלח מסמך (תמונה או PDF)."
                }
                
        except Exception as e:
            logger.error("Error handling guarantor documents", extra={"error": str(e)})
            return {
                "success": False,
                "message": "מצטער, אירעה שגיאה. אנא נסה שוב."
            }
    
    async def _get_next_guarantor_document(self, current_document: str) -> Optional[str]:
        """Get the next document in the guarantor document sequence."""
        document_sequence = [
            "id_card",
            "sephach", 
            "payslips",
            "bank_statements"
        ]
        
        try:
            current_index = document_sequence.index(current_document)
            if current_index < len(document_sequence) - 1:
                return document_sequence[current_index + 1]
            return None
        except ValueError:
            return "id_card"  # Default to first document
    
    async def _get_guarantor_document_request_message(self, document_type: str) -> str:
        """Get the request message for a specific document type."""
        messages = {
            "id_card": "אנא שלח את תעודת הזהות שלך.",
            "sephach": "אנא שלח את הספח (Sephach).",
            "payslips": "אנא שלח את 3 תלושי המשכורת האחרונים.",
            "bank_statements": "אנא שלח את דוח הבנק של 3 החודשים האחרונים."
        }
        return messages.get(document_type, "אנא שלח את המסמך הבא.")
    
    
    async def _handle_guarantor_completed(self, guarantor: Dict[str, Any], message_type: str, content: Any) -> Dict[str, Any]:
        """Handle guarantor in completed state."""
        try:
            # Get tenant information
            from app.services.supabase_service import supabase_service
            tenant = await supabase_service.get_tenant_by_id(guarantor["tenant_id"])
            
            completion_message = f"""תודה רבה! כל המסמכים התקבלו ואושרו.

אתה ערב עבור {tenant['full_name']} ב-{tenant['property_name']}.

התהליך הושלם בהצלחה!"""
            
            await self.whatsapp_service.send_text_message(guarantor["phone_number"], completion_message)
            
            return {
                "success": True,
                "message": "Guarantor completion confirmed"
            }
            
        except Exception as e:
            logger.error("Error handling guarantor completed", extra={"error": str(e)})
            return {
                "success": False,
                "message": "Error sending completion message"
            }
    
    async def _parse_guarantor_personal_info(self, text: str) -> Optional[Dict[str, Any]]:
        """Parse personal information from text message."""
        try:
            # Use Vertex AI to parse personal information
            prompt = f"""Extract personal information from this Hebrew text:

Text: {text}

Extract and return as JSON:
{{
    "full_name": "Full name in Hebrew",
    "phone_number": "Phone number",
    "email": "Email address"
}}

Return ONLY the JSON object."""
            
            response = await self.vertex_ai_service.generate_response(prompt)
            
            # Parse response
            import json
            try:
                # Clean response
                cleaned_response = response.strip()
                if cleaned_response.startswith("```json"):
                    cleaned_response = cleaned_response[7:]
                if cleaned_response.endswith("```"):
                    cleaned_response = cleaned_response[:-3]
                
                personal_info = json.loads(cleaned_response)
                return personal_info
                
            except json.JSONDecodeError:
                logger.warning("Failed to parse personal info JSON", extra={"response": response})
                return None
                
        except Exception as e:
            logger.error("Error parsing guarantor personal info", extra={"error": str(e)})
            return None
    
    async def _update_guarantor_personal_info(self, guarantor_id: str, personal_info: Dict[str, Any]):
        """Update guarantor with personal information."""
        try:
            # Update guarantor record
            update_data = {}
            if personal_info.get("full_name"):
                update_data["full_name"] = personal_info["full_name"]
            if personal_info.get("email"):
                update_data["email"] = personal_info["email"]
            
            if update_data:
                from app.services.supabase_service import supabase_service
                result = supabase_service.table("guarantors").update(update_data).eq("id", guarantor_id).execute()
                logger.info("Guarantor personal info updated", extra={"guarantor_id": guarantor_id})
                
        except Exception as e:
            logger.error("Error updating guarantor personal info", extra={"error": str(e)})
    
    
    async def _detect_guarantor_document_type(self, content: Any) -> Optional[str]:
        """Detect guarantor document type."""
        try:
            # Use Vertex AI to detect document type
            prompt = f"""Analyze this document and determine its type.

Return one of these options:
- id_card
- sephach  
- payslips
- pnl
- bank_statements

Return ONLY the document type."""
            
            response = await self.vertex_ai_service.generate_response(prompt)
            document_type = response.strip().lower()
            
            if document_type in ["id_card", "sephach", "payslips", "pnl", "bank_statements"]:
                return document_type
            
            return None
            
        except Exception as e:
            logger.error("Error detecting guarantor document type", extra={"error": str(e)})
            return None
    
    async def _check_guarantor_document_completion(self, guarantor: Dict[str, Any]) -> Dict[str, Any]:
        """Check if guarantor has completed all required documents."""
        try:
            documents_status = guarantor.get("documents_status", {})
            required_docs = ["id_card", "sephach", "payslips", "pnl", "bank_statements"]
            
            completed_docs = []
            missing_docs = []
            
            for doc_type in required_docs:
                if documents_status.get(doc_type, {}).get("status") == "validated":
                    completed_docs.append(doc_type)
                else:
                    missing_docs.append(doc_type)
            
            all_completed = len(completed_docs) == len(required_docs)
            next_document = missing_docs[0] if missing_docs else None
            
            return {
                "all_completed": all_completed,
                "completed_docs": completed_docs,
                "missing_docs": missing_docs,
                "next_document": next_document
            }
            
        except Exception as e:
            logger.error("Error checking guarantor document completion", extra={"error": str(e)})
            return {
                "all_completed": False,
                "completed_docs": [],
                "missing_docs": ["id_card", "sephach", "payslips", "pnl", "bank_statements"],
                "next_document": "id_card"
            }
    
    async def _send_guarantor_completion_message(self, guarantor: Dict[str, Any]):
        """Send completion message to guarantor."""
        try:
            # Get tenant information
            from app.services.supabase_service import supabase_service
            tenant = await supabase_service.get_tenant_by_id(guarantor["tenant_id"])
            
            completion_message = f"""מעולה! כל המסמכים התקבלו ואושרו.

אתה ערב עבור {tenant['full_name']} ב-{tenant['property_name']}.

התהליך הושלם בהצלחה!"""
            
            await self.whatsapp_service.send_text_message(guarantor["phone_number"], completion_message)
            
            # Check if all guarantors are completed and notify tenant
            await self._check_all_guarantors_completed(tenant["id"])
            
        except Exception as e:
            logger.error("Error sending guarantor completion message", extra={"error": str(e)})
    
    async def _check_all_guarantors_completed(self, tenant_id: str):
        """Check if all guarantors are completed and notify tenant."""
        try:
            completion_status = await self.guarantor_service.check_guarantor_completion(tenant_id)
            
            if completion_status["all_completed"]:
                # Get tenant information
                from app.services.supabase_service import supabase_service
                tenant = await supabase_service.get_tenant_by_id(tenant_id)
                
                if tenant:
                    # Send completion notification to tenant
                    completion_message = f"""מעולה! כל הערבים סיימו לשלוח את המסמכים.

התהליך הושלם בהצלחה עבור {tenant['full_name']} ב-{tenant['property_name']}.

תודה שהצטרפת למשפחת מגורית!"""
                    
                    await self.whatsapp_service.send_text_message(tenant["phone_number"], completion_message)
                    
                    # Update tenant status
                    await supabase_service.update_tenant(tenant_id, {
                        "whatsapp_status": "completed"
                    })
                    
                    logger.info("All guarantors completed, tenant notified", extra={
                        "tenant_id": tenant_id,
                        "tenant_name": tenant["full_name"],
                        "completed_guarantors": completion_status["completed_count"],
                        "total_guarantors": completion_status["total_count"]
                    })
            
        except Exception as e:
            logger.error("Error checking guarantor completion", extra={"error": str(e)})


# Global instance
guarantor_conversation_service = GuarantorConversationService()
