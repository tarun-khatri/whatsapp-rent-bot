"""
Vertex AI Document Parser Service

This service uses Vertex AI to intelligently parse document text extracted by Document AI.
It replaces complex regex patterns with AI-powered natural language understanding.
"""

import json
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, date, timedelta
import re

from app.services.vertex_ai_service import vertex_ai_service
from flask import current_app

logger = logging.getLogger(__name__)


class VertexAIDocumentParser:
    """AI-powered document parser using Vertex AI for intelligent text extraction."""
    
    def __init__(self):
        self.vertex_ai = vertex_ai_service
        logger.info("Vertex AI Document Parser initialized")
    
    async def parse_id_card(self, text: str, tenant_name: str = None) -> Dict[str, Any]:
        """
        Parse Israeli ID card text using Vertex AI.
        
        Args:
            text: Raw OCR text from Document AI
            tenant_name: Expected tenant name for validation
            
        Returns:
            Dict containing extracted data and validation results
        """
        try:
            logger.info("Starting ID card parsing with Vertex AI", extra={"text_length": len(text)})
            
            # Create comprehensive prompt for ID card parsing
            prompt = self._create_id_card_prompt(text, tenant_name)
            
            # Get AI response
            response = await self.vertex_ai.generate_response(prompt)
            
            # Parse the structured response
            parsed_data = self._parse_ai_response(response)
            
            # Perform additional validation
            validation_results = await self._validate_id_card_data(parsed_data, tenant_name)
            
            # Combine results
            result = {
                "success": validation_results.get("is_valid", False),
                "data": parsed_data,
                "validation": validation_results,
                "confidence": parsed_data.get("confidence", 0.8),
                "source": "vertex_ai"
            }
            
            logger.info("ID card parsing completed successfully", 
                       extra={"extracted_fields": list(parsed_data.keys()),
                              "validation_passed": validation_results["is_valid"]})
            
            return result
            
        except Exception as e:
            logger.error("Error in ID card parsing", extra={"error": str(e)})
            return {
                "success": False,
                "error": str(e),
                "data": {},
                "validation": {"is_valid": False, "errors": [str(e)]},
                "confidence": 0.0,
                "source": "vertex_ai"
            }
    
    def _create_id_card_prompt(self, text: str, tenant_name: str = None) -> str:
        """Create a comprehensive prompt for ID card parsing."""
        
        tenant_context = ""
        if tenant_name:
            tenant_context = f"\nExpected tenant name: {tenant_name}"
        
        prompt = f"""
You are an expert document parser specializing in Israeli ID cards (תעודת זהות). 
Parse the following Hebrew/Arabic text extracted from an ID card and extract all relevant information.

Text to parse:
{text}
{tenant_context}

Extract the following information and return as JSON:

{{
    "id_number": "9-digit ID number (remove spaces, format as 123456789)",
    "full_name": "Complete name in Hebrew",
    "first_name": "First name only",
    "family_name": "Family name only", 
    "date_of_birth": "Birth date in DD.MM.YYYY format",
    "date_of_issue": "Issue date in DD.MM.YYYY format",
    "date_of_expiry": "Expiry date in DD.MM.YYYY format",
    "gender": "male/female/unknown",
    "nationality": "Nationality (usually 'ישראלי' for Israeli)",
    "place_of_birth": "Place of birth if available",
    "father_name": "Father's name if available",
    "mother_name": "Mother's name if available",
    "place_of_residence": "Place of residence if available",
    "confidence": 0.0-1.0,
    "extraction_notes": "Any notes about the extraction process"
}}

IMPORTANT RULES:
1. ID number must be exactly 9 digits (remove all spaces and formatting)
2. Dates must be in DD.MM.YYYY format
3. Names should be in Hebrew as they appear on the card
4. If a field is not found, use null
5. Be very careful with Hebrew text - preserve exact spelling
6. If tenant_name is provided, check if the extracted name matches
7. Set confidence based on how clear the text is and how many fields you could extract

Return ONLY the JSON object, no additional text or markdown formatting.
"""
        return prompt
    
    def _create_sephach_prompt(self, text: str, tenant_info: Dict[str, Any] = None) -> str:
        """Create a comprehensive prompt for Sephach parsing."""
        
        tenant_context = ""
        if tenant_info and tenant_info.get("full_name"):
            tenant_context = f"\nExpected tenant name: {tenant_info['full_name']}"
        
        prompt = f"""
You are an expert document parser specializing in Israeli Sephach (ספח לתעודת זהות) - the ID card appendix form.
Parse the following Hebrew/Arabic text extracted from a Sephach document and extract all relevant information.

Text to parse:
{text}
{tenant_context}

Extract the following information and return as JSON:

{{
    "id_number": "9-digit ID number (remove spaces, format as 123456789)",
    "full_name": "Complete name in Hebrew",
    "first_name": "First name only",
    "family_name": "Family name only",
    "address": "Current address",
    "marital_status": "Marital status - CRITICAL: Look for ANY Hebrew text indicating marital status. Search for: נשוי/נשואה/רווק/רווקה/גרוש/גרושה/אלמן/אלמנה. If you see spouse/children info, infer marital status. REQUIRED FIELD",
    "spouse_name": "Spouse name if married",
    "spouse_id_number": "Spouse ID number if married",
    "children": [
        {{
            "name": "Child's full name",
            "id_number": "Child's ID number",
            "birth_date": "Birth date in DD.MM.YYYY format",
            "gender": "male/female"
        }}
    ],
    "previous_family_name": "Previous family name if changed",
    "previous_first_name": "Previous first name if changed",
    "maiden_name": "Maiden name if applicable",
    "issue_date": "Sephach issue date in DD.MM.YYYY format",
    "document_number": "Sephach document number",
    "confidence": 0.0-1.0,
    "extraction_notes": "Any notes about the extraction process"
}}

IMPORTANT RULES:
1. ID number must be exactly 9 digits (remove all spaces and formatting)
2. Dates must be in DD.MM.YYYY format
3. Names should be in Hebrew as they appear on the document
4. If a field is not found, use null
5. Be very careful with Hebrew text - preserve exact spelling
6. If tenant_name is provided, check if the extracted name matches
7. Set confidence based on how clear the text is and how many fields you could extract
8. For children array, include all children found in the document
9. Marital status should match the Hebrew text exactly - look for "המצב האישי" field
10. Address should include full address details
11. CRITICAL: Marital status is REQUIRED - look for ANY Hebrew text indicating marital status
12. If you see spouse information (spouse_name, spouse_id_number), the person is likely married
13. If you see children information, the person is likely married
14. Look for: נשוי/נשואה/רווק/רווקה/גרוש/גרושה/אלמן/אלמנה anywhere in the document
15. INFER marital status from context: spouse + children = נשואה/נשוי
16. Be very aggressive in finding marital status - it's a critical field

Return ONLY the JSON object, no additional text or markdown formatting.
"""
        return prompt
    
    def _parse_ai_response(self, response: str) -> Dict[str, Any]:
        """Parse the AI response and extract structured data."""
        try:
            # Clean the response (remove markdown if present)
            cleaned_response = self._clean_ai_response(response)
            
            # Debug: Log the cleaned response
            logger.info("Attempting to parse JSON", extra={"cleaned_response": cleaned_response[:500]})
            logger.info("Full cleaned response", extra={"full_response": cleaned_response})
            
            # Parse JSON
            parsed_data = json.loads(cleaned_response)
            
            # Validate required fields
            if not parsed_data.get("id_number"):
                logger.warning("No ID number found in AI response")
            
            if not parsed_data.get("full_name"):
                logger.warning("No name found in AI response")
            
            return parsed_data
            
        except json.JSONDecodeError as e:
            logger.error("Failed to parse AI response as JSON", extra={"error": str(e), "cleaned_response": cleaned_response[:300]})
            # Return empty data - let the system handle it
            return {
                "id_number": None,
                "full_name": None,
                "confidence": 0.0,
                "extraction_notes": f"JSON parsing failed: {str(e)}"
            }
        except Exception as e:
            logger.error("Error parsing AI response", extra={"error": str(e)})
            return {
                "id_number": None,
                "full_name": None,
                "confidence": 0.0,
                "extraction_notes": f"Parsing error: {str(e)}"
            }
    
    def _clean_ai_response(self, response: str) -> str:
        """Clean AI response to extract pure JSON."""
        # Remove markdown code blocks if present
        if "```json" in response:
            start = response.find("```json") + 7
            end = response.find("```", start)
            if end != -1:
                response = response[start:end]
        elif "```" in response:
            start = response.find("```") + 3
            end = response.find("```", start)
            if end != -1:
                response = response[start:end]
        
        # Remove any leading/trailing whitespace
        response = response.strip()
        
        # Debug logging
        logger.info("Cleaned AI response", extra={"response_preview": response[:200]})
        
        return response
    
    def _extract_basic_info_from_text(self, response: str) -> Dict[str, Any]:
        """Extract basic information from text when JSON parsing fails."""
        try:
            # Try to find ID number in the text
            import re
            id_match = re.search(r'"id_number":\s*"(\d+)"', response)
            id_number = id_match.group(1) if id_match else None
            
            # Try to find name
            name_match = re.search(r'"full_name":\s*"([^"]+)"', response)
            full_name = name_match.group(1) if name_match else None
            
            # Try to find confidence
            confidence_match = re.search(r'"confidence":\s*([\d.]+)', response)
            confidence = float(confidence_match.group(1)) if confidence_match else 0.5
            
            return {
                "id_number": id_number,
                "full_name": full_name,
                "confidence": confidence,
                "extraction_notes": "Extracted from text fallback due to JSON parsing error"
            }
        except Exception as e:
            logger.error("Error in fallback extraction", extra={"error": str(e)})
            return {
                "id_number": None,
                "full_name": None,
                "confidence": 0.0,
                "extraction_notes": f"Fallback extraction failed: {str(e)}"
            }
    
    async def _validate_id_card_data(self, data: Dict[str, Any], tenant_name: str = None) -> Dict[str, Any]:
        """Perform comprehensive validation on extracted data."""
        validation = {
            "is_valid": True,
            "errors": [],
            "warnings": [],
            "field_validation": {}
        }
        
        # Validate ID number
        id_validation = self._validate_id_number(data.get("id_number"))
        validation["field_validation"]["id_number"] = id_validation
        if not id_validation["is_valid"]:
            validation["is_valid"] = False
            validation["errors"].extend(id_validation["errors"])
        
        # Validate name
        name_validation = await self._validate_name(data.get("full_name"), tenant_name)
        validation["field_validation"]["name"] = name_validation
        if not name_validation["is_valid"]:
            validation["is_valid"] = False
            validation["errors"].extend(name_validation["errors"])
        elif name_validation["warnings"]:
            validation["warnings"].extend(name_validation["warnings"])
        
        # Validate dates
        date_validation = self._validate_dates(data)
        validation["field_validation"]["dates"] = date_validation
        if date_validation["warnings"]:
            validation["warnings"].extend(date_validation["warnings"])
        
        # Check confidence
        confidence = data.get("confidence", 0.0)
        if confidence < 0.5:
            validation["warnings"].append(f"Low confidence score: {confidence}")
        
        return validation
    
    def _validate_id_number(self, id_number: str) -> Dict[str, Any]:
        """Validate Israeli ID number format."""
        if not id_number:
            return {"is_valid": False, "errors": ["ID number is required"]}
        
        # Remove any non-digit characters
        clean_id = re.sub(r'\D', '', str(id_number))
        
        if len(clean_id) != 9:
            return {"is_valid": False, "errors": [f"ID number must be 9 digits, got {len(clean_id)}"]}
        
        if not clean_id.isdigit():
            return {"is_valid": False, "errors": ["ID number must contain only digits"]}
        
        return {"is_valid": True, "clean_id": clean_id}
    
    async def _validate_name(self, name: str, tenant_name: str = None) -> Dict[str, Any]:
        """Validate extracted name with intelligent matching."""
        if not name:
            return {"is_valid": False, "errors": ["Name is required"]}
        
        result = {"is_valid": True, "warnings": [], "errors": []}
        
        # Check if name matches expected tenant name - MANDATORY VALIDATION
        if tenant_name:
            if not await self._names_match(name, tenant_name):
                result["errors"].append(f"Name '{name}' doesn't match expected '{tenant_name}'")
                result["is_valid"] = False
                logger.warning("ID card rejected - name mismatch", 
                             extra={"extracted_name": name, "tenant_name": tenant_name})
        
        return result
    
    async def _names_match(self, extracted_name: str, expected_name: str) -> bool:
        """Check if two names match with human-like understanding."""
        if not extracted_name or not expected_name:
            return False
        
        # Normalize names: lowercase, strip, remove extra spaces
        def normalize_name(name):
            # Remove common Hebrew prefixes/suffixes and normalize
            name = name.strip()
            # Remove common Hebrew articles and particles
            hebrew_particles = ['ה', 'ב', 'ל', 'מ', 'כ', 'ש']
            for particle in hebrew_particles:
                if name.startswith(particle + ' '):
                    name = name[2:].strip()
            return ' '.join(name.lower().strip().split())
        
        norm_extracted = normalize_name(extracted_name)
        norm_expected = normalize_name(expected_name)
        
        # Exact match
        if norm_extracted == norm_expected:
            return True
        
        # Split into parts for comparison
        extracted_parts = set(norm_extracted.split())
        expected_parts = set(norm_expected.split())
        
        # Check if all parts of expected name are in extracted name
        if expected_parts.issubset(extracted_parts):
            return True
        
        # Check if all parts of extracted name are in expected name
        if extracted_parts.issubset(expected_parts):
            return True
        
        # Check for partial matches (at least 2 parts match)
        common_parts = extracted_parts.intersection(expected_parts)
        if len(common_parts) >= 2:
            return True
        
        # Check for single name match (for cases like "Tarun" vs "Tarun Khatri")
        if len(common_parts) == 1 and len(extracted_parts) == 1:
            return True
        
        # Special case: Check if any significant part matches (for Hebrew names)
        # This handles cases where the order might be different or some parts missing
        for extracted_part in extracted_parts:
            for expected_part in expected_parts:
                if len(extracted_part) >= 3 and len(expected_part) >= 3:
                    # Check if one is contained in the other (for similar names)
                    if extracted_part in expected_part or expected_part in extracted_part:
                        return True
        
        # NEW: Handle cross-language name matching using Vertex AI
        # Check if we're comparing names in different languages
        if self._is_cross_language_comparison(norm_extracted, norm_expected):
            return await self._ai_name_match(norm_extracted, norm_expected)
        
        return False
    
    def _is_cross_language_comparison(self, name1: str, name2: str) -> bool:
        """Check if we're comparing names in different languages."""
        # Check if one name contains Hebrew characters and the other doesn't
        has_hebrew_1 = any('\u0590' <= char <= '\u05FF' for char in name1)
        has_hebrew_2 = any('\u0590' <= char <= '\u05FF' for char in name2)
        
        # If one has Hebrew and the other doesn't, it's cross-language
        return has_hebrew_1 != has_hebrew_2
    
    async def _ai_name_match(self, name1: str, name2: str) -> bool:
        """Use Vertex AI to determine if two names in different languages refer to the same person."""
        try:
            prompt = f"""
You are an expert in Hebrew and English name matching. Determine if these two names refer to the same person:

Name 1: "{name1}"
Name 2: "{name2}"

Consider:
- Hebrew to English transliteration (e.g., "שרין" = "Shirin")
- English to Hebrew transliteration (e.g., "David" = "דוד")
- Different spellings of the same name
- Cultural name variations
- Common name translations

Respond with ONLY "YES" if the names refer to the same person, or "NO" if they don't.
"""

            response = await self.vertex_ai.generate_response(prompt)
            
            # Clean the response
            cleaned_response = response.strip().upper()
            
            # Check if AI says YES
            if "YES" in cleaned_response:
                logger.info("AI confirmed name match", 
                           extra={"name1": name1, "name2": name2, "ai_response": cleaned_response})
                return True
            else:
                logger.info("AI rejected name match", 
                           extra={"name1": name1, "name2": name2, "ai_response": cleaned_response})
                return False
                
        except Exception as e:
            logger.error("Error in AI name matching", 
                        extra={"name1": name1, "name2": name2, "error": str(e)})
            # If AI fails, be conservative and reject the match
            return False
    
    def _validate_dates(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate date fields."""
        warnings = []
        
        # Check date formats and validity
        date_fields = ["date_of_birth", "date_of_issue", "date_of_expiry"]
        
        for field in date_fields:
            date_value = data.get(field)
            if date_value:
                try:
                    # Parse date in DD.MM.YYYY format
                    parsed_date = datetime.strptime(date_value, "%d.%m.%Y").date()
                    
                    # Check if expiry date is in the future
                    if field == "date_of_expiry" and parsed_date < date.today():
                        warnings.append(f"ID card expired on {date_value}")
                    elif field == "date_of_expiry" and parsed_date < date.today().replace(year=date.today().year + 1):
                        warnings.append(f"ID card expires soon: {date_value}")
                        
                except ValueError:
                    warnings.append(f"Invalid date format for {field}: {date_value}")
        
        return {"warnings": warnings}
    
    async def _validate_sephach_data(self, data: Dict[str, Any], tenant_info: Dict[str, Any] = None) -> Dict[str, Any]:
        """Perform comprehensive validation on extracted Sephach data."""
        validation = {
            "is_valid": True,
            "errors": [],
            "warnings": [],
            "field_validation": {}
        }
        
        # Validate ID number
        id_validation = self._validate_id_number(data.get("id_number"))
        validation["field_validation"]["id_number"] = id_validation
        if not id_validation["is_valid"]:
            validation["is_valid"] = False
            validation["errors"].extend(id_validation["errors"])
        
        # Validate name
        tenant_name = tenant_info.get("full_name") if tenant_info else None
        name_validation = await self._validate_name(data.get("full_name"), tenant_name)
        validation["field_validation"]["name"] = name_validation
        if not name_validation["is_valid"]:
            validation["is_valid"] = False
            validation["errors"].extend(name_validation["errors"])
        elif name_validation["warnings"]:
            validation["warnings"].extend(name_validation["warnings"])
        
        # Validate required Sephach fields
        required_fields = ["full_name", "id_number", "address", "marital_status"]
        missing_fields = []
        
        for field in required_fields:
            if not data.get(field):
                missing_fields.append(field)
        
        if missing_fields:
            validation["is_valid"] = False
            validation["errors"].append(f"Missing required fields: {', '.join(missing_fields)}")
            logger.warning("Sephach rejected - missing required fields", 
                         extra={"missing_fields": missing_fields})
        
        # Validate marital status consistency
        marital_status = data.get("marital_status", "")
        if marital_status:
            marital_status = marital_status.lower()
        spouse_name = data.get("spouse_name")
        children = data.get("children", [])
        
        if marital_status in ["נשוי", "נשואה", "married"]:
            if not spouse_name:
                validation["warnings"].append("Married status but no spouse name found")
        elif marital_status in ["רווק", "רווקה", "single"]:
            if spouse_name:
                validation["warnings"].append("Single status but spouse name found")
            if children:
                validation["warnings"].append("Single status but children found")
        
        # Validate children data if present
        if children:
            for i, child in enumerate(children):
                if not child.get("name"):
                    validation["warnings"].append(f"Child {i+1} missing name")
                if not child.get("id_number"):
                    validation["warnings"].append(f"Child {i+1} missing ID number")
        
        # Check confidence
        confidence = data.get("confidence", 0.0)
        if confidence < 0.5:
            validation["warnings"].append(f"Low confidence score: {confidence}")
        
        # Log validation results
        logger.info("Sephach validation completed", 
                   extra={"is_valid": validation["is_valid"],
                          "errors_count": len(validation["errors"]),
                          "warnings_count": len(validation["warnings"])})
        
        return validation
    
    async def parse_sephach(self, text: str, tenant_info: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Parse Israeli Sephach (ID card appendix) text using Vertex AI.
        
        Args:
            text: Raw OCR text from Document AI
            tenant_info: Tenant information for validation
            
        Returns:
            Dict containing extracted data and validation results
        """
        try:
            logger.info("Starting Sephach parsing with Vertex AI", extra={"text_length": len(text)})
            
            # Create comprehensive prompt for Sephach parsing
            prompt = self._create_sephach_prompt(text, tenant_info)
            
            # Get AI response
            response = await self.vertex_ai.generate_response(prompt)
            
            # Parse the structured response
            parsed_data = self._parse_ai_response(response)
            
            # Perform additional validation
            validation_results = await self._validate_sephach_data(parsed_data, tenant_info)
            
            # Combine results
            result = {
                "success": validation_results.get("is_valid", False),
                "data": parsed_data,
                "validation": validation_results,
                "confidence": parsed_data.get("confidence", 0.8),
                "source": "vertex_ai"
            }
            
            logger.info("Sephach parsing completed successfully", 
                       extra={"extracted_fields": list(parsed_data.keys()),
                              "validation_passed": validation_results["is_valid"]})
            
            return result
            
        except Exception as e:
            logger.error("Error in Sephach parsing", extra={"error": str(e)})
            return {
                "success": False,
                "error": str(e),
                "data": {},
                "validation": {"is_valid": False, "errors": [str(e)]},
                "confidence": 0.0,
                "source": "vertex_ai"
            }

    async def parse_other_documents(self, text: str, document_type: str) -> Dict[str, Any]:
        """Parse other document types (payslips, bank statements, etc.)."""
        try:
            logger.info("Parsing document with Vertex AI", extra={"document_type": document_type})
            
            prompt = self._create_generic_document_prompt(text, document_type)
            response = await self.vertex_ai.generate_response(prompt)
            parsed_data = self._parse_ai_response(response)
            
            return {
                "success": True,
                "data": parsed_data,
                "confidence": parsed_data.get("confidence", 0.8),
                "source": "vertex_ai"
            }
            
        except Exception as e:
            logger.error("Error parsing document", extra={"document_type": document_type, "error": str(e)})
            return {
                "success": False,
                "error": str(e),
                "data": {},
                "confidence": 0.0,
                "source": "vertex_ai"
            }
    
    def _create_generic_document_prompt(self, text: str, document_type: str) -> str:
        """Create prompt for generic document parsing."""
        
        prompts = {
            "payslip": """
Extract information from this payslip document:
- Gross salary amount
- Net salary amount  
- Pay period dates
- Employee name
- Company name
Return as JSON with extracted fields.
""",
            "bank_statement": """
Extract information from this bank statement:
- Account number
- Current balance
- Statement period
- Bank name
Return as JSON with extracted fields.
""",
            "sephach": """
Extract information from this Sephach (Israeli ID card appendix) document:
- Personal details (name, ID number, address)
- Marital status and spouse information
- Children information
- Previous names if applicable
- Document issue date and number
Return as JSON with extracted fields.
"""
        }
        
        base_prompt = prompts.get(document_type, "Extract relevant information from this document and return as JSON.")
        
        return f"""
{base_prompt}

Document text:
{text}

Return ONLY a JSON object with the extracted information.
"""


    async def parse_payslip(self, text: str, tenant_name: str = None, tenant_id: str = None) -> Dict[str, Any]:
        """
        Parse Israeli payslip text using Vertex AI.
        
        Args:
            text: Raw OCR text from Document AI
            tenant_name: Expected tenant name for validation
            tenant_id: Expected tenant ID for validation
            
        Returns:
            Dict containing extracted data and validation results
        """
        try:
            logger.info("Starting payslip parsing with Vertex AI", extra={"text_length": len(text)})
            
            # Create comprehensive prompt for payslip parsing
            prompt = self._create_payslip_prompt(text, tenant_name, tenant_id)
            
            # Get AI response
            response = await self.vertex_ai.generate_response(prompt)
            
            # Parse the structured response
            parsed_data = self._parse_ai_response(response)
            
            # Perform additional validation
            validation_results = await self._validate_payslip_data(parsed_data, tenant_name, tenant_id)
            
            return {
                "success": validation_results.get("is_valid", False),
                "data": parsed_data,
                "validation": validation_results
            }
            
        except Exception as e:
            logger.error("Error in payslip parsing", extra={"error": str(e)})
            return {
                "success": False,
                "data": {},
                "validation": {
                    "is_valid": False,
                    "errors": [f"Payslip parsing failed: {str(e)}"],
                    "warnings": []
                }
            }

    async def parse_pnl(self, text: str, tenant_name: str = None, tenant_id: str = None) -> Dict[str, Any]:
        """
        Parse PNL (Profit and Loss) statement text using Vertex AI.
        
        Args:
            text: Raw OCR text from Document AI
            tenant_name: Expected tenant name for validation
            tenant_id: Expected tenant ID for validation
            
        Returns:
            Dict containing extracted data and validation results
        """
        try:
            logger.info("Starting PNL parsing with Vertex AI", extra={"text_length": len(text)})
            
            # Create comprehensive prompt for PNL parsing
            prompt = self._create_pnl_prompt(text, tenant_name, tenant_id)
            
            # Get AI response
            response = await self.vertex_ai.generate_response(prompt)
            
            # Parse the structured response
            parsed_data = self._parse_ai_response(response)
            
            # Perform additional validation
            validation_results = await self._validate_pnl_data(parsed_data, tenant_name, tenant_id)
            
            return {
                "success": validation_results.get("is_valid", False),
                "data": parsed_data,
                "validation": validation_results
            }
            
        except Exception as e:
            logger.error("Error in PNL parsing", extra={"error": str(e)})
            return {
                "success": False,
                "data": {},
                "validation": {
                    "is_valid": False,
                    "errors": [f"PNL parsing failed: {str(e)}"],
                    "warnings": []
                }
            }

    async def parse_bank_statement(self, text: str, tenant_name: str = None, tenant_id: str = None) -> dict:
        """Parse bank statement document using Vertex AI."""
        try:
            logger.info("Starting bank statement parsing with Vertex AI", extra={"text_length": len(text)})
            
            # Create comprehensive prompt for bank statement parsing
            prompt = self._create_bank_statement_prompt(text, tenant_name, tenant_id)
            
            # Get AI response
            response = await self.vertex_ai.generate_response(prompt)
            
            # Parse the structured response
            parsed_data = self._parse_ai_response(response)
            
            # Perform additional validation
            validation_results = await self._validate_bank_statement_data(parsed_data, tenant_name, tenant_id)
            
            return {
                "success": validation_results.get("is_valid", False),
                "data": parsed_data,
                "validation": validation_results
            }
            
        except Exception as e:
            logger.error("Error in bank statement parsing", extra={"error": str(e)})
            return {
                "success": False,
                "data": {},
                "validation": {
                    "is_valid": False,
                    "errors": [f"Bank statement parsing failed: {str(e)}"],
                    "warnings": []
                }
            }

    def _create_payslip_prompt(self, text: str, tenant_name: str = None, tenant_id: str = None) -> str:
        """Create a comprehensive prompt for payslip parsing."""
        return f"""
You are an expert in parsing Israeli payslips (תלוש משכורת). Extract the following information from this payslip document:

REQUIRED FIELDS:
1. employee_name: Full name of the employee (שם עובד)
2. employee_id: Israeli government ID number - 9 digits only (מספר זהות)
3. company_name: Company name (שם החברה)
4. pay_period: Pay period month/year (תלוש משכורת לחודש) - Look for "לחודש" or month/year format
5. gross_salary: Gross salary amount (שכר יסוד/ברוטו)
6. net_salary: Net salary amount (שכר נטו)
7. basic_salary: Basic salary (שכר יסוד) - Look for "שכר יסוד" or "שכר בסיס"
8. deductions: Total deductions (סה"כ ניכויים)
9. income_tax: Income tax (מס הכנסה)
10. national_insurance: National insurance (ביטוח לאומי)
11. health_insurance: Health insurance (ביטוח בריאות)
12. work_days: Number of work days (ימי עבודה)
13. work_hours: Number of work hours (שעות עבודה)
14. hourly_rate: Hourly rate (תעריף שעה)
15. bank_account: Bank account number (חשבון)
16. prepared_by: Prepared by (בוצע ע"י)
17. document_date: Document date (בתאריך)

VALIDATION CONTEXT:
- Expected tenant name: {tenant_name or 'Not provided'}
- Expected tenant ID: {tenant_id or 'Not provided'}

IMPORTANT RULES:
1. Extract ALL required fields - missing fields will cause validation failure
2. Names should be in Hebrew if the document is in Hebrew
3. CRITICAL: For employee_id, extract ONLY the Israeli government ID number (מספר זהות) - must be 9 digits
4. DO NOT extract company employee ID (מספר עובד) - ignore this number
5. Look specifically for "מספר זהות" label, not "מספר עובד"
6. Israeli ID numbers are always 9 digits (e.g., 301177358, 123456789)
7. Salary amounts should be numeric values only
8. Dates should be in DD/MM/YYYY format
9. If a field is not found, mark it as null
10. Look for Hebrew labels like "שם עובד", "מספר זהות", "שכר יסוד", etc.
11. Company information is usually in the header
12. Financial data is usually in the main table
13. Employee details are usually at the top
14. Israeli ID is usually in the personal data section (נתונים אישיים)

Document text:
{text}

Return ONLY a JSON object with the extracted information. Do not include any explanations or additional text.
"""

    def _create_pnl_prompt(self, text: str, tenant_name: str = None, tenant_id: str = None) -> str:
        """Create a comprehensive prompt for PNL parsing."""
        return f"""
You are an expert in parsing Israeli PNL (Profit and Loss) statements. This document may be a 2-page PDF with incomplete OCR text. Extract the following information from this PNL document:

REQUIRED FIELDS:
1. business_name: Business/company name (שם החברה/העסק)
2. owner_name: Owner name (שם בעל העסק) - CRITICAL: Look for the business owner's name
3. owner_id: Owner ID number (תעודת זהות) - CRITICAL: Look for 9-digit Israeli ID number
4. accountant_name: Accountant name (שם רואה החשבון)
5. accountant_signature: Accountant signature present (yes/no) - CRITICAL: Look for signatures/stamps
6. period: Financial period (תקופה)
7. revenue: Total revenue (הכנסות)
8. expenses: Total expenses (הוצאות)
9. net_income: Net income (רווח נקי)
10. gross_profit: Gross profit (רווח גולמי)
11. operating_expenses: Operating expenses (הוצאות תפעול)
12. document_date: Document date
13. accountant_license: Accountant license number
14. business_address: Business address
15. business_phone: Business phone number

VALIDATION CONTEXT:
- Expected tenant name: {tenant_name or 'Not provided'}
- Expected tenant ID: {tenant_id or 'Not provided'}

DYNAMIC EXTRACTION RULES - ADAPT TO ANY FORMAT:
1. For business_name: Look for the business owner's name anywhere in the document
2. For owner_name: Same as business_name for sole proprietorships
3. For owner_id: Look for ANY 9-digit number anywhere in the document
4. For accountant_signature: Look for any accountant information, signatures, or professional stamps
5. For accountant_name: Look for any accountant names anywhere in the document
6. For financial data: Look for revenue, expenses, net income anywhere in the document

ADAPTIVE SEARCH STRATEGY:
- Business/Owner Name: Look anywhere for the main person's name
- Owner ID: Look for ANY 9-digit number anywhere in the document
- Accountant Info: Look for any accountant-related information anywhere
- Financial Data: Look for revenue, expenses, net income anywhere
- Period: Look for any date ranges or periods
- Be flexible with document layouts and formats

IMPORTANT: If you find a 9-digit number anywhere in the document, it's likely the owner_id. Don't assume it's only in specific locations.

CRITICAL: If you find a 9-digit number like "558346847", use it as owner_id, not as accountant_license.

INTELLIGENT EXTRACTION FOR ANY PNL FORMAT:
- This document could be in ANY format - 1 page, 2 pages, different layouts, different languages
- Use your knowledge of PNL documents to extract data regardless of format
- Look for patterns in the numbers - revenue is usually the largest positive number
- Expenses are usually the sum of all negative numbers or expense categories
- Net income = Revenue - Expenses (calculate if missing)
- If you see partial financial data, try to reconstruct the complete picture
- Look for Hebrew keywords like "הכנסות", "הוצאות", "רווח נקי" even in fragmented text
- Use mathematical logic to fill in missing financial data
- Be flexible with document layouts - PNL documents can vary significantly
- Look for any 9-digit number anywhere in the document for owner_id
- Look for any name that could be the business owner
- Look for any accountant information (names, signatures, stamps)
- Use intelligent inference to fill missing data based on available information

IMPORTANT RULES:
1. Extract ALL required fields - missing fields will cause validation failure
2. Names should be in Hebrew if the document is in Hebrew
3. ID numbers should be exactly as shown (9 digits for Israeli ID)
4. Financial amounts should be numeric values only
5. Dates should be in DD/MM/YYYY format
6. If a field is not found, mark it as null
7. Look for Hebrew labels like "שם בעל העסק", "תעודת זהות", "רווח נקי", etc.
8. Accountant signature is CRITICAL for PNL validation
9. Financial data should be consistent and reasonable
10. Look for official stamps and signatures
11. If you see any name in the document, try to determine if it's the business owner
12. Look for any ID numbers in the document - they might be the owner's ID
13. If OCR text is incomplete, use intelligent inference to fill missing financial data

Document text:
{text}

Return ONLY a JSON object with the extracted information. Do not include any explanations or additional text.
"""

    def _create_bank_statement_prompt(self, text: str, tenant_name: str = None, tenant_id: str = None) -> str:
        """Create a comprehensive prompt for bank statement parsing."""
        return f"""
You are an expert in parsing Israeli bank statements (דוח בנק). This document may be in any format - 1 page, 2 pages, different layouts, different banks. Extract the following information from this bank statement document:

REQUIRED FIELDS:
1. account_holder_name: Account holder name (שם בעל החשבון) - CRITICAL: Look for the account owner's name
2. bank_name: Bank name (שם הבנק) - Look for bank names like "לאומי", "הפועלים", "מזרחי", "דיסקונט", "יגואר"
3. statement_period_start: Start date of statement period (תאריך התחלה)
4. statement_period_end: End date of statement period (תאריך סיום)
5. opening_balance: Opening balance (יתרה פתיחה)
6. closing_balance: Closing balance (יתרה סגירה)
7. account_number: Bank account number (מספר חשבון)
8. document_date: Statement issue date (תאריך הנפקה)

OPTIONAL FIELDS:
9. total_deposits: Total deposits/credits (סה"כ הפקדות)
10. total_withdrawals: Total withdrawals/debits (סה"כ משיכות)
11. transaction_count: Number of transactions (מספר עסקאות)
12. average_balance: Average balance (יתרה ממוצעת)
13. regular_income_sources: Identified salary/income patterns (מקורות הכנסה קבועים)
14. regular_expenses: Identified recurring payments (הוצאות קבועות)

VALIDATION CONTEXT:
- Expected tenant name: {tenant_name or 'Not provided'}
- Expected tenant ID: {tenant_id or 'Not provided'}

DYNAMIC EXTRACTION RULES - ADAPT TO ANY FORMAT:
1. For account_holder_name: Look for the account owner's name anywhere in the document
2. For bank_name: Look for any Israeli bank name anywhere in the document
3. For statement_period: Look for any date range or period anywhere in the document
4. For balances: Look for opening and closing balances anywhere in the document
5. For account_number: Look for any account number anywhere in the document
6. For financial data: Look for deposits, withdrawals, transactions anywhere in the document

ADAPTIVE SEARCH STRATEGY:
- Account Holder Name: Look anywhere for the main person's name
- Bank Name: Look for any Israeli bank name anywhere in the document
- Statement Period: Look for any date ranges or periods anywhere
- Balances: Look for opening/closing balances anywhere
- Account Number: Look for any account number anywhere
- Financial Data: Look for deposits, withdrawals, transactions anywhere
- Be flexible with document layouts and formats

IMPORTANT: Bank statements can have various formats - be flexible and look anywhere for the required information.

INTELLIGENT EXTRACTION FOR ANY BANK STATEMENT FORMAT:
- This document could be from ANY Israeli bank - Leumi, Hapoalim, Mizrahi, Discount, etc.
- Use your knowledge of bank statements to extract data regardless of format
- Look for patterns in the numbers - balances are usually the largest numbers
- Deposits are usually positive numbers, withdrawals are usually negative
- Use mathematical logic to fill in missing financial data
- Look for Hebrew keywords like "יתרה", "הפקדה", "משיכה", "חשבון" even in fragmented text
- Use intelligent inference to fill missing data based on available information
- Be flexible with document layouts - bank statements can vary significantly
- Look for any name that could be the account holder
- Look for any bank information (names, logos, addresses)
- Use intelligent inference to fill missing data based on available information

IMPORTANT RULES:
1. Extract ALL required fields - missing fields will cause validation failure
2. Names should be in Hebrew if the document is in Hebrew
3. Dates should be in DD/MM/YYYY format
4. Financial amounts should be numeric values only
5. If a field is not found, mark it as null
6. Look for Hebrew labels like "שם בעל החשבון", "יתרה", "תאריך", etc.
7. Bank name is CRITICAL for bank statement validation
8. Financial data should be consistent and reasonable
9. Look for official bank logos and formatting
10. If you see any name in the document, try to determine if it's the account holder
11. Look for any bank information in the document
12. If OCR text is incomplete, use intelligent inference to fill missing financial data

Document text:
{text}

Return ONLY a JSON object with the extracted information. Do not include any explanations or additional text.
"""

    async def _validate_payslip_data(self, data: Dict[str, Any], tenant_name: str = None, tenant_id: str = None) -> Dict[str, Any]:
        """Validate extracted payslip data."""
        result = {
            "is_valid": True,
            "errors": [],
            "warnings": []
        }
        
        try:
            # Check required fields
            # Check for critical required fields
            critical_fields = [
                "employee_name", "employee_id", "company_name", 
                "gross_salary", "net_salary", "deductions"
            ]
            
            missing_critical = []
            for field in critical_fields:
                if not data.get(field):
                    missing_critical.append(field)
            
            if missing_critical:
                result["errors"].append(f"Missing critical fields: {', '.join(missing_critical)}")
                result["is_valid"] = False
            
            # Check for optional fields and add warnings
            optional_fields = ["pay_period", "basic_salary", "income_tax", "national_insurance", "health_insurance"]
            missing_optional = []
            for field in optional_fields:
                if not data.get(field):
                    missing_optional.append(field)
            
            if missing_optional:
                result["warnings"].append(f"Optional fields not found: {', '.join(missing_optional)}")
            
            # Validate payslip date (must be from last 3 months)
            pay_period = data.get("pay_period")
            if pay_period:
                date_validation = self._validate_payslip_date(pay_period)
                if not date_validation["is_valid"]:
                    result["errors"].append(f"Payslip date validation failed: {date_validation['error']}")
                    result["is_valid"] = False
                elif date_validation["warnings"]:
                    result["warnings"].extend(date_validation["warnings"])
            
            # Validate name match if tenant name provided
            if tenant_name and data.get("employee_name"):
                name_match = await self._names_match(data["employee_name"], tenant_name)
                if not name_match:
                    result["errors"].append(f"Name mismatch: extracted '{data['employee_name']}' vs expected '{tenant_name}'")
                    result["is_valid"] = False
            
            # Validate ID number if tenant ID provided
            if tenant_id and data.get("employee_id"):
                # Normalize both IDs to 9 digits (add leading zeros if needed)
                extracted_id = str(data["employee_id"]).strip().zfill(9)
                expected_id = str(tenant_id).strip().zfill(9)
                
                if extracted_id != expected_id:
                    result["errors"].append(f"ID mismatch: extracted '{data['employee_id']}' vs expected '{tenant_id}'")
                    result["is_valid"] = False
                else:
                    logger.info("ID numbers match after normalization", 
                               extra={"extracted_id": extracted_id, "expected_id": expected_id})
            
            # Validate salary reasonableness
            gross_salary = data.get("gross_salary")
            if gross_salary and isinstance(gross_salary, (int, float)):
                if gross_salary < 1000 or gross_salary > 100000:  # Reasonable salary range
                    result["warnings"].append(f"Salary amount seems unusual: {gross_salary}")
            
            # Validate financial consistency
            net_salary = data.get("net_salary")
            deductions = data.get("deductions")
            if gross_salary and net_salary and deductions:
                try:
                    # Convert to numbers for calculation
                    gross_num = float(str(gross_salary).replace(',', '').replace('₪', '').strip())
                    net_num = float(str(net_salary).replace(',', '').replace('₪', '').strip())
                    deductions_num = float(str(deductions).replace(',', '').replace('₪', '').strip())
                    
                    calculated_net = gross_num - deductions_num
                    if abs(calculated_net - net_num) > 100:  # Allow small rounding differences
                        result["warnings"].append("Financial data inconsistency detected")
                except (ValueError, TypeError):
                    result["warnings"].append("Could not validate financial consistency - invalid number format")
            
            logger.info("Payslip validation completed", extra={
                "is_valid": result["is_valid"],
                "errors_count": len(result["errors"]),
                "warnings_count": len(result["warnings"])
            })
            
        except Exception as e:
            logger.error("Error in payslip validation", extra={"error": str(e)})
            result["errors"].append(f"Validation error: {str(e)}")
            result["is_valid"] = False
        
        return result

    def _validate_payslip_date(self, pay_period: str) -> Dict[str, Any]:
        """Validate if payslip is from the last 3 months."""
        result = {
            "is_valid": True,
            "error": None,
            "warnings": []
        }
        
        try:
            import re
            
            # Parse Hebrew month names
            hebrew_months = {
                "ינואר": 1, "פברואר": 2, "מרץ": 3, "אפריל": 4, "מאי": 5, "יוני": 6,
                "יולי": 7, "אוגוסט": 8, "ספטמבר": 9, "אוקטובר": 10, "נובמבר": 11, "דצמבר": 12
            }
            
            # Extract month and year from pay_period
            # Format: "מאי 2025" or "May 2025"
            current_date = datetime.now()
            
            # Calculate 4 months ago to be more lenient (accept 4-5 month old payslips)
            # Go back 4 months from current date
            if current_date.month <= 4:
                three_months_ago = datetime(current_date.year - 1, current_date.month + 8, 1)
            else:
                three_months_ago = datetime(current_date.year, current_date.month - 4, 1)
            
            # Debug logging
            logger.info("Date validation debug", 
                       extra={
                           "current_date": current_date.strftime("%Y-%m-%d"),
                           "three_months_ago": three_months_ago.strftime("%Y-%m-%d"),
                           "pay_period": pay_period
                       })
            
            # Try to parse Hebrew format first
            for hebrew_month, month_num in hebrew_months.items():
                if hebrew_month in pay_period:
                    # Extract year
                    year_match = re.search(r'(\d{4})', pay_period)
                    if year_match:
                        year = int(year_match.group(1))
                        payslip_date = datetime(year, month_num, 1)
                        
                        if payslip_date < three_months_ago:
                            result["is_valid"] = False
                            result["error"] = f"Payslip is too old: {pay_period} (must be from last 4 months)"
                            return result
                        elif payslip_date < current_date - timedelta(days=60):
                            result["warnings"].append(f"Payslip is getting old: {pay_period}")
                        
                        return result
            
            # Try to parse English format
            english_months = {
                "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
                "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12
            }
            
            for english_month, month_num in english_months.items():
                if english_month.lower() in pay_period.lower():
                    year_match = re.search(r'(\d{4})', pay_period)
                    if year_match:
                        year = int(year_match.group(1))
                        payslip_date = datetime(year, month_num, 1)
                        
                        if payslip_date < three_months_ago:
                            result["is_valid"] = False
                            result["error"] = f"Payslip is too old: {pay_period} (must be from last 4 months)"
                            return result
                        elif payslip_date < datetime(current_date.year, current_date.month - 2, 1) if current_date.month > 2 else datetime(current_date.year - 1, current_date.month + 10, 1):
                            result["warnings"].append(f"Payslip is getting old: {pay_period}")
                        
                        return result
            
            # If we can't parse the date, add a warning
            result["warnings"].append(f"Could not parse payslip date: {pay_period}")
            
        except Exception as e:
            result["is_valid"] = False
            result["error"] = f"Date parsing error: {str(e)}"
        
        return result

    def _validate_pnl_date(self, period: str) -> Dict[str, Any]:
        """Validate if PNL is from the last 4 months."""
        result = {
            "is_valid": True,
            "error": None,
            "warnings": []
        }
        
        try:
            import re
            
            # Parse Hebrew month names
            hebrew_months = {
                "ינואר": 1, "פברואר": 2, "מרץ": 3, "אפריל": 4, "מאי": 5, "יוני": 6,
                "יולי": 7, "אוגוסט": 8, "ספטמבר": 9, "אוקטובר": 10, "נובמבר": 11, "דצמבר": 12
            }
            
            # Extract month and year from period
            current_date = datetime.now()
            
            # Calculate 4 months ago to be more lenient
            if current_date.month <= 4:
                four_months_ago = datetime(current_date.year - 1, current_date.month + 8, 1)
            else:
                four_months_ago = datetime(current_date.year, current_date.month - 4, 1)
            
            # Try to parse Hebrew format first
            for hebrew_month, month_num in hebrew_months.items():
                if hebrew_month in period:
                    year_match = re.search(r'(\d{4})', period)
                    if year_match:
                        year = int(year_match.group(1))
                        pnl_date = datetime(year, month_num, 1)
                        
                        if pnl_date < four_months_ago:
                            result["is_valid"] = False
                            result["error"] = f"PNL is too old: {period} (must be from last 4 months)"
                            return result
                        elif pnl_date < datetime(current_date.year, current_date.month - 2, 1) if current_date.month > 2 else datetime(current_date.year - 1, current_date.month + 10, 1):
                            result["warnings"].append(f"PNL is getting old: {period}")
                        
                        return result
            
            # If we can't parse the date, add a warning
            result["warnings"].append(f"Could not parse PNL date: {period}")
            
        except Exception as e:
            result["is_valid"] = False
            result["error"] = f"Date parsing error: {str(e)}"
        
        return result

    async def _validate_pnl_data(self, data: Dict[str, Any], tenant_name: str = None, tenant_id: str = None) -> Dict[str, Any]:
        """Validate extracted PNL data."""
        result = {
            "is_valid": True,
            "errors": [],
            "warnings": []
        }
        
        try:
            # Check required fields
            required_fields = [
                "business_name", "owner_name", "owner_id", "accountant_name",
                "accountant_signature", "period", "revenue", "expenses"
            ]
            
            missing_fields = []
            for field in required_fields:
                if not data.get(field):
                    missing_fields.append(field)
            
            if missing_fields:
                result["errors"].append(f"Missing required fields: {', '.join(missing_fields)}")
                result["is_valid"] = False
            
            # Check if net_income is missing and add warning (not error)
            if not data.get("net_income"):
                result["warnings"].append("Net income not found - this is optional for PNL documents")
            
            # Validate PNL date (must be from last 4 months)
            period = data.get("period")
            if period:
                date_validation = self._validate_pnl_date(period)
                if not date_validation["is_valid"]:
                    result["errors"].append(f"PNL date validation failed: {date_validation['error']}")
                    result["is_valid"] = False
                elif date_validation["warnings"]:
                    result["warnings"].extend(date_validation["warnings"])
            
            # Validate name match if tenant name provided
            if tenant_name and data.get("owner_name"):
                name_match = await self._names_match(data["owner_name"], tenant_name)
                if not name_match:
                    result["errors"].append(f"Name mismatch: extracted '{data['owner_name']}' vs expected '{tenant_name}'")
                    result["is_valid"] = False
            
            # Validate ID number if tenant ID provided
            if tenant_id and data.get("owner_id"):
                # Normalize both IDs to 9 digits (add leading zeros if needed)
                extracted_id = str(data["owner_id"]).strip().zfill(9)
                expected_id = str(tenant_id).strip().zfill(9)
                
                if extracted_id != expected_id:
                    result["errors"].append(f"ID mismatch: extracted '{data['owner_id']}' vs expected '{tenant_id}'")
                    result["is_valid"] = False
                else:
                    logger.info("ID numbers match after normalization", 
                               extra={"extracted_id": extracted_id, "expected_id": expected_id})
            
            # Validate accountant signature
            accountant_signature = data.get("accountant_signature", "").lower()
            if not accountant_signature or accountant_signature not in ["yes", "כן", "true", "1"]:
                result["errors"].append("Accountant signature is required for PNL validation")
                result["is_valid"] = False
            
            # Validate financial consistency
            revenue = data.get("revenue")
            expenses = data.get("expenses")
            net_income = data.get("net_income")
            
            if revenue and expenses and net_income:
                try:
                    # Convert to numbers for calculation
                    revenue_num = float(str(revenue).replace(',', '').replace('₪', '').strip())
                    expenses_num = float(str(expenses).replace(',', '').replace('₪', '').strip())
                    net_income_num = float(str(net_income).replace(',', '').replace('₪', '').strip())
                    
                    calculated_net = revenue_num - expenses_num
                    if abs(calculated_net - net_income_num) > 100:  # Allow small rounding differences
                        result["warnings"].append("Financial data inconsistency detected")
                except (ValueError, TypeError):
                    result["warnings"].append("Could not validate financial consistency - invalid number format")
            
            # Validate financial reasonableness
            if revenue and isinstance(revenue, (int, float)):
                if revenue < 0:
                    result["warnings"].append("Negative revenue detected")
                elif revenue > 1000000:  # Very high revenue
                    result["warnings"].append("Unusually high revenue amount")
            
            logger.info("PNL validation completed", extra={
                "is_valid": result["is_valid"],
                "errors_count": len(result["errors"]),
                "warnings_count": len(result["warnings"])
            })
            
        except Exception as e:
            logger.error("Error in PNL validation", extra={"error": str(e)})
            result["errors"].append(f"Validation error: {str(e)}")
            result["is_valid"] = False
        
        return result

    async def _validate_bank_statement_data(self, data: Dict[str, Any], tenant_name: str = None, tenant_id: str = None) -> Dict[str, Any]:
        """Validate extracted bank statement data."""
        result = {
            "is_valid": True,
            "errors": [],
            "warnings": []
        }
        
        try:
            # Check required fields
            required_fields = [
                "account_holder_name", "bank_name", "statement_period_start",
                "statement_period_end", "account_number", "document_date"
            ]
            
            missing_fields = []
            for field in required_fields:
                if not data.get(field):
                    missing_fields.append(field)
            
            if missing_fields:
                result["errors"].append(f"Missing required fields: {', '.join(missing_fields)}")
                result["is_valid"] = False
            
            # Check for missing balance fields (optional but important)
            if not data.get("opening_balance"):
                result["warnings"].append("Opening balance not found - this is optional for bank statements")
            if not data.get("closing_balance"):
                result["warnings"].append("Closing balance not found - this is optional for bank statements")
            
            # Validate name match
            if tenant_name and data.get("account_holder_name"):
                name_validation = await self._validate_name(data["account_holder_name"], tenant_name)
                if not name_validation["is_valid"]:
                    result["errors"].extend(name_validation["errors"])
                    result["is_valid"] = False
                else:
                    result["warnings"].extend(name_validation["warnings"])
            
            # Validate bank statement date (must be from last 4 months)
            statement_period = f"{data.get('statement_period_start', '')} - {data.get('statement_period_end', '')}"
            if statement_period.strip() != " - ":
                date_validation = self._validate_bank_statement_date(statement_period)
                if not date_validation["is_valid"]:
                    result["errors"].append(f"Bank statement date validation failed: {date_validation['error']}")
                    result["is_valid"] = False
                elif date_validation["warnings"]:
                    result["warnings"].extend(date_validation["warnings"])
            
            # Validate bank name
            bank_name = data.get("bank_name", "").lower()
            israeli_banks = ["לאומי", "הפועלים", "מזרחי", "דיסקונט", "יגואר", "leumi", "hapoalim", "mizrahi", "discount", "jaguar"]
            if bank_name and not any(bank in bank_name for bank in israeli_banks):
                result["warnings"].append(f"Bank name '{data.get('bank_name')}' may not be a recognized Israeli bank")
            
            # Validate balance consistency
            try:
                opening_balance = float(str(data.get("opening_balance", 0)).replace(',', '').replace('₪', '').strip())
                closing_balance = float(str(data.get("closing_balance", 0)).replace(',', '').replace('₪', '').strip())
                
                if opening_balance != 0 and closing_balance != 0:
                    # Basic balance validation - closing should be reasonable compared to opening
                    balance_ratio = abs(closing_balance / opening_balance) if opening_balance != 0 else 1
                    if balance_ratio > 10 or balance_ratio < 0.1:
                        result["warnings"].append("Unusual balance ratio detected - please verify statement authenticity")
                        
            except (ValueError, TypeError):
                result["warnings"].append("Could not validate balance consistency")
            
            # Validate financial data consistency
            try:
                total_deposits = data.get("total_deposits")
                total_withdrawals = data.get("total_withdrawals")
                
                if total_deposits and total_withdrawals:
                    deposits = float(str(total_deposits).replace(',', '').replace('₪', '').strip())
                    withdrawals = float(str(total_withdrawals).replace(',', '').replace('₪', '').strip())
                    
                    if deposits < 0 or withdrawals > 0:
                        result["warnings"].append("Financial data inconsistency detected")
                        
            except (ValueError, TypeError):
                pass  # Optional fields, don't fail validation
            
            logger.info("Bank statement validation completed", 
                       extra={"is_valid": result["is_valid"], "errors": len(result["errors"]), "warnings": len(result["warnings"])})
            
        except Exception as e:
            logger.error("Error in bank statement validation", extra={"error": str(e)})
            result["errors"].append(f"Validation error: {str(e)}")
            result["is_valid"] = False
        
        return result

    def _validate_bank_statement_date(self, statement_period: str) -> Dict[str, Any]:
        """Validate if bank statement is from the last 5 months (3-5 months acceptable)."""
        result = {
            "is_valid": True,
            "error": None,
            "warnings": []
        }
        
        try:
            current_date = datetime.now()
            # Calculate 5 months ago (maximum acceptable age)
            five_months_ago = current_date.replace(day=1)
            for _ in range(5):
                if five_months_ago.month == 1:
                    five_months_ago = five_months_ago.replace(year=five_months_ago.year - 1, month=12)
                else:
                    five_months_ago = five_months_ago.replace(month=five_months_ago.month - 1)
            
            # Try to extract end date from period
            period_parts = statement_period.split(' - ')
            if len(period_parts) >= 2:
                end_date_str = period_parts[-1].strip()
                
                # Try to parse DD/MM/YYYY format
                try:
                    day, month, year = map(int, end_date_str.split('/'))
                    statement_date = datetime(year, month, day)
                    
                    if statement_date < five_months_ago:
                        result["is_valid"] = False
                        result["error"] = f"Bank statement is too old: {statement_period} (must be from last 5 months)"
                        return result
                    elif statement_date < current_date - timedelta(days=90):
                        result["warnings"].append(f"Bank statement is getting old: {statement_period}")
                    
                    return result
                except ValueError:
                    pass
            
            # If we can't parse the date, add a warning
            result["warnings"].append(f"Could not parse bank statement date: {statement_period}")
            
        except Exception as e:
            result["is_valid"] = False
            result["error"] = f"Date parsing error: {str(e)}"
        
        return result


# Global instance
vertex_ai_document_parser = VertexAIDocumentParser()
