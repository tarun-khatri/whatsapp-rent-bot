import re
import logging
import structlog
from typing import Optional

logger = structlog.get_logger(__name__)


def normalize_phone_number(phone: str) -> str:
    """
    Convert various phone formats to international format.
    
    Handles formats like:
    - Israeli: 0501234567 -> +972501234567
    - Indian: 917775094760 -> +917775094760
    - International: +972501234567 -> +972501234567
    
    Returns:
        str: Normalized phone number in international format
    """
    try:
        # Remove all non-digit characters except +
        cleaned = re.sub(r'[^\d+]', '', phone)
        
        # Remove leading + if present
        if cleaned.startswith('+'):
            cleaned = cleaned[1:]
        
        # Handle different phone number formats
        if cleaned.startswith('972'):
            # Israeli number with country code
            return f"+{cleaned}"
        elif cleaned.startswith('91'):
            # Indian number with country code
            return f"+{cleaned}"
        elif cleaned.startswith('0'):
            # Israeli format starting with 0
            # Remove the leading 0 and add 972
            return f"+972{cleaned[1:]}"
        elif len(cleaned) == 9 and cleaned.startswith('5'):
            # Israeli mobile number without leading 0
            return f"+972{cleaned}"
        elif len(cleaned) == 10 and cleaned.startswith('0'):
            # Israeli landline number
            return f"+972{cleaned[1:]}"
        elif len(cleaned) == 10 and cleaned.startswith('9'):
            # Indian mobile number without country code
            return f"+91{cleaned}"
        else:
            # Try to handle other formats - return as is with +
            if len(cleaned) >= 9:
                return f"+{cleaned}"
            else:
                logger.warning("Unable to normalize phone number", phone=phone, cleaned=cleaned)
                return phone  # Return original if can't normalize
        
    except Exception as e:
        logger.error("Error normalizing phone number", phone=phone, error=str(e))
        return phone


def validate_israeli_phone(phone: str) -> bool:
    """
    Validate if a phone number is a valid Israeli phone number.
    
    Args:
        phone (str): Phone number to validate
        
    Returns:
        bool: True if valid Israeli phone number
    """
    try:
        normalized = normalize_phone_number(phone)
        
        # Check if it starts with +972
        if not normalized.startswith('+972'):
            return False
        
        # Remove country code
        number = normalized[4:]
        
        # Israeli mobile numbers are 9 digits starting with 5
        if len(number) == 9 and number.startswith('5'):
            return True
        
        # Israeli landline numbers are 8-9 digits
        if len(number) in [8, 9]:
            return True
        
        return False
        
    except Exception as e:
        logger.error("Error validating Israeli phone number", phone=phone, error=str(e))
        return False


def format_phone_for_display(phone: str) -> str:
    """
    Format phone number for display purposes.
    
    Args:
        phone (str): Phone number in +972XXXXXXXXX format
        
    Returns:
        str: Formatted phone number for display
    """
    try:
        normalized = normalize_phone_number(phone)
        
        if normalized.startswith('+972'):
            number = normalized[4:]
            if len(number) == 9 and number.startswith('5'):
                # Mobile number: +972 50 123 4567
                return f"+972 {number[:2]} {number[2:5]} {number[5:]}"
            else:
                # Landline: +972 3 123 4567
                return f"+972 {number[:1]} {number[1:4]} {number[4:]}"
        
        return phone
        
    except Exception as e:
        logger.error("Error formatting phone for display", phone=phone, error=str(e))
        return phone


def extract_phone_from_whatsapp_id(wa_id: str) -> Optional[str]:
    """
    Extract phone number from WhatsApp ID.
    
    WhatsApp IDs are typically in the format: 972501234567@c.us or 917775094760@c.us
    
    Args:
        wa_id (str): WhatsApp ID
        
    Returns:
        Optional[str]: Extracted phone number or None if invalid
    """
    try:
        # Remove @c.us suffix if present
        if '@' in wa_id:
            phone_part = wa_id.split('@')[0]
        else:
            phone_part = wa_id
        
        # Normalize the phone number
        normalized = normalize_phone_number(phone_part)
        
        # Accept any valid international phone number (not just Israeli)
        if normalized and len(normalized) >= 10 and normalized.startswith('+'):
            return normalized
        
        return None
        
    except Exception as e:
        logger.error("Error extracting phone from WhatsApp ID", wa_id=wa_id, error=str(e))
        return None


def is_mobile_number(phone: str) -> bool:
    """
    Check if a phone number is a mobile number.
    
    Args:
        phone (str): Phone number to check
        
    Returns:
        bool: True if mobile number
    """
    try:
        normalized = normalize_phone_number(phone)
        
        if normalized.startswith('+972'):
            number = normalized[4:]
            # Israeli mobile numbers are 9 digits starting with 5
            return len(number) == 9 and number.startswith('5')
        
        return False
        
    except Exception as e:
        logger.error("Error checking if mobile number", phone=phone, error=str(e))
        return False


def get_phone_operator(phone: str) -> Optional[str]:
    """
    Get the mobile operator for an Israeli phone number.
    
    Args:
        phone (str): Phone number
        
    Returns:
        Optional[str]: Operator name or None if not mobile
    """
    try:
        if not is_mobile_number(phone):
            return None
        
        normalized = normalize_phone_number(phone)
        number = normalized[4:]  # Remove +972
        
        # Israeli mobile operator prefixes
        operator_prefixes = {
            '50': 'Partner',
            '51': 'Partner',
            '52': 'Cellcom',
            '53': 'Cellcom',
            '54': 'Pelephone',
            '55': 'Pelephone',
            '56': 'Hot Mobile',
            '57': 'Hot Mobile',
            '58': 'Golan Telecom',
            '59': 'Golan Telecom'
        }
        
        prefix = number[:2]
        return operator_prefixes.get(prefix, 'Unknown')
        
    except Exception as e:
        logger.error("Error getting phone operator", phone=phone, error=str(e))
        return None
