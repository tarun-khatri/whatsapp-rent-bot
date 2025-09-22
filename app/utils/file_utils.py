import os
import re
import hashlib
import mimetypes
import structlog
from typing import Optional, Dict, Any, Tuple
from datetime import datetime
import uuid

logger = structlog.get_logger(__name__)


def generate_unique_filename(original_filename: str, prefix: str = "") -> str:
    """
    Generate a unique filename with timestamp and UUID.
    
    Args:
        original_filename: Original filename
        prefix: Optional prefix for the filename
        
    Returns:
        Unique filename
    """
    try:
        # Get file extension
        name, ext = os.path.splitext(original_filename)
        
        # Generate unique identifier
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        
        # Create unique filename
        if prefix:
            unique_filename = f"{prefix}_{timestamp}_{unique_id}{ext}"
        else:
            unique_filename = f"{timestamp}_{unique_id}{ext}"
        
        return unique_filename
        
    except Exception as e:
        logger.error("Error generating unique filename", original_filename=original_filename, error=str(e))
        return f"file_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"


def get_file_extension(filename: str) -> str:
    """
    Get file extension from filename.
    
    Args:
        filename: Filename to extract extension from
        
    Returns:
        File extension (without dot)
    """
    try:
        _, ext = os.path.splitext(filename)
        return ext.lower().lstrip('.')
    except Exception as e:
        logger.error("Error getting file extension", filename=filename, error=str(e))
        return ""


def get_mime_type(filename: str) -> str:
    """
    Get MIME type for a file.
    
    Args:
        filename: Filename to get MIME type for
        
    Returns:
        MIME type string
    """
    try:
        mime_type, _ = mimetypes.guess_type(filename)
        return mime_type or "application/octet-stream"
    except Exception as e:
        logger.error("Error getting MIME type", filename=filename, error=str(e))
        return "application/octet-stream"


def calculate_file_hash(file_data: bytes, algorithm: str = "sha256") -> str:
    """
    Calculate hash of file data.
    
    Args:
        file_data: File data as bytes
        algorithm: Hash algorithm to use
        
    Returns:
        Hash string
    """
    try:
        if algorithm == "md5":
            hash_obj = hashlib.md5()
        elif algorithm == "sha1":
            hash_obj = hashlib.sha1()
        elif algorithm == "sha256":
            hash_obj = hashlib.sha256()
        else:
            raise ValueError(f"Unsupported hash algorithm: {algorithm}")
        
        hash_obj.update(file_data)
        return hash_obj.hexdigest()
        
    except Exception as e:
        logger.error("Error calculating file hash", algorithm=algorithm, error=str(e))
        return ""


def validate_file_signature(file_data: bytes, filename: str) -> bool:
    """
    Validate file signature against expected file type.
    
    Args:
        file_data: File data as bytes
        filename: Original filename
        
    Returns:
        bool: True if signature matches expected type
    """
    try:
        extension = get_file_extension(filename).lower()
        
        # Check file signatures
        if extension in ['jpg', 'jpeg']:
            return file_data.startswith(b'\xff\xd8\xff')
        elif extension == 'png':
            return file_data.startswith(b'\x89PNG')
        elif extension == 'pdf':
            return file_data.startswith(b'%PDF')
        elif extension == 'gif':
            return file_data.startswith(b'GIF8')
        elif extension == 'bmp':
            return file_data.startswith(b'BM')
        elif extension == 'tiff':
            return file_data.startswith(b'II*\x00') or file_data.startswith(b'MM\x00*')
        else:
            # For unknown extensions, assume valid
            return True
            
    except Exception as e:
        logger.error("Error validating file signature", filename=filename, error=str(e))
        return False


