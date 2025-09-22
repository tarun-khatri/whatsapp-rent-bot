import re
import structlog
from typing import Dict, Any, Optional, List
from datetime import datetime, date
import json

logger = structlog.get_logger(__name__)


class ValidationError(Exception):
    """Custom exception for validation errors."""
    pass


def validate_phone_number(phone: str) -> bool:
    """
    Validate Israeli phone number format.
    
    Args:
        phone: Phone number to validate
        
    Returns:
        bool: True if valid
    """
    try:
        # Remove all non-digit characters except +
        cleaned = re.sub(r'[^\d+]', '', phone)
        
        # Check if it starts with +972
        if not cleaned.startswith('+972'):
            return False
        
        # Remove country code
        number = cleaned[4:]
        
        # Israeli mobile numbers are 9 digits starting with 5
        if len(number) == 9 and number.startswith('5'):
            return True
        
        # Israeli landline numbers are 8-9 digits
        if len(number) in [8, 9]:
            return True
        
        return False
        
    except Exception as e:
        logger.error("Error validating phone number", phone=phone, error=str(e))
        return False


def validate_email(email: str) -> bool:
    """
    Validate email address format.
    
    Args:
        email: Email to validate
        
    Returns:
        bool: True if valid
    """
    try:
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return re.match(pattern, email) is not None
    except Exception as e:
        logger.error("Error validating email", email=email, error=str(e))
        return False


def validate_id_number(id_number: str) -> bool:
    """
    Validate Israeli ID number (Teudat Zehut).
    
    Args:
        id_number: ID number to validate
        
    Returns:
        bool: True if valid
    """
    try:
        # Remove non-digit characters
        cleaned = re.sub(r'[^\d]', '', id_number)
        
        # Israeli ID numbers are 9 digits
        if len(cleaned) != 9:
            return False
        
        # Check if all digits
        if not cleaned.isdigit():
            return False
        
        # Validate using Israeli ID checksum algorithm
        return _validate_israeli_id_checksum(cleaned)
        
    except Exception as e:
        logger.error("Error validating ID number", id_number=id_number, error=str(e))
        return False


