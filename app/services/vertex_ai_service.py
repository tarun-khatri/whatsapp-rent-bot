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
        """Create a prompt for Vertex AI validation."""
        prompt = f"""
        You are a JSON response generator for a WhatsApp bot. You MUST respond with ONLY valid JSON.

        QUESTION: "{question}"
        USER RESPONSE: "{response}"
        
        CONTEXT: {json.dumps(context, ensure_ascii=False, indent=2)}
        
        TASK: Determine if the user confirmed the details are correct.
        
        RULES:
        1. If user says "yes", "כן", "נכון", "correct", "right", "everything is correct", "i dont want to change anything", "ok", "alright" → confirmed: true
        2. If user says "no", "לא", "wrong", "incorrect", "not right" → confirmed: false
        3. If user is unclear → confirmed: null
        
        RESPOND WITH ONLY THIS JSON FORMAT (NO MARKDOWN, NO CODE BLOCKS):
        {{
            "is_valid": true,
            "feedback": "תודה על התגובה",
            "parsed_data": {{
                "confirmed": true
            }},
            "confidence": 0.9
        }}
        
        CRITICAL REQUIREMENTS:
        - Respond with ONLY the JSON object, no markdown code blocks
        - Replace "confirmed": true with false or null based on user response
        - Keep all other fields exactly as shown
        - NO ```json``` or ``` code blocks
        - NO explanatory text before or after the JSON
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
                    
                    # BULLETPROOF: If Vertex AI is dumb and returns empty parsed_data, use rule-based fallback
                    if not result.get("parsed_data") or result.get("parsed_data", {}).get("confirmed") is None:
                        logger.warning("Vertex AI returned empty parsed_data, using rule-based fallback")
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
        """Rule-based fallback when Vertex AI fails."""
        try:
            # Extract the user response from the prompt
            import re
            response_match = re.search(r'USER RESPONSE: "([^"]*)"', prompt)
            if response_match:
                response = response_match.group(1)
                response_lower = response.lower().strip()
                
                # Check for confirmation words
                confirmation_words = [
                    "yes", "yeah", "yep", "sure", "ok", "alright", "correct", "right", "perfect", 
                    "sounds good", "that's correct", "i confirm", "confirmed", "agreed", "looks good", "seems right",
                    "everything is correct", "i dont want to change anything", "dont want to change",
                    "כן", "נכון", "אישור", "בסדר", "טוב", "מושלם", "נשמע טוב", "זה נכון", "אני מאשר", "אושר", "הסכמתי", "נראה טוב", "נראה נכון"
                ]
                
                rejection_words = [
                    "no", "nope", "wrong", "incorrect", "not right", "that's wrong", "i disagree", "not correct",
                    "לא", "לא נכון", "שגוי", "לא נכון", "אני לא מסכים", "זה לא נכון"
                ]
                
                if any(word in response_lower for word in confirmation_words):
                    logger.info("Rule-based fallback detected confirmation", response=response)
                    return {
                        "is_valid": True,
                        "feedback": "תודה על האישור",
                        "parsed_data": {"confirmed": True},
                        "confidence": 0.9
                    }
                elif any(word in response_lower for word in rejection_words):
                    logger.info("Rule-based fallback detected rejection", response=response)
                    return {
                        "is_valid": True,
                        "feedback": "אנא ספר לי מה צריך לשנות",
                        "parsed_data": {"confirmed": False},
                        "confidence": 0.9
                    }
                else:
                    logger.info("Rule-based fallback couldn't determine confirmation", response=response)
                    return {
                        "is_valid": True,
                        "feedback": "אנא השיב 'כן' או 'לא' כדי שאוכל להמשיך",
                        "parsed_data": {"confirmed": None, "extracted_info": f"user said: {response}"},
                        "confidence": 0.5
                    }
            
            # Default fallback
            return {
                "is_valid": True,
                "feedback": "אנא השיב 'כן' או 'לא' כדי שאוכל להמשיך",
                "parsed_data": {"confirmed": None},
                "confidence": 0.5
            }
            
        except Exception as e:
            logger.error("Error in rule-based fallback", error=str(e))
            return {
                "is_valid": False,
                "feedback": "מצטער, אירעה שגיאה. אנא נסה שוב.",
                "parsed_data": {},
                "confidence": 0.0
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

    async def generate_contextual_response(self, conversation_state: str, context: Dict[str, Any], user_message: str) -> str:
        """
        Generate a contextual response based on conversation state and user input.
        
        Args:
            conversation_state: Current conversation state
            context: Conversation context
            user_message: User's message
            
        Returns:
            Generated response message
        """
        try:
            # For now, we'll use rule-based responses
            # In production, you would use a Vertex AI model for more sophisticated responses
            
            if conversation_state == "GREETING":
                return await self._generate_greeting_response(context)
            elif conversation_state == "CONFIRMATION":
                return await self._generate_confirmation_response(context, user_message)
            elif conversation_state == "PERSONAL_INFO":
                return await self._generate_personal_info_response(context, user_message)
            elif conversation_state == "DOCUMENTS":
                return await self._generate_document_response(context, user_message)
            elif conversation_state == "GUARANTOR_1":
                return await self._generate_guarantor_response(context, user_message, 1)
            elif conversation_state == "GUARANTOR_2":
                return await self._generate_guarantor_response(context, user_message, 2)
            else:
                return "אני לא בטוח איך לעזור. אנא פנה לצוות התמיכה."
                
        except Exception as e:
            logger.error("Error generating contextual response", error=str(e))
            return "מצטער, אירעה שגיאה. אנא נסה שוב."

    async def _generate_greeting_response(self, context: Dict[str, Any]) -> str:
        """Generate greeting response."""
        tenant_name = context.get("tenant_name", "")
        property_name = context.get("property_name", "")
        
        if tenant_name and property_name:
            return f"שלום {tenant_name}, זה יוני ממגורית. אנחנו שמחים שהחלטת להצטרף למשפחת מגורית ב{property_name}."
        else:
            return "שלום! זה יוני ממגורית. איך אני יכול לעזור לך היום?"

    async def _generate_confirmation_response(self, context: Dict[str, Any], user_message: str) -> str:
        """Generate confirmation response."""
        user_lower = user_message.lower()
        
        if any(word in user_lower for word in ["yes", "כן", "confirm", "אישור", "נכון"]):
            return "מעולה! הפרטים נכונים. עכשיו נמשיך לשלב הבא."
        elif any(word in user_lower for word in ["no", "לא", "incorrect", "לא נכון"]):
            return "אין בעיה. אנא ספר לי מה צריך לשנות."
        else:
            return "אנא אשר את הפרטים או ספר לי מה צריך לשנות."

    async def _generate_personal_info_response(self, context: Dict[str, Any], user_message: str) -> str:
        """Generate personal info response."""
        current_field = context.get("current_field", "")
        
        if current_field == "occupation":
            return "תודה! עכשיו אנא ספר לי מה המצב המשפחתי שלך (רווק/נשוי/גרוש/אלמן)."
        elif current_field == "family_status":
            return "תודה! כמה ילדים יש לך?"
        elif current_field == "number_of_children":
            return "מעולה! עכשיו נתחיל לאסוף את המסמכים הנדרשים."
        else:
            return "אנא השלם את הפרטים האישיים."

    async def _generate_document_response(self, context: Dict[str, Any], user_message: str) -> str:
        """Generate document response."""
        current_document = context.get("current_document", "")
        
        if current_document == "id_card":
            return "תודה! עכשיו אנא שלח את הטופס ספח (Sephach)."
        elif current_document == "sephach":
            return "תודה! עכשיו אנא שלח את 3 תלושי השכר האחרונים שלך."
        elif current_document == "payslips":
            return "תודה! עכשיו אנא שלח את דוחות הבנק של 3 החודשים האחרונים."
        elif current_document == "pnl":
            return "תודה! עכשיו אנא שלח את דוחות הבנק של 3 החודשים האחרונים."
        elif current_document == "bank_statements":
            return "מעולה! כל המסמכים התקבלו. עכשיו נצטרך מידע על הערבים."
        else:
            return "אנא שלח את המסמך הנדרש."

    async def _generate_guarantor_response(self, context: Dict[str, Any], user_message: str, guarantor_num: int) -> str:
        """Generate guarantor response."""
        if guarantor_num == 1:
            return "תודה! עכשיו אנא שלח את השם ומספר הטלפון של הערב השני."
        else:
            return "מעולה! כל המידע התקבל. התהליך הושלם בהצלחה!"

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
