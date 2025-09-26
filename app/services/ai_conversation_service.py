"""
AI Conversation Service

This service handles AI-generated responses for both tenant and guarantor conversations.
It provides natural, human-like responses while maintaining conversation flow logic.
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
import json

from app.services.vertex_ai_service import vertex_ai_service
from app.services.supabase_service import supabase_service

logger = logging.getLogger(__name__)


class AIConversationService:
    """Service for generating AI-powered conversation responses."""
    
    def __init__(self):
        self.vertex_ai_service = vertex_ai_service
        self.supabase_service = supabase_service
    
    async def generate_response(self, phone_number: str, user_message: str, 
                              conversation_type: str, current_state: str, 
                              context_data: Dict[str, Any]) -> str:
        """
        Generate AI response for both tenants and guarantors.
        
        Args:
            phone_number: User's phone number
            user_message: User's message
            conversation_type: 'tenant' or 'guarantor'
            current_state: Current conversation state
            context_data: Context data from conversation state
            
        Returns:
            AI-generated response in Hebrew
        """
        try:
            logger.info("Generating AI response", extra={
                "phone_number": phone_number,
                "conversation_type": conversation_type,
                "current_state": current_state,
                "context_data": context_data
            })
            
            # Get conversation history with token limit
            history = await self._get_conversation_history_with_token_limit(phone_number, conversation_type)
            
            # Get personality data
            personality = await self._get_conversation_personality(phone_number, conversation_type)
            
            # Build AI prompt
            prompt = await self._build_ai_prompt(
                conversation_type=conversation_type,
                current_state=current_state,
                context_data=context_data,
                conversation_history=history,
                personality=personality,
                user_message=user_message
            )
            
            # Generate response using Vertex AI
            ai_response = await self.vertex_ai_service.generate_ai_response(prompt)
            
            # Store the AI response in conversation history
            await self._store_message_history(
                phone_number, conversation_type, "bot_response", ai_response, current_state, context_data
            )
            
            logger.info("AI response generated successfully", extra={
                "phone_number": phone_number,
                "response_length": len(ai_response)
            })
            
            return ai_response
            
        except Exception as e:
            logger.error("Error generating AI response", extra={
                "phone_number": phone_number,
                "conversation_type": conversation_type,
                "error": str(e)
            })
            # Fallback to default response
            return await self._get_fallback_response(conversation_type, current_state)
    
    async def _get_conversation_history(self, phone_number: str, conversation_type: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Get conversation history for AI context."""
        try:
            # Use the database function to get conversation history
            result = self.supabase_service.client.rpc(
                'get_conversation_history_for_ai',
                {
                    'p_phone_number': phone_number,
                    'p_conversation_type': conversation_type,
                    'p_limit': limit
                }
            ).execute()
            
            if result.data:
                return result.data
            return []
            
        except Exception as e:
            logger.error("Error getting conversation history", extra={
                "phone_number": phone_number,
                "conversation_type": conversation_type,
                "error": str(e)
            })
            return []
    
    async def _get_conversation_history_with_token_limit(self, phone_number: str, conversation_type: str, max_tokens: int = 50000) -> List[Dict[str, Any]]:
        """Get conversation history with token limit to prevent AI overload."""
        try:
            # Start with a small limit and increase if needed
            limit = 3
            total_tokens = 0
            history = []
            
            while limit <= 10 and total_tokens < max_tokens:
                result = self.supabase_service.client.rpc(
                    'get_conversation_history_for_ai',
                    {
                        'p_phone_number': phone_number,
                        'p_conversation_type': conversation_type,
                        'p_limit': limit
                    }
                ).execute()
                
                if not result.data:
                    break
                
                # Calculate approximate token count (rough estimate: 1 token ≈ 4 characters)
                new_history = result.data
                new_tokens = sum(len(str(msg.get('message_content', ''))) * 0.25 for msg in new_history)
                
                if total_tokens + new_tokens > max_tokens:
                    break
                
                history = new_history
                total_tokens += new_tokens
                limit += 2
            
            logger.info("Conversation history retrieved", extra={
                "phone_number": phone_number,
                "conversation_type": conversation_type,
                "message_count": len(history),
                "estimated_tokens": total_tokens
            })
            
            return history
            
        except Exception as e:
            logger.error("Error getting conversation history with token limit", extra={
                "phone_number": phone_number,
                "conversation_type": conversation_type,
                "error": str(e)
            })
            return []
    
    async def _get_conversation_personality(self, phone_number: str, conversation_type: str) -> Dict[str, Any]:
        """Get conversation personality data."""
        try:
            if conversation_type == "tenant":
                conversation_state = await self.supabase_service.get_conversation_state(phone_number)
                if conversation_state:
                    return conversation_state.conversation_personality or {}
            elif conversation_type == "guarantor":
                conversation_state = await self.supabase_service.get_guarantor_conversation_state(phone_number)
                if conversation_state:
                    return conversation_state.get("conversation_personality", {})
            
            return {}
            
        except Exception as e:
            logger.error("Error getting conversation personality", extra={
                "phone_number": phone_number,
                "conversation_type": conversation_type,
                "error": str(e)
            })
            return {}
    
    async def _build_ai_prompt(self, conversation_type: str, current_state: str, 
                             context_data: Dict[str, Any], conversation_history: List[Dict], 
                             personality: Dict[str, Any], user_message: str) -> str:
        """Build AI prompt based on conversation type."""
        
        if conversation_type == "tenant":
            return await self._build_tenant_prompt(current_state, context_data, conversation_history, personality, user_message)
        elif conversation_type == "guarantor":
            return await self._build_guarantor_prompt(current_state, context_data, conversation_history, personality, user_message)
        else:
            raise ValueError(f"Unknown conversation type: {conversation_type}")
    
    async def _build_tenant_prompt(self, current_state: str, context_data: Dict[str, Any], 
                                 conversation_history: List[Dict], personality: Dict[str, Any], 
                                 user_message: str) -> str:
        """Build AI prompt for tenant conversations."""
        
        # Format conversation history
        history_text = self._format_conversation_history(conversation_history)
        
        # Get tenant context
        tenant_name = context_data.get('tenant_name', 'הדייר')
        property_name = context_data.get('property_name', 'הנכס')
        apartment_number = context_data.get('apartment_number', '')
        
        # Get personality traits
        formality_level = personality.get('formality_level', 'professional_friendly')
        response_style = personality.get('response_style', 'helpful')
        
        # Get current task description
        current_task = self._get_tenant_task_description(current_state, context_data)
        
        prompt = f"""
אתה יוני ממגורית, עוזר נדלן ידידותי שמסייע לדיירים.

הקשר:
- דייר: {tenant_name}
- נכס: {property_name}
- דירה: {apartment_number}
- מצב: {current_state}

היסטוריה:
{history_text}

משימה: {current_task}

הודעה: {user_message}

הוראות:
- השב בעברית טבעית, כאילו אתה מדבר עם חבר
- אל תחזור על מה שהמשתמש אמר
- אל תציג את עצמך שוב
- השתמש בשמות אמיתיים
- היה ישיר ומועיל
- שמור על טון חם אבל לא רשמי
- אל תחזור על מידע שכבר נאמר
"""
        
        return prompt
    
    async def _build_guarantor_prompt(self, current_state: str, context_data: Dict[str, Any], 
                                    conversation_history: List[Dict], personality: Dict[str, Any], 
                                    user_message: str) -> str:
        """Build AI prompt for guarantor conversations."""
        
        # Format conversation history
        history_text = self._format_conversation_history(conversation_history)
        
        # Get guarantor context
        guarantor_name = context_data.get('guarantor_name', 'הערב')
        tenant_name = context_data.get('tenant_name', 'הדייר')
        property_name = context_data.get('property_name', 'הנכס')
        current_document = context_data.get('current_document', 'תעודת זהות')
        collected_documents = context_data.get('collected_documents', [])
        pending_documents = context_data.get('pending_documents', [])
        document_status = context_data.get('document_status', {})
        
        # Get personality traits
        formality_level = personality.get('formality_level', 'professional_friendly')
        response_style = personality.get('response_style', 'helpful')
        
        # Get current task description
        current_task = self._get_guarantor_task_description(current_state, context_data)
        
        # Format document status information
        status_info = ""
        if collected_documents:
            status_info += f"\nמסמכים שכבר התקבלו ואושרו: {', '.join(collected_documents)}"
        if pending_documents:
            status_info += f"\nמסמכים שנותרו: {', '.join(pending_documents)}"
        
        # Add explicit instruction about not asking for already collected documents
        if collected_documents:
            status_info += f"\nחשוב: אל תבקש מסמכים שכבר התקבלו ואושרו! המסמכים הבאים כבר אושרו: {', '.join(collected_documents)}"
        
        # Check if a document was just approved
        document_just_approved = context_data.get('document_just_approved', False)
        next_document = context_data.get('next_document', '')
        print(f"DEBUG AI: document_just_approved={document_just_approved}, next_document={next_document}")
        if document_just_approved and next_document:
            # Map document types to Hebrew names
            document_names = {
                "id_card": "תעודת הזהות",
                "sephach": "הספח",
                "payslips": "תלושי המשכורת",
                "bank_statements": "דוח הבנק",
                "pnl": "דוח רווח והפסד"
            }
            next_document_name = document_names.get(next_document, next_document)
            status_info += f"\nחשוב: מסמך {current_document} זה עתה אושר! עכשיו בקש את {next_document_name}."
            print(f"DEBUG AI: Added status_info: {status_info}")
        
        # Check if a document was just rejected
        document_just_rejected = context_data.get('document_just_rejected', False)
        rejection_reason = context_data.get('rejection_reason', '')
        current_document = context_data.get('current_document', 'id_card')
        print(f"DEBUG AI: document_just_rejected={document_just_rejected}, rejection_reason={rejection_reason}, current_document={current_document}")
        if document_just_rejected:
            # Extract the actual document type from the rejection reason
            # Format: "המסמך לא אושר. ... אנא שלח שוב את payslips."
            rejected_document_type = "unknown"
            if "אנא שלח שוב את" in rejection_reason:
                parts = rejection_reason.split("אנא שלח שוב את ")
                if len(parts) > 1:
                    rejected_document_type = parts[1].split(".")[0].strip()
            elif "אנא שלח מסמך" in rejection_reason:
                # This is the generic message when no document was sent
                # Use the current document from context
                rejected_document_type = current_document
                print(f"DEBUG AI: Using current_document as rejected_document_type: {rejected_document_type}")
            
            # Map document types to Hebrew names
            document_names = {
                "id_card": "תעודת הזהות",
                "sephach": "הספח", 
                "payslips": "תלושי המשכורת",
                "bank_statements": "דוח הבנק",
                "pnl": "דוח רווח והפסד"
            }
            rejected_document_name = document_names.get(rejected_document_type, rejected_document_type)
            
            # Include specific validation errors in the status info
            if rejected_document_type != "unknown":
                # Extract specific errors from rejection reason
                specific_errors = rejection_reason.replace("המסמך לא אושר. ", "").replace(f" אנא שלח שוב את {rejected_document_type}.", "")
                if specific_errors.strip():
                    status_info += f"\nחשוב: המסמך {rejected_document_name} נדחה! הסיבות: {specific_errors.strip()}. בקש את אותו מסמך שוב עם המידע הנכון."
                else:
                    status_info += f"\nחשוב: המסמך {rejected_document_name} נדחה! בקש את אותו מסמך שוב עם המידע הנכון."
            else:
                status_info += f"\nחשוב: המסמך {rejected_document_name} נדחה! בקש את אותו מסמך שוב עם המידע הנכון."
            print(f"DEBUG AI: Added rejection status_info: {status_info}")
        
        # Add specific validation errors to the prompt if available
        validation_errors = ""
        if document_just_rejected and rejection_reason:
            # Extract validation errors from rejection reason
            if "המסמך לא אושר." in rejection_reason:
                error_part = rejection_reason.split("המסמך לא אושר. ")[1]
                if "אנא שלח שוב את" in error_part:
                    error_part = error_part.split("אנא שלח שוב את")[0].strip()
                if error_part:
                    validation_errors = f"\n\nפרטי השגיאות: {error_part}"
                    print(f"DEBUG AI: Extracted validation errors: {error_part}")

        prompt = f"""
אתה יוני ממגורית, עוזר נדלן שמסייע לערבים.

הקשר:
- ערב: {guarantor_name}
- דייר: {tenant_name}
- נכס: {property_name}
- מסמך נוכחי: {current_document}
- מצב: {current_state}
{status_info}

היסטוריה:
{history_text}

משימה: {current_task}

הודעה: {user_message}

הוראות חשובות:
- השב בעברית טבעית, כאילו אתה מדבר עם חבר
- אל תחזור על מה שהמשתמש אמר
- אל תציג את עצמך שוב
- השתמש בשמות אמיתיים
- היה ישיר ומועיל
- שמור על טון חם אבל לא רשמי
- אל תחזור על מידע שכבר נאמר
- היה מודע למצב הנוכחי של המסמכים
- אל תתחיל הודעות עם "היי" או "שלום" - רק בפעם הראשונה

חשוב מאוד - סדר המסמכים:
- בקש רק את המסמך הנוכחי: {current_document}
- אל תציע מסמכים אחרים
- אל תדלג על מסמכים
- אם המשתמש שולח מסמך אחר, הסבר שצריך את המסמך הנוכחי קודם
- שמור על הסדר המדויק של המסמכים

חשוב מאוד - אל תבקש מסמכים שכבר אושרו:
- אם תעודת זהות כבר אושרה, אל תבקש אותה שוב
- אם ספח כבר אושר, אל תבקש אותו שוב
- בקש רק את המסמך הבא בסדר
- אם כל המסמכים אושרו, הודע שהתהליך הושלם

חשוב מאוד - זה ערב, לא דייר:
- אתה מדבר עם {guarantor_name} שהוא ערב עבור {tenant_name}
- בקש מהערב את המסמכים שלו, לא של הדייר
- אל תבקש מהערב לשלוח מסמכים של הדייר
- הערב צריך לשלוח את המסמכים שלו עצמו
{validation_errors}
"""
        
        return prompt
    
    def _format_conversation_history(self, history: List[Dict[str, Any]]) -> str:
        """Format conversation history for AI context."""
        if not history:
            return "אין היסטוריית שיחה קודמת."
        
        formatted_history = []
        for entry in reversed(history):  # Reverse to show chronological order
            message_type = "משתמש" if entry.get('message_type') == 'user' else "בוט"
            content = entry.get('message_content', '')
            timestamp = entry.get('timestamp', '')
            
            formatted_history.append(f"{message_type}: {content}")
        
        return "\n".join(formatted_history)
    
    def _get_tenant_task_description(self, current_state: str, context_data: Dict[str, Any]) -> str:
        """Get task description for tenant conversations."""
        task_descriptions = {
            "GREETING": "ברכה לדייר החדש והצגת התהליך",
            "CONFIRMATION": "אישור פרטי הנכס והדייר",
            "PERSONAL_INFO": "איסוף מידע אישי (עיסוק, מצב משפחתי, מספר ילדים)",
            "DOCUMENTS": "איסוף מסמכים נדרשים (תעודת זהות, ספח, תלושי שכר, דוחות בנק)",
            "GUARANTOR_1": "איסוף פרטי ערב ראשון",
            "GUARANTOR_2": "איסוף פרטי ערב שני",
            "COMPLETED": "סיום התהליך ואישור קבלה"
        }
        
        return task_descriptions.get(current_state, "משימה לא מוגדרת")
    
    def _get_guarantor_task_description(self, current_state: str, context_data: Dict[str, Any]) -> str:
        """Get task description for guarantor conversations."""
        current_document = context_data.get('current_document', 'מסמך')
        
        # Define the complete document list in order
        document_list = [
            "תעודת זהות",
            "ספח תעודת זהות", 
            "תלושי שכר (3 חודשים אחרונים)",
            "דוח בנק (3 חודשים אחרונים)",
            "אישור הכנסה"
        ]
        
        task_descriptions = {
            "GREETING": "ברכה לערב והצגת התהליך",
            "DOCUMENTS": f"איסוף {current_document} - רק המסמך הנוכחי, לא אחר",
            "COMPLETED": "סיום איסוף המסמכים"
        }
        
        base_task = task_descriptions.get(current_state, "משימה לא מוגדרת")
        
        if current_state == "DOCUMENTS":
            return f"{base_task}\n\nרשימת מסמכים נדרשים (בסדר):\n" + "\n".join([f"{i+1}. {doc}" for i, doc in enumerate(document_list)])
        
        return base_task
    
    async def _store_message_history(self, phone_number: str, conversation_type: str, 
                                   message_type: str, content: str, state: str, 
                                   context_data: Dict[str, Any] = None):
        """Store message in conversation history."""
        try:
            history_data = {
                "phone_number": phone_number,
                "conversation_type": conversation_type,
                "message_type": message_type,
                "message_content": content,
                "conversation_state": state,
                "context_data": context_data or {},
                "message_timestamp": datetime.now().isoformat()
            }
            
            self.supabase_service.client.table("conversation_history").insert(history_data).execute()
            
        except Exception as e:
            logger.error("Error storing message history", extra={
                "phone_number": phone_number,
                "conversation_type": conversation_type,
                "error": str(e)
            })
    
    async def _get_fallback_response(self, conversation_type: str, current_state: str) -> str:
        """Get fallback response when AI fails."""
        fallback_responses = {
            "tenant": {
                "GREETING": "שלום! אני יוני ממגורית. איך אני יכול לעזור לך היום?",
                "CONFIRMATION": "אנא אשר את הפרטים שצוינו.",
                "PERSONAL_INFO": "אנא שלח את המידע הנדרש.",
                "DOCUMENTS": "אנא שלח את המסמכים הנדרשים.",
                "GUARANTOR_1": "אנא שלח את פרטי הערב הראשון.",
                "GUARANTOR_2": "אנא שלח את פרטי הערב השני.",
                "COMPLETED": "תודה! התהליך הושלם בהצלחה."
            },
            "guarantor": {
                "GREETING": "שלום! אני יוני ממגורית. איך אני יכול לעזור לך היום?",
                "DOCUMENTS": "אנא שלח את המסמכים הנדרשים.",
                "COMPLETED": "תודה! התהליך הושלם בהצלחה."
            }
        }
        
        return fallback_responses.get(conversation_type, {}).get(current_state, "אני כאן לעזור לך. איך אני יכול לסייע?")
    
    async def update_conversation_personality(self, phone_number: str, conversation_type: str, 
                                            personality_data: Dict[str, Any]) -> bool:
        """Update conversation personality based on user interactions."""
        try:
            # Use the database function to update personality
            result = self.supabase_service.client.rpc(
                'update_conversation_personality',
                {
                    'p_phone_number': phone_number,
                    'p_conversation_type': conversation_type,
                    'p_personality_data': personality_data
                }
            ).execute()
            
            return True
            
        except Exception as e:
            logger.error("Error updating conversation personality", extra={
                "phone_number": phone_number,
                "conversation_type": conversation_type,
                "error": str(e)
            })
            return False


# Global instance
ai_conversation_service = AIConversationService()
