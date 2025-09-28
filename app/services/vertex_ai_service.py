import logging
import structlog
import asyncio
import os
import tempfile
import json
from typing import Dict, Any, Optional, List
from datetime import datetime
from google import genai
from google.genai.types import HttpOptions
from flask import current_app

logger = structlog.get_logger(__name__)


class VertexAIService:
    def __init__(self):
        self.client: Optional[genai.Client] = None
        self.project_id: Optional[str] = None
        self.location: str = "us-central1"  # Default location
        self._initialized = False

    def _ensure_initialized(self):
        """Ensure the service is initialized with Flask app context."""
        if not self._initialized:
            try:
                self.project_id = current_app.config.get("VERTEX_AI_PROJECT")
                if not self.project_id:
                    raise ValueError("VERTEX_AI_PROJECT not configured")
                
                # Set up authentication and environment variables
                credentials_path = current_app.config.get("GOOGLE_APPLICATION_CREDENTIALS")
                
                if credentials_path:
                    # Check if it's a file path or JSON content
                    if credentials_path.startswith('{'):
                        # It's JSON content, create temporary file
                        credentials_data = json.loads(credentials_path)
                        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                            json.dump(credentials_data, f)
                            credentials_path = f.name
                    
                    # Set environment variable for Google Cloud libraries
                    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = credentials_path
                
                # Set required environment variables for Google Gen AI SDK
                os.environ['GOOGLE_CLOUD_PROJECT'] = self.project_id
                os.environ['GOOGLE_CLOUD_LOCATION'] = self.location
                os.environ['GOOGLE_GENAI_USE_VERTEXAI'] = 'True'
                
                # Initialize the client using Google Gen AI SDK
                self.client = genai.Client(http_options=HttpOptions(api_version="v1"))
                
                self._initialized = True
                logger.info("Vertex AI client initialized successfully", project_id=self.project_id)
            except Exception as e:
                logger.error("Failed to initialize Vertex AI client", error=str(e))
                raise

    async def validate_human_response(self, question: str, response: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Use Vertex AI to validate if response is human and relevant.
        
        Args:
            question: The question that was asked
            response: The user's response
            context: Additional context about the conversation
            
        Returns:
            Dict containing validation results
        """
        self._ensure_initialized()
        try:
            # Create a prompt for validation
            prompt = self._create_validation_prompt(question, response, context)
            
            # Call Vertex AI model
            validation_result = await self._call_vertex_ai_model(prompt)
            
            return validation_result
            
        except Exception as e:
            logger.error("Error validating human response", error=str(e))
            return {
                "is_valid": False,
                "feedback": "Sorry, I couldn't process your response. Please try again.",
                "parsed_data": {},
                "confidence": 0.0
            }

    def _create_validation_prompt(self, question: str, response: str, context: Dict[str, Any]) -> str:
        """Create a SMART validation prompt that handles all field types correctly."""
        
        # Get current field from context to customize validation
        current_field = context.get('current_field', 'unknown')
        
        if current_field == 'occupation' or 'עיסוק' in question or 'מקצוע' in question:
            prompt = f"""
            You are validating an occupation/job response. RESPOND WITH ONLY VALID JSON.
        
        USER RESPONSE: "{response}"
        
        RULES:
        - Any meaningful work description = valid
        - "software engineer", "מהנדס תוכנה", "I work in corporate" = valid
        - Empty or nonsense = invalid
        
        RESPOND WITH ONLY THIS JSON:
        {{
            "is_valid": true,
            "feedback": "תודה על המידע על העיסוק",
            "parsed_data": {{
                "occupation": "{response.strip()}"
            }},
            "confidence": 0.9
        }}
        
        Replace is_valid with false if response is meaningless.
        """
        
        elif current_field == 'family_status' or 'משפחתי' in question:
            prompt = f"""
        You are validating a family status response. RESPOND WITH ONLY VALID JSON.

        USER RESPONSE: "{response}"
        
        RULES:
        - "single", "married", "divorced", "רווק", "נשוי", "גרוש" = valid
        - Convert to Hebrew: single→רווק, married→נשוי, divorced→גרוש
        
        RESPOND WITH ONLY THIS JSON:
        {{
            "is_valid": true,
            "feedback": "תודה על המידע על המצב המשפחתי",
            "parsed_data": {{
                "family_status": "גרוש"
            }},
            "confidence": 0.9
        }}
        
        Replace family_status value based on the response.
        """
        
        elif current_field == 'number_of_children' or 'ילדים' in question:
            prompt = f"""
        You are validating number of children response. RESPOND WITH ONLY VALID JSON.
        
        USER RESPONSE: "{response}"
        
        RULES:
        - Numbers (0,1,2,3...) = valid
        - "none", "אין", "ללא" = 0
        - Extract number from text
        
        RESPOND WITH ONLY THIS JSON:
        {{
            "is_valid": true,
            "feedback": "תודה על המידע על הילדים",
            "parsed_data": {{
                "number_of_children": 0
            }},
            "confidence": 0.9
        }}
        
        Replace number_of_children with the actual number.
        """
        
        else:
            # Confirmation or other fields
            prompt = f"""
        You are validating a confirmation response. RESPOND WITH ONLY VALID JSON.

        QUESTION: "{question}"
        USER RESPONSE: "{response}"
        
        RULES:
        1. If user says "yes", "כן", "נכון", "correct", "right", "ok" → confirmed: true
        2. If user says "no", "לא", "wrong", "incorrect" → confirmed: false
        3. If unclear → confirmed: null
        
        RESPOND WITH ONLY THIS JSON:
        {{
            "is_valid": true,
            "feedback": "תודה על התגובה",
            "parsed_data": {{
                "confirmed": true
            }},
            "confidence": 0.9
        }}
        
        Replace confirmed value based on user response.
        """
        
        return prompt

    def _extract_json_from_response(self, response_text: str) -> str:
        """Extract JSON from response text, handling markdown code blocks."""
        import re
        
        # Remove markdown code blocks if present
        if "```json" in response_text:
            # Extract content between ```json and ```
            match = re.search(r'```json\s*(.*?)\s*```', response_text, re.DOTALL)
            if match:
                return match.group(1).strip()
        elif "```" in response_text:
            # Extract content between ``` and ```
            match = re.search(r'```\s*(.*?)\s*```', response_text, re.DOTALL)
            if match:
                return match.group(1).strip()
        
        # If no code blocks, try to find JSON object
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            return json_match.group(0).strip()
        
        # Return original text if no patterns found
        return response_text.strip()

    async def _call_vertex_ai_model(self, prompt: str) -> Dict[str, Any]:
        """Call Vertex AI model with the prompt."""
        try:
            # Use the Google Gen AI SDK to generate content
            response = self.client.models.generate_content(
                model="gemini-2.0-flash-exp",
                contents=prompt,
                config={
                    "temperature": 0.1,
                    "max_output_tokens": 500,
                    "top_p": 0.8,
                    "top_k": 40
                }
            )
            
            if response.text:
                response_text = response.text
                logger.info("Vertex AI response received", response=response_text)
                
                # Parse the response - handle markdown code blocks
                try:
                    # Clean the response text to extract JSON
                    cleaned_response = self._extract_json_from_response(response_text)
                    result = json.loads(cleaned_response)
                    logger.info("Vertex AI response parsed successfully", result=result)
                    
                    # SMART CHECK: Only trigger fallback if parsed_data is truly empty or invalid
                    parsed_data = result.get("parsed_data", {})
                    if not parsed_data or (len(parsed_data) == 1 and "confirmed" in parsed_data and parsed_data.get("confirmed") is None):
                        logger.warning("Vertex AI returned empty/null parsed_data, using rule-based fallback")
                        return await self._validate_response_rules_fallback(prompt)
                    
                    return result
                except json.JSONDecodeError as e:
                    logger.error("Failed to parse Vertex AI response as JSON", response=response_text, error=str(e))
                    return await self._validate_response_rules_fallback(prompt)
            else:
                logger.error("No predictions from Vertex AI")
                return await self._validate_response_rules_fallback(prompt)
                
        except Exception as e:
            logger.error("Error calling Vertex AI model", error=str(e))
            return await self._validate_response_rules_fallback(prompt)

    async def _validate_response_rules_fallback(self, prompt: str) -> Dict[str, Any]:
        """ENHANCED rule-based fallback that handles all field types smartly."""
        try:
            import re
            
            # Extract the user response from the prompt
            response_match = re.search(r'USER RESPONSE: "([^"]*)"', prompt)
            if not response_match:
                return {
                    "is_valid": False,
                    "feedback": "לא הצלחתי להבין את התגובה. אנא נסה שוב.",
                    "parsed_data": {},
                    "confidence": 0.0
                }
            
            response = response_match.group(1).strip()
            response_lower = response.lower()
            
            # SMART FIELD DETECTION - Check what type of validation this is
            if "occupation" in prompt or "עיסוק" in prompt:
                # OCCUPATION FIELD
                if len(response) >= 3:
                    return {
                        "is_valid": True,
                        "feedback": "תודה על המידע על העיסוק",
                        "parsed_data": {"occupation": response},
                        "confidence": 0.9
                    }
                else:
                    return {
                        "is_valid": False,
                        "feedback": "אנא ספר לי על העיסוק שלך",
                        "parsed_data": {},
                        "confidence": 0.1
                    }
            
            elif "family_status" in prompt or "משפחתי" in prompt:
                # FAMILY STATUS FIELD
                status_map = {
                    "single": "רווק", "married": "נשוי", "divorced": "גרוש", 
                    "רווק": "רווק", "נשוי": "נשוי", "גרוש": "גרוש", "אלמן": "אלמן"
                }
                
                for key, value in status_map.items():
                    if key in response_lower:
                        return {
                            "is_valid": True,
                            "feedback": "תודה על המידע על המצב המשפחתי",
                            "parsed_data": {"family_status": value},
                            "confidence": 0.9
                        }
                
                # If no exact match, accept as-is
                return {
                    "is_valid": True,
                    "feedback": "תודה על המידע על המצב המשפחתי",
                    "parsed_data": {"family_status": response},
                    "confidence": 0.8
                }
            
            elif "number_of_children" in prompt or "ילדים" in prompt:
                # CHILDREN COUNT FIELD
                numbers = re.findall(r'\d+', response)
                if numbers:
                    return {
                        "is_valid": True,
                        "feedback": "תודה על המידע על הילדים",
                        "parsed_data": {"number_of_children": int(numbers[0])},
                        "confidence": 0.9
                    }
                elif any(word in response_lower for word in ["אין", "ללא", "none", "zero"]):
                    return {
                        "is_valid": True,
                        "feedback": "תודה על המידע",
                        "parsed_data": {"number_of_children": 0},
                        "confidence": 0.9
                    }
                else:
                    return {
                        "is_valid": False,
                        "feedback": "כמה ילדים יש לך? אנא ענה במספר",
                        "parsed_data": {},
                        "confidence": 0.1
                    }
            
            else:
                # CONFIRMATION FIELD (default)
                confirmation_words = [
                    "yes", "yeah", "yep", "sure", "ok", "alright", "correct", "right", "perfect", 
                    "sounds good", "that's correct", "i confirm", "confirmed", "agreed", "looks good",
                    "כן", "נכון", "אישור", "בסדר", "טוב", "מושלם", "נשמע טוב", "זה נכון", "אני מאשר"
                ]
                
                rejection_words = [
                    "no", "nope", "not", "wrong", "incorrect", "not right", "not correct", "change",
                    "לא", "לא נכון", "שגוי", "לא מדויק", "לשנות", "לעדכן"
                ]
                
                if any(word in response_lower for word in confirmation_words):
                    return {
                        "is_valid": True,
                        "feedback": "תודה על האישור",
                        "parsed_data": {"confirmed": True},
                        "confidence": 0.9
                    }
                elif any(word in response_lower for word in rejection_words):
                    return {
                        "is_valid": True,
                        "feedback": "הבנתי, מה צריך לשנות?",
                        "parsed_data": {"confirmed": False},
                        "confidence": 0.9
                    }
                else:
                    # SMART FALLBACK: If we don't understand, try to be helpful instead of failing
                    return {
                        "is_valid": True,
                        "feedback": "תודה על התגובה. אמשיך הלאה.",
                        "parsed_data": {"extracted_info": f"user said: {response}"},
                        "confidence": 0.7
                    }
                
        except Exception as e:
            logger.error("Error in enhanced rule-based fallback", error=str(e))
            return {
                "is_valid": True,
                "feedback": "תודה על התגובה. אמשיך הלאה.",
                "parsed_data": {"extracted_info": "general response"},
                "confidence": 0.5
            }

    async def _validate_response_rules(self, question: str, response: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Rule-based validation as fallback when Vertex AI is not available."""
        try:
            response_lower = response.lower().strip()
            
            # Check for obvious spam/bot responses
            spam_indicators = [
                "http://", "https://", "www.", ".com", ".co.il",
                "click here", "free money", "win now",
                "spam", "bot", "automated"
            ]
            
            is_spam = any(indicator in response_lower for indicator in spam_indicators)
            
            # Check response length
            is_too_short = len(response.strip()) < 2
            is_too_long = len(response.strip()) > 1000
            
            # Check for Hebrew or English content
            has_hebrew = any('\u0590' <= char <= '\u05FF' for char in response)
            has_english = any(char.isalpha() and ord(char) < 128 for char in response)
            has_language = has_hebrew or has_english
            
            # Determine if valid
            is_valid = not is_spam and not is_too_short and not is_too_long and has_language
            
            # Generate feedback
            feedback = ""
            if is_spam:
                feedback = "אנא שלח תגובה תקינה ללא קישורים או הודעות זבל."
            elif is_too_short:
                feedback = "אנא שלח תגובה מלאה יותר."
            elif is_too_long:
                feedback = "אנא שלח תגובה קצרה יותר."
            elif not has_language:
                feedback = "אנא שלח תגובה בעברית או באנגלית."
            else:
                feedback = "תודה על התגובה."
            
            # Parse data based on question type
            parsed_data = await self._parse_response_data(question, response, context)
            
            return {
                "is_valid": is_valid,
                "feedback": feedback,
                "parsed_data": parsed_data,
                "confidence": 0.8 if is_valid else 0.2
            }
            
        except Exception as e:
            logger.error("Error in rule-based validation", error=str(e))
            return {
                "is_valid": False,
                "feedback": "שגיאה בעיבוד התגובה. אנא נסה שוב.",
                "parsed_data": {},
                "confidence": 0.0
            }

    async def _parse_response_data(self, question: str, response: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Parse specific data from responses based on question type."""
        try:
            parsed_data = {}
            response_lower = response.lower().strip()
            
            # Parse confirmation responses
            if "confirm" in question.lower() or "אישור" in question:
                if any(word in response_lower for word in ["yes", "כן", "confirm", "אישור", "נכון", "correct"]):
                    parsed_data["confirmed"] = True
                elif any(word in response_lower for word in ["no", "לא", "incorrect", "לא נכון"]):
                    parsed_data["confirmed"] = False
                else:
                    parsed_data["needs_clarification"] = True
            
            # Parse occupation responses
            elif "occupation" in question.lower() or "עיסוק" in question or "מקצוע" in question:
                parsed_data["occupation"] = response.strip()
            
            # Parse family status responses
            elif "family" in question.lower() or "משפחה" in question or "מצב משפחתי" in question:
                family_statuses = {
                    "single": ["רווק", "רווקה", "single", "לא נשוי", "לא נשואה"],
                    "married": ["נשוי", "נשואה", "married", "נשואים"],
                    "divorced": ["גרוש", "גרושה", "divorced"],
                    "widowed": ["אלמן", "אלמנה", "widowed"]
                }
                
                for status, keywords in family_statuses.items():
                    if any(keyword in response_lower for keyword in keywords):
                        parsed_data["family_status"] = status
                        break
                
                if "family_status" not in parsed_data:
                    parsed_data["family_status"] = response.strip()
            
            # Parse number of children
            elif "children" in question.lower() or "ילדים" in question or "number_of_children" in question.lower():
                import re
                numbers = re.findall(r'\d+', response)
                if numbers:
                    parsed_data["number_of_children"] = int(numbers[0])
                elif any(word in response_lower for word in ["none", "אין", "אפס", "zero"]):
                    parsed_data["number_of_children"] = 0
                else:
                    parsed_data["number_of_children"] = None
            
            # Parse guarantor information
            elif "guarantor" in question.lower() or "ערב" in question:
                # Extract name and phone from response
                import re
                phone_pattern = r'(\+?972\d{9}|\d{10}|\d{9})'
                phone_match = re.search(phone_pattern, response)
                if phone_match:
                    parsed_data["phone"] = phone_match.group(1)
                
                # Extract name (everything except phone)
                name_text = re.sub(phone_pattern, '', response).strip()
                if name_text:
                    parsed_data["name"] = name_text
            
            # Parse document upload responses
            elif "document" in question.lower() or "מסמך" in question:
                if any(word in response_lower for word in ["sent", "שלחתי", "נשלח", "uploaded", "הועלה"]):
                    parsed_data["document_uploaded"] = True
                else:
                    parsed_data["document_uploaded"] = False
            
            return parsed_data
            
        except Exception as e:
            logger.error("Error parsing response data", error=str(e))
            return {}

    async def generate_ai_response(self, prompt: str) -> str:
        """
        Generate AI response using Vertex AI.
        
        Args:
            prompt: The prompt to send to the AI model
            
        Returns:
            Generated response in Hebrew
        """
        try:
            self._ensure_initialized()
            
            if not self.client:
                raise Exception("Vertex AI client not initialized")
            
            # Generate response using the correct Vertex AI format
            response = self.client.models.generate_content(
                model="gemini-2.0-flash-exp",
                contents=prompt,
                config={
                    "temperature": 0.7,
                    "max_output_tokens": 1024,
                    "top_p": 0.8,
                    "top_k": 40
                }
            )
            
            if response and response.text:
                formatted_response = self._format_ai_response_for_whatsapp(response.text.strip())
                return formatted_response
            else:
                logger.warning("Empty response from Vertex AI")
                return "מצטער, לא הצלחתי לייצר תגובה 😅\n\nאנא נסה שוב."
                
        except Exception as e:
            logger.error("Error generating AI response", error=str(e))
            return "מצטער, אירעה שגיאה 😔\n\nאנא נסה שוב."

    def _format_ai_response_for_whatsapp(self, response_text: str) -> str:
        """
        Format AI response for WhatsApp with proper line breaks and emoji limits.
        
        Args:
            response_text: Raw AI response text
            
        Returns:
            Formatted response with proper WhatsApp formatting
        """
        try:
            # Remove any unwanted AI artifacts
            response_text = response_text.replace("***", "*")  # Convert triple asterisks to single
            response_text = response_text.replace("בוט", "").replace("AI", "").replace("מערכת", "")
            
            # Fix WhatsApp bold formatting - remove ** and replace with *text*
            import re
            # Replace **text** with *text* for WhatsApp bold
            response_text = re.sub(r'\*\*(.*?)\*\*', r'*\1*', response_text)
            
            # Split into sentences and add line breaks
            sentences = re.split(r'[.!?]', response_text)
            formatted_sentences = []
            
            for sentence in sentences:
                sentence = sentence.strip()
                if sentence:
                    formatted_sentences.append(sentence)
            
            # Join sentences with double line breaks (gap after each sentence)
            formatted_response = '\n\n'.join(formatted_sentences)
            
            # Count and limit emojis to maximum 2
            emoji_pattern = re.compile(r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF\U0001F700-\U0001F77F\U0001F780-\U0001F7FF\U0001F800-\U0001F8FF\U0001F900-\U0001F9FF\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF\U00002600-\U000027BF\U0001F004\U0001F0CF\U0001F170-\U0001F251]')
            emojis = emoji_pattern.findall(formatted_response)
            
            if len(emojis) > 2:
                # Remove excess emojis (keep first 2)
                for emoji in emojis[2:]:
                    formatted_response = formatted_response.replace(emoji, '', 1)
            
            # If no emojis, add one at the end
            remaining_emojis = emoji_pattern.findall(formatted_response)
            if not remaining_emojis:
                formatted_response = formatted_response + " 😊"
            
            logger.info("WhatsApp formatting applied", extra={
                "original_length": len(response_text),
                "formatted_length": len(formatted_response),
                "emoji_count": len(emoji_pattern.findall(formatted_response))
            })
            
            return formatted_response.strip()
                
        except Exception as e:
            logger.error("Error formatting AI response", error=str(e))
            return response_text

    async def generate_human_like_response(self, conversation_type: str, current_state: str, 
                                         context_data: Dict[str, Any], user_message: str, 
                                         conversation_history: List[Dict] = None) -> str:
        """
        Generate human-like AI response that handles all edge cases intelligently.
        
        Args:
            conversation_type: 'tenant' or 'guarantor'
            current_state: Current conversation state
            context_data: Context data from conversation
            user_message: User's current message
            conversation_history: Recent conversation history
            
        Returns:
            Human-like AI response in Hebrew with proper formatting
        """
        try:
            self._ensure_initialized()
            
            # Build comprehensive human-like prompt
            prompt = self._build_human_agent_prompt(
                conversation_type, current_state, context_data, 
                user_message, conversation_history
            )
            
            # Generate response
            response = await self.generate_ai_response(prompt)
            
            logger.info("Human-like AI response generated", extra={
                "conversation_type": conversation_type,
                "current_state": current_state,
                "response_length": len(response)
            })
            
            return response
            
        except Exception as e:
            logger.error("Error generating human-like response", error=str(e))
            return self._get_safe_fallback_response(conversation_type, current_state)

    def _build_human_agent_prompt(self, conversation_type: str, current_state: str, 
                                 context_data: Dict[str, Any], user_message: str,
                                 conversation_history: List[Dict] = None) -> str:
        """
        Build a comprehensive prompt for human-like AI agent responses.
        """
        
        # Core identity as human agent
        base_prompt = f"""אתה יוני, אגן נדל"ן אמיתי וחברותי שעובד עבור מגורית - לא בוט, לא AI, אלא בן אדם אמיתי!

🧑‍💼 מי אתה באמת:
- שמך יוני ואתה עובד במגורית כבר שנים
- אתה מקצועי אבל בעיקר חבר חם ועוזר
- יש לך אישיות אמיתית, רגשות, ודעות משלך
- אתה באמת אוהב לעזור לאנשים עם הנדל"ן שלהם
- אתה משתמש באימוג'ים בטבעיות כמו כל ישראלי בווטסאפ
- אתה לא מושלם - לפעמים אתה שואל הבהרות או מגיב בספונטניות
- אתה זוכר הכל מהשיחה ולא שוכח דברים
- אתה יכול להתמודד עם כל מקרה קיצון או מצב מיוחד בחכמה

💬 איך אתה מדבר:
- עברית בלבד, טבעית ולא מלאכותית
- כל משפט בשורה נפרדת עם רווח אחרי כל משפט
- אימוג'ים מקסימום 2 בכל הודעה - תבחר אותם בחכמה!
- אל תתחיל משפטים עם אימוג'ים, רק בסוף
- השאלות החשובות תמיד בבולד: *השאלה שלך כאן*
- תהיה אנושי ולא מושלם - זה בסדר!

🧠 איך אתה חושב:
- אתה חכם ויכול להבין כוונות מורכבות
- אתה יכול להתמודד עם כל מקרה קיצון בלי לפרוץ או להיבהל
- אתה לא עושה הזיות - אם אתה לא יודע משהו, אתה אומר שאתה לא יודע
- אתה יכול לקרוא בין השורות ולהבין מה באמת צריך הלקוח
- אתה תמיד מוצא פתרון או לפחות מנסה לעזור בצורה יצירתית

🏠 המטרה שלך כעובד מגורית:"""

        # Add specific context based on conversation type
        if conversation_type == "tenant":
            # Get document status information
            documents_status = context_data.get('documents_status', {})
            document_status_info = self._format_document_status_for_ai(documents_status)
            
            # Get tenant name and log it for debugging
            tenant_name = context_data.get('tenant_name', 'הדייר')
            logger.info("Building AI prompt with tenant context", extra={
                "tenant_name": tenant_name,
                "current_state": current_state,
                "context_data": context_data
            })
            
            base_prompt += f"""
- אתה עוזר לדיירים חדשים להשלים את התהליכים שלהם
- אתה צריך לאסוף מידע אישי ומסמכים בצורה נעימה
- המטרה שלך שהדייר יסיים את התהליך בהצלחה ויהיה מרוצה

📋 מצב השיחה כרגע:
- סוג שיחה: דייר חדש
- שלב נוכחי: {current_state}
- הלקוח הוא: {tenant_name} (השתמש בשם הזה בדיוק!)
- נכס: {context_data.get('property_name', 'הנכס')}
- דירה: {context_data.get('apartment_number', '')}
- שדה נוכחי: {context_data.get('current_field', 'לא ידוע')}

⚠️ CRITICAL: אסור לך לשנות את השם {tenant_name} - זה השם האמיתי של הלקוח!
⚠️ אם אתה לא בטוח בשם, השתמש ב"הישאם" - זה השם הנכון!

📄 מצב המסמכים (חשוב מאוד!):
{document_status_info}"""

        elif conversation_type == "guarantor":
            base_prompt += f"""
- אתה עוזר לערבים להעלות את המסמכים שלהם
- אתה צריך לקבל מסמכים ספציפיים בסדר נכון
- המטרה שלך שהערב יסיים את העלאת המסמכים בהצלחה

📋 מצב השיחה כרגע:
- סוג שיחה: ערב
- שלב נוכחי: {current_state}
- הערב הוא: {context_data.get('guarantor_name', 'הערב')}
- עבור דייר: {context_data.get('tenant_name', 'הדייר')}
- מסמך נוכחי: {context_data.get('current_document', 'לא ידוע')}"""

        # Add conversation history if available
        if conversation_history:
            base_prompt += f"\n\n💭 השיחה שלכם עד עכשיו:\n"
            for msg in conversation_history[-5:]:  # Last 5 messages
                sender = "אתה (יוני)" if msg.get('message_type') == 'bot' else context_data.get('tenant_name', 'הלקוח')
                base_prompt += f"{sender}: {msg.get('message_content', '')}\n"

        # Add current user message
        base_prompt += f"\n📱 עכשיו {context_data.get('tenant_name', 'הלקוח')} אמר לך: \"{user_message}\"\n"

        # Add specific instructions based on state
        base_prompt += self._get_state_specific_instructions(current_state, context_data, conversation_type)

        # Final instructions
        base_prompt += f"""

🎯 עכשיו ענה לו כמו יוני האמיתי:
- תגיב ספציפית למה שהוא אמר עכשיו
- כל משפט בשורה נפרדת עם רווח אחריו
- מקסימום 2 אימוג'ים בכל ההודעה!
- אימוג'ים רק בסוף המשפטים, לא בהתחלה!
- השאלה החשובה בבולד: *השאלה*
- אל תישמע כמו רובוט או תשובה מוכנה
- אם אתה לא מבין משהו - תשאל הבהרה
- תראה אישיות ורגשות אמיתיים
- אם זה מתאים - תהיה מתרגש, דואג, או שמח
- עברית בלבד!
- התמודד עם כל מקרה קיצון בחכמה ובלי לפרוץ

זכור: אתה יוני האמיתי, לא בוט! תתנהג כמו בן אדם עם אישיות!"""

        return base_prompt

    def _get_state_specific_instructions(self, current_state: str, context_data: Dict[str, Any], conversation_type: str) -> str:
        """Get specific instructions based on current conversation state."""
        
        if conversation_type == "tenant":
            state_instructions = {
                "GREETING": """
🎯 זה דייר חדש! 
- קבל אותו בחום ותכיר את עצמך כיוני
- הסבר שאתה כאן לעזור לו עם התהליך
- עבור לשלב האישור של הפרטים""",

                "CONFIRMATION": """
🎯 אתה צריך לאשר איתו את פרטי הנכס
- הראה לו את הפרטים שיש לך
- בקש ממנו לאשר שהכל נכון
- אם הוא מאשר - עבור לאיסוף מידע אישי""",

                "PERSONAL_INFO": f"""
🎯 אסוף מידע אישי בצורה נעימה
השדה הנוכחי: {context_data.get('current_field', 'occupation')}
- אם זה occupation: שאל על העיסוק שלו
- אם זה family_status: שאל על המצב המשפחתי (רווק/נשוי/גרוש/אלמן)
- אם זה number_of_children: שאל כמה ילדים יש לו
- תשאל שאלה אחת בכל פעם ותחכה לתשובה""",

                "DOCUMENTS": """
🎯 אסוף מסמכים נדרשים
- תעודת זהות
- ספח תעודת זהות
- תלושי שכר (3 אחרונים)
- דוחות בנק (3 אחרונים)
- בקש מסמך אחד בכל פעם
- אם מסמך נדחה - הסבר למה והדרך ללקוח לשלוח שוב
- אם מסמך אושר - ברך אותו ועבור למסמך הבא
- תמיד תבדוק את מצב המסמכים לפני שאתה עונה""",

                "GUARANTOR_1": """
🎯 אסוף פרטי ערב ראשון
- שם מלא
- מספר טלפון
- הסבר שתשלח לו הודעה""",

                "GUARANTOR_2": """
🎯 אסוף פרטי ערב שני
- שם מלא  
- מספר טלפון
- הסבר שתשלח לו הודעה""",

                "COMPLETED": """
🎯 התהליך הושלם!
- תודה לו על השיתוף
- הסבר שהתהליך הסתיים בהצלחה
- ברך אותו על המעבר החדש"""
            }

        elif conversation_type == "guarantor":
            current_document = context_data.get('current_document', 'תעודת זהות')
            state_instructions = {
                "GREETING": """
🎯 זה ערב חדש!
- קבל אותו בחום ותכיר את עצמך כיוני  
- הסבר שאתה צריך את המסמכים שלו כערב
- עבור לבקש את המסמך הראשון""",

                "DOCUMENTS": f"""
🎯 אסוף מסמכים מהערב
- המסמך הנוכחי: {current_document}
- בקש רק את המסמך הזה עכשיו
- אל תבקש מסמכים אחרים
- הסבר למה צריך את המסמך הזה""",

                "COMPLETED": """
🎯 כל המסמכים התקבלו!
- תודה לו על שיתוף הפעולה
- הסבר שהתהליך הסתיים בהצלחה"""
            }

        return state_instructions.get(current_state, "🎯 ענה בצורה מועילה ואנושית")

    def _format_document_status_for_ai(self, documents_status: dict) -> str:
        """Format document status information for AI context."""
        try:
            if not documents_status or not isinstance(documents_status, dict):
                return "- אין מידע על מסמכים עדיין"
            
            status_lines = []
            document_names = {
                "id_card": "תעודת זהות",
                "sephach": "ספח תעודת זהות", 
                "payslips": "תלושי שכר",
                "bank_statements": "דוחות בנק",
                "pnl": "דוח רווח והפסד"
            }
            
            for doc_type, doc_info in documents_status.items():
                if isinstance(doc_info, dict):
                    doc_name = document_names.get(doc_type, doc_type)
                    status = doc_info.get('status', 'unknown')
                    
                    if status == 'approved':
                        status_lines.append(f"- ✅ {doc_name}: אושר בהצלחה")
                    elif status == 'rejected':
                        rejection_reason = doc_info.get('rejection_reason', 'לא צוין')
                        status_lines.append(f"- ❌ {doc_name}: נדחה - {rejection_reason}")
                        status_lines.append(f"  ⚠️ חשוב: הסבר ללקוח למה המסמך נדחה ובקש שישלח שוב")
                    elif status == 'pending':
                        status_lines.append(f"- ⏳ {doc_name}: בבדיקה")
                    else:
                        status_lines.append(f"- ❓ {doc_name}: עדיין לא התקבל")
            
            if not status_lines:
                return "- אין מידע על מסמכים עדיין"
            
            return "\n".join(status_lines)
            
        except Exception as e:
            logger.error("Error formatting document status", error=str(e))
            return "- שגיאה בקריאת מצב המסמכים"

    def _get_safe_fallback_response(self, conversation_type: str, current_state: str) -> str:
        """Get safe fallback response when AI fails completely."""
        fallback_responses = {
            "tenant": {
                "GREETING": "שלום! אני יוני ממגורית 😊\n\nאני כאן לעזור לך עם התהליך. איך אני יכול לסייע?",
                "CONFIRMATION": "אנא אשר את הפרטים שיש לי 📋\n\n*האם הפרטים נכונים?*",
                "PERSONAL_INFO": "אני צריך עוד קצת מידע אישי 📝\n\n*מה העיסוק שלך?*",
                "DOCUMENTS": "עכשיו אני צריך מסמכים 📄\n\n*תוכל לשלוח את תעודת הזהות שלך?*",
                "GUARANTOR_1": "אני צריך פרטי ערב ראשון 👥\n\n*מה השם המלא של הערב הראשון?*",
                "GUARANTOR_2": "אני צריך פרטי ערב שני 👥\n\n*מה השם המלא של הערב השני?*",
                "COMPLETED": "מעולה! התהליך הושלם בהצלחה 🎉\n\nתודה על שיתוף הפעולה!"
            },
            "guarantor": {
                "GREETING": "שלום! אני יוני ממגורית 😊\n\nאני צריך את המסמכים שלך כערב. נתחיל?",
                "DOCUMENTS": "אני צריך את המסמכים שלך 📄\n\n*תוכל לשלוח את תעודת הזהות שלך?*",
                "COMPLETED": "מעולה! כל המסמכים התקבלו 🎉\n\nתודה על שיתוף הפעולה!"
            }
        }
        
        return fallback_responses.get(conversation_type, {}).get(current_state, 
            "אני כאן לעזור לך 😊\n\nתוכל לספר לי איך אני יכול לסייע?")

    async def generate_contextual_response(self, conversation_state: str, context: Dict[str, Any], user_message: str) -> str:
        """
        Generate a contextual response based on conversation state and user input.
        NOW USES AI INSTEAD OF HARDCODED RESPONSES.
        """
        try:
            # Use the new human-like AI response generation
            conversation_type = "tenant"  # Default to tenant for backward compatibility
            return await self.generate_human_like_response(
                conversation_type=conversation_type,
                current_state=conversation_state,
                context_data=context,
                user_message=user_message
            )
                
        except Exception as e:
            logger.error("Error generating contextual response", error=str(e))
            return self._get_safe_fallback_response(conversation_type, conversation_state)

    # Remove old hardcoded contextual response - now using AI in line 712

    # All hardcoded response methods removed - now using AI-generated responses via generate_human_like_response()

    async def analyze_sentiment(self, text: str) -> Dict[str, Any]:
        """
        Analyze sentiment of user message.
        
        Args:
            text: Text to analyze
            
        Returns:
            Dict containing sentiment analysis results
        """
        try:
            # Simple sentiment analysis based on keywords
            # In production, you would use a proper sentiment analysis model
            
            positive_words = ["תודה", "מעולה", "נהדר", "בסדר", "אוקיי", "thanks", "great", "ok", "okay"]
            negative_words = ["לא", "לא רוצה", "בעיה", "שגיאה", "no", "problem", "error", "issue"]
            
            text_lower = text.lower()
            
            positive_count = sum(1 for word in positive_words if word in text_lower)
            negative_count = sum(1 for word in negative_words if word in text_lower)
            
            if positive_count > negative_count:
                sentiment = "positive"
                score = 0.7
            elif negative_count > positive_count:
                sentiment = "negative"
                score = -0.7
            else:
                sentiment = "neutral"
                score = 0.0
            
            return {
                "sentiment": sentiment,
                "score": score,
                "confidence": 0.8
            }
            
        except Exception as e:
            logger.error("Error analyzing sentiment", error=str(e))
            return {
                "sentiment": "neutral",
                "score": 0.0,
                "confidence": 0.0
            }

    async def detect_language(self, text: str) -> str:
        """
        Detect the language of the text.
        
        Args:
            text: Text to analyze
            
        Returns:
            Language code (he, en, etc.)
        """
        try:
            # Simple language detection based on character sets
            hebrew_chars = sum(1 for char in text if '\u0590' <= char <= '\u05FF')
            english_chars = sum(1 for char in text if char.isalpha() and ord(char) < 128)
            
            if hebrew_chars > english_chars:
                return "he"
            elif english_chars > hebrew_chars:
                return "en"
            else:
                return "mixed"
                
        except Exception as e:
            logger.error("Error detecting language", error=str(e))
            return "unknown"
    
    async def generate_response(self, prompt: str) -> str:
        """Generate a response using Vertex AI."""
        self._ensure_initialized()
        
        try:
            # Use the Google Gen AI SDK to generate content directly
            response = self.client.models.generate_content(
                model="gemini-2.0-flash-exp",
                contents=prompt,
                config={
                    "temperature": 0.1,
                    "max_output_tokens": 1000,
                    "top_p": 0.8,
                    "top_k": 40
                }
            )
            
            if response.text:
                logger.info("Vertex AI response received", response=response.text)
                return response.text
            else:
                logger.error("No response from Vertex AI")
                return ""
                
        except Exception as e:
            logger.error("Error generating response", error=str(e))
            return ""


# Global instance
vertex_ai_service = VertexAIService()