def get_file_info(file_data: bytes, filename: str) -> Dict[str, Any]:
    """
    Get comprehensive file information.
    
    Args:
        file_data: File data as bytes
        filename: Original filename
        
    Returns:
        Dictionary with file information
    """
    try:
        file_size = len(file_data)
        extension = get_file_extension(filename)
        mime_type = get_mime_type(filename)
        file_hash = calculate_file_hash(file_data)
        
        # Validate file signature
        signature_valid = validate_file_signature(file_data, filename)
        
        return {
            "filename": filename,
            "size": file_size,
            "extension": extension,
            "mime_type": mime_type,
            "hash": file_hash,
            "signature_valid": signature_valid,
            "created_at": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error("Error getting file info", filename=filename, error=str(e))
        return {
            "filename": filename,
            "size": 0,
            "extension": "",
            "mime_type": "application/octet-stream",
            "hash": "",
            "signature_valid": False,
            "created_at": datetime.utcnow().isoformat()
        }


def format_file_size(size_bytes: int) -> str:
    """
    Format file size in human-readable format.
    
    Args:
        size_bytes: File size in bytes
        
    Returns:
        Formatted file size string
    """
    try:
        if size_bytes == 0:
            return "0 B"
        
        size_names = ["B", "KB", "MB", "GB", "TB"]
        i = 0
        size = float(size_bytes)
        
        while size >= 1024.0 and i < len(size_names) - 1:
            size /= 1024.0
            i += 1
        
        return f"{size:.1f} {size_names[i]}"
        
    except Exception as e:
        logger.error("Error formatting file size", size_bytes=size_bytes, error=str(e))
        return "Unknown"


def is_image_file(filename: str) -> bool:
    """
    Check if file is an image.
    
    Args:
        filename: Filename to check
        
    Returns:
        bool: True if image file
    """
    try:
        extension = get_file_extension(filename).lower()
        image_extensions = ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff', 'webp']
        return extension in image_extensions
    except Exception as e:
        logger.error("Error checking if image file", filename=filename, error=str(e))
        return False


def is_document_file(filename: str) -> bool:
    """
    Check if file is a document.
    
    Args:
        filename: Filename to check
        
    Returns:
        bool: True if document file
    """
    try:
        extension = get_file_extension(filename).lower()
        document_extensions = ['pdf', 'doc', 'docx', 'txt', 'rtf']
        return extension in document_extensions
    except Exception as e:
        logger.error("Error checking if document file", filename=filename, error=str(e))
        return False


def is_supported_file_type(filename: str) -> bool:
    """
    Check if file type is supported by the system.
    
    Args:
        filename: Filename to check
        
    Returns:
        bool: True if supported
    """
    try:
        extension = get_file_extension(filename).lower()
        supported_extensions = [
            'jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff', 'webp',  # Images
            'pdf', 'doc', 'docx', 'txt', 'rtf'  # Documents
        ]
        return extension in supported_extensions
    except Exception as e:
        logger.error("Error checking if supported file type", filename=filename, error=str(e))
        return False


def create_document_filename(tenant_name: str, document_type: str, file_extension: str) -> str:
    """
    Create standardized document filename.
    
    Args:
        tenant_name: Tenant's name
        document_type: Type of document
        file_extension: File extension
        
    Returns:
        Standardized filename
    """
    try:
        # Clean tenant name
        clean_name = "".join(c for c in tenant_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
        clean_name = clean_name.replace(' ', '_')
        
        # Create filename
        timestamp = datetime.utcnow().strftime("%Y%m%d")
        filename = f"{document_type}_{clean_name}_{timestamp}.{file_extension}"
        
        return filename
        
    except Exception as e:
        logger.error("Error creating document filename", tenant_name=tenant_name, document_type=document_type, error=str(e))
        return f"{document_type}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.{file_extension}"


def get_document_type_from_filename(filename: str) -> Optional[str]:
    """
    Infer document type from filename.
    
    Args:
        filename: Filename to analyze
        
    Returns:
        Document type or None if cannot determine
    """
    try:
        filename_lower = filename.lower()
        
        # Check for document type keywords
        if any(keyword in filename_lower for keyword in ['id', 'identity', 'teudat', 'zehut']):
            return 'id_card'
        elif any(keyword in filename_lower for keyword in ['sephach', 'appendix', 'form']):
            return 'sephach'
        elif any(keyword in filename_lower for keyword in ['payslip', 'salary', 'wage', 'pay']):
            return 'payslips'
        elif any(keyword in filename_lower for keyword in ['bank', 'statement', 'account']):
            return 'bank_statements'
        
        return None
        
    except Exception as e:
        logger.error("Error getting document type from filename", filename=filename, error=str(e))
        return None


def validate_file_for_processing(file_data: bytes, filename: str, max_size_mb: int = 16) -> Tuple[bool, str]:
    """
    Validate file for processing.
    
    Args:
        file_data: File data as bytes
        filename: Original filename
        max_size_mb: Maximum file size in MB
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        # Check file size
        file_size_mb = len(file_data) / (1024 * 1024)
        if file_size_mb > max_size_mb:
            return False, f"File size ({file_size_mb:.1f}MB) exceeds maximum allowed size ({max_size_mb}MB)"
        
        # Check if file type is supported
        if not is_supported_file_type(filename):
            return False, f"File type '{get_file_extension(filename)}' is not supported"
        
        # Check file signature
        if not validate_file_signature(file_data, filename):
            return False, "File signature does not match expected file type"
        
        # Check if file is not empty
        if len(file_data) == 0:
            return False, "File is empty"
        
        return True, ""
        
    except Exception as e:
        logger.error("Error validating file for processing", filename=filename, error=str(e))
        return False, f"File validation error: {str(e)}"


def extract_text_from_filename(filename: str) -> str:
    """
    Extract meaningful text from filename for search purposes.
    
    Args:
        filename: Filename to extract text from
        
    Returns:
        Extracted text
    """
    try:
        # Remove file extension
        name_without_ext = os.path.splitext(filename)[0]
        
        # Remove common separators and replace with spaces
        text = re.sub(r'[_-]', ' ', name_without_ext)
        
        # Remove numbers and special characters
        text = re.sub(r'[^a-zA-Z\s]', '', text)
        
        # Clean up multiple spaces
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text
        
    except Exception as e:
        logger.error("Error extracting text from filename", filename=filename, error=str(e))
        return ""


def get_file_category(filename: str) -> str:
    """
    Get file category based on extension.
    
    Args:
        filename: Filename to categorize
        
    Returns:
        File category
    """
    try:
        extension = get_file_extension(filename).lower()
        
        if extension in ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff', 'webp']:
            return 'image'
        elif extension in ['pdf', 'doc', 'docx', 'txt', 'rtf']:
            return 'document'
        elif extension in ['mp3', 'wav', 'ogg', 'm4a']:
            return 'audio'
        elif extension in ['mp4', 'avi', 'mov', 'wmv', 'flv']:
            return 'video'
        else:
            return 'other'
            
    except Exception as e:
        logger.error("Error getting file category", filename=filename, error=str(e))
        return 'unknown'