def _validate_israeli_id_checksum(id_number: str) -> bool:
    """
    Validate Israeli ID number using checksum algorithm.
    
    Args:
        id_number: 9-digit ID number
        
    Returns:
        bool: True if valid checksum
    """
    try:
        # Convert to list of integers
        digits = [int(d) for d in id_number]
        
        # Apply checksum algorithm
        total = 0
        for i, digit in enumerate(digits[:-1]):  # Exclude last digit (checksum)
            # Multiply by 1 or 2 based on position
            multiplier = 2 if i % 2 == 1 else 1
            result = digit * multiplier
            
            # If result is 10 or more, add the digits
            if result >= 10:
                result = (result // 10) + (result % 10)
            
            total += result
        
        # Calculate checksum
        checksum = (10 - (total % 10)) % 10
        
        return checksum == digits[-1]
        
    except Exception as e:
        logger.error("Error validating ID checksum", id_number=id_number, error=str(e))
        return False


def validate_date_format(date_str: str, format_str: str = "%d/%m/%Y") -> bool:
    """
    Validate date format.
    
    Args:
        date_str: Date string to validate
        format_str: Expected format
        
    Returns:
        bool: True if valid
    """
    try:
        datetime.strptime(date_str, format_str)
        return True
    except ValueError:
        return False
    except Exception as e:
        logger.error("Error validating date format", date_str=date_str, error=str(e))
        return False


def validate_amount(amount: str) -> bool:
    """
    Validate monetary amount.
    
    Args:
        amount: Amount string to validate
        
    Returns:
        bool: True if valid
    """
    try:
        # Remove currency symbols and commas
        cleaned = re.sub(r'[₪,$,\s]', '', amount)
        
        # Check if it's a valid number
        float(cleaned)
        return True
        
    except ValueError:
        return False
    except Exception as e:
        logger.error("Error validating amount", amount=amount, error=str(e))
        return False


def validate_document_type(file_name: str, expected_type: str) -> bool:
    """
    Validate document file type.
    
    Args:
        file_name: Name of the file
        expected_type: Expected document type
        
    Returns:
        bool: True if valid
    """
    try:
        # Get file extension
        extension = file_name.lower().split('.')[-1] if '.' in file_name else ''
        
        # Allowed extensions
        allowed_extensions = ['pdf', 'jpg', 'jpeg', 'png', 'gif']
        
        if extension not in allowed_extensions:
            return False
        
        # Additional validation based on expected type
        if expected_type == "id_card":
            # ID cards are typically images
            return extension in ['jpg', 'jpeg', 'png', 'gif']
        elif expected_type == "payslips":
            # Payslips can be PDF or images
            return extension in ['pdf', 'jpg', 'jpeg', 'png']
        elif expected_type == "bank_statements":
            # Bank statements are typically PDF
            return extension in ['pdf', 'jpg', 'jpeg', 'png']
        elif expected_type == "sephach":
            # Sephach forms can be PDF or images
            return extension in ['pdf', 'jpg', 'jpeg', 'png']
        
        return True
        
    except Exception as e:
        logger.error("Error validating document type", file_name=file_name, expected_type=expected_type, error=str(e))
        return False


def validate_file_size(file_size: int, max_size_mb: int = 16) -> bool:
    """
    Validate file size.
    
    Args:
        file_size: File size in bytes
        max_size_mb: Maximum size in MB
        
    Returns:
        bool: True if valid
    """
    try:
        max_size_bytes = max_size_mb * 1024 * 1024
        return file_size <= max_size_bytes
    except Exception as e:
        logger.error("Error validating file size", file_size=file_size, error=str(e))
        return False


def validate_tenant_data(tenant_data: Dict[str, Any]) -> List[str]:
    """
    Validate tenant data.
    
    Args:
        tenant_data: Tenant data dictionary
        
    Returns:
        List of validation errors (empty if valid)
    """
    errors = []
    
    try:
        # Required fields
        required_fields = [
            'full_name', 'phone_number', 'property_name', 
            'apartment_number', 'number_of_rooms', 
            'monthly_rent_amount', 'move_in_date'
        ]
        
        for field in required_fields:
            if not tenant_data.get(field):
                errors.append(f"Missing required field: {field}")
        
        # Validate phone number
        if tenant_data.get('phone_number') and not validate_phone_number(tenant_data['phone_number']):
            errors.append("Invalid phone number format")
        
        # Validate rent amount
        if tenant_data.get('monthly_rent_amount'):
            try:
                rent = float(tenant_data['monthly_rent_amount'])
                if rent <= 0:
                    errors.append("Monthly rent amount must be positive")
            except (ValueError, TypeError):
                errors.append("Invalid monthly rent amount format")
        
        # Validate number of rooms
        if tenant_data.get('number_of_rooms'):
            try:
                rooms = int(tenant_data['number_of_rooms'])
                if rooms <= 0:
                    errors.append("Number of rooms must be positive")
            except (ValueError, TypeError):
                errors.append("Invalid number of rooms format")
        
        # Validate move-in date
        if tenant_data.get('move_in_date'):
            if isinstance(tenant_data['move_in_date'], str):
                if not validate_date_format(tenant_data['move_in_date']):
                    errors.append("Invalid move-in date format (expected DD/MM/YYYY)")
            elif not isinstance(tenant_data['move_in_date'], date):
                errors.append("Invalid move-in date type")
        
        # Validate number of children
        if tenant_data.get('number_of_children') is not None:
            try:
                children = int(tenant_data['number_of_children'])
                if children < 0:
                    errors.append("Number of children cannot be negative")
            except (ValueError, TypeError):
                errors.append("Invalid number of children format")
        
        return errors
        
    except Exception as e:
        logger.error("Error validating tenant data", error=str(e))
        return [f"Validation error: {str(e)}"]


def validate_guarantor_data(guarantor_data: Dict[str, Any]) -> List[str]:
    """
    Validate guarantor data.
    
    Args:
        guarantor_data: Guarantor data dictionary
        
    Returns:
        List of validation errors (empty if valid)
    """
    errors = []
    
    try:
        # Required fields
        required_fields = ['full_name', 'phone_number']
        
        for field in required_fields:
            if not guarantor_data.get(field):
                errors.append(f"Missing required field: {field}")
        
        # Validate phone number
        if guarantor_data.get('phone_number') and not validate_phone_number(guarantor_data['phone_number']):
            errors.append("Invalid guarantor phone number format")
        
        # Validate guarantor number
        if guarantor_data.get('guarantor_number'):
            try:
                guarantor_num = int(guarantor_data['guarantor_number'])
                if guarantor_num not in [1, 2]:
                    errors.append("Guarantor number must be 1 or 2")
            except (ValueError, TypeError):
                errors.append("Invalid guarantor number format")
        
        return errors
        
    except Exception as e:
        logger.error("Error validating guarantor data", error=str(e))
        return [f"Validation error: {str(e)}"]


def validate_conversation_state(state_data: Dict[str, Any]) -> List[str]:
    """
    Validate conversation state data.
    
    Args:
        state_data: Conversation state dictionary
        
    Returns:
        List of validation errors (empty if valid)
    """
    errors = []
    
    try:
        # Validate current state
        valid_states = ['GREETING', 'CONFIRMATION', 'PERSONAL_INFO', 'DOCUMENTS', 'GUARANTOR_1', 'GUARANTOR_2', 'COMPLETED']
        current_state = state_data.get('current_state')
        
        if current_state and current_state not in valid_states:
            errors.append(f"Invalid conversation state: {current_state}")
        
        # Validate context data
        context_data = state_data.get('context_data', {})
        if not isinstance(context_data, dict):
            errors.append("Context data must be a dictionary")
        
        # Validate last message time
        last_message_time = state_data.get('last_message_time')
        if last_message_time:
            if isinstance(last_message_time, str):
                try:
                    datetime.fromisoformat(last_message_time.replace('Z', '+00:00'))
                except ValueError:
                    errors.append("Invalid last message time format")
            elif not isinstance(last_message_time, datetime):
                errors.append("Invalid last message time type")
        
        return errors
        
    except Exception as e:
        logger.error("Error validating conversation state", error=str(e))
        return [f"Validation error: {str(e)}"]


def sanitize_input(text: str) -> str:
    """
    Sanitize user input to prevent injection attacks.
    
    Args:
        text: Input text to sanitize
        
    Returns:
        Sanitized text
    """
    try:
        if not text:
            return ""
        
        # Remove potentially dangerous characters
        sanitized = re.sub(r'[<>"\']', '', text)
        
        # Limit length
        if len(sanitized) > 1000:
            sanitized = sanitized[:1000]
        
        return sanitized.strip()
        
    except Exception as e:
        logger.error("Error sanitizing input", error=str(e))
        return ""


def validate_json_data(json_str: str) -> bool:
    """
    Validate JSON string format.
    
    Args:
        json_str: JSON string to validate
        
    Returns:
        bool: True if valid JSON
    """
    try:
        json.loads(json_str)
        return True
    except (json.JSONDecodeError, TypeError):
        return False
    except Exception as e:
        logger.error("Error validating JSON data", error=str(e))
        return False


def validate_document_processing_result(result: Dict[str, Any]) -> bool:
    """
    Validate document processing result.
    
    Args:
        result: Document processing result dictionary
        
    Returns:
        bool: True if valid result
    """
    try:
        # Check required fields
        required_fields = ['extracted_data', 'validation_result', 'processing_status', 'confidence_score']
        
        for field in required_fields:
            if field not in result:
                return False
        
        # Validate confidence score
        confidence = result.get('confidence_score', 0)
        if not isinstance(confidence, (int, float)) or confidence < 0 or confidence > 1:
            return False
        
        # Validate processing status
        valid_statuses = ['pending', 'processing', 'validated', 'rejected', 'error']
        status = result.get('processing_status')
        if status not in valid_statuses:
            return False
        
        # Validate validation result structure
        validation_result = result.get('validation_result', {})
        if not isinstance(validation_result, dict):
            return False
        
        return True
        
    except Exception as e:
        logger.error("Error validating document processing result", error=str(e))
        return False
