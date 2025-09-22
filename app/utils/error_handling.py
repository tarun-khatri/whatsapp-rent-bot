import logging
import structlog
import traceback
import asyncio
from typing import Dict, Any, Optional, Callable
from datetime import datetime
from functools import wraps
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import json

logger = structlog.get_logger(__name__)


class WhatsAppBotError(Exception):
    """Base exception for WhatsApp bot errors."""
    pass


class ValidationError(WhatsAppBotError):
    """Exception for validation errors."""
    pass


class DocumentProcessingError(WhatsAppBotError):
    """Exception for document processing errors."""
    pass


class ConversationFlowError(WhatsAppBotError):
    """Exception for conversation flow errors."""
    pass


class ExternalServiceError(WhatsAppBotError):
    """Exception for external service errors."""
    pass


class DatabaseError(WhatsAppBotError):
    """Exception for database errors."""
    pass


class WhatsAppAPIError(WhatsAppBotError):
    """Exception for WhatsApp API errors."""
    pass


def handle_errors(func: Callable) -> Callable:
    """
    Decorator to handle errors and log them appropriately.
    
    Args:
        func: Function to wrap
        
    Returns:
        Wrapped function with error handling
    """
    @wraps(func)
    async def async_wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except WhatsAppBotError as e:
            logger.error("WhatsApp bot error", error=str(e), function=func.__name__)
            raise
        except Exception as e:
            logger.error("Unexpected error", error=str(e), function=func.__name__, traceback=traceback.format_exc())
            raise WhatsAppBotError(f"Unexpected error in {func.__name__}: {str(e)}")
    
    @wraps(func)
    def sync_wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except WhatsAppBotError as e:
            logger.error("WhatsApp bot error", error=str(e), function=func.__name__)
            raise
        except Exception as e:
            logger.error("Unexpected error", error=str(e), function=func.__name__, traceback=traceback.format_exc())
            raise WhatsAppBotError(f"Unexpected error in {func.__name__}: {str(e)}")
    
    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    else:
        return sync_wrapper


def retry_on_failure(max_attempts: int = 3, wait_time: float = 1.0, backoff_factor: float = 2.0):
    """
    Decorator to retry function on failure with exponential backoff.
    
    Args:
        max_attempts: Maximum number of retry attempts
        wait_time: Initial wait time in seconds
        backoff_factor: Backoff factor for exponential backoff
        
    Returns:
        Decorator function
    """
    def decorator(func: Callable) -> Callable:
        @retry(
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential(multiplier=wait_time, max=60),
            retry=retry_if_exception_type((ExternalServiceError, DatabaseError, WhatsAppAPIError))
        )
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                logger.warning("Function failed, retrying", function=func.__name__, error=str(e))
                raise
        
        @retry(
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential(multiplier=wait_time, max=60),
            retry=retry_if_exception_type((ExternalServiceError, DatabaseError, WhatsAppAPIError))
        )
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.warning("Function failed, retrying", function=func.__name__, error=str(e))
                raise
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


class ErrorTracker:
    """Track and analyze errors for monitoring and alerting."""
    
    def __init__(self):
        self.error_counts: Dict[str, int] = {}
        self.error_history: list = []
        self.max_history_size = 1000
    
    def record_error(self, error_type: str, error_message: str, context: Dict[str, Any] = None):
        """
        Record an error for tracking.
        
        Args:
            error_type: Type of error
            error_message: Error message
            context: Additional context
        """
        try:
            # Increment error count
            self.error_counts[error_type] = self.error_counts.get(error_type, 0) + 1
            
            # Add to history
            error_record = {
                "timestamp": datetime.utcnow().isoformat(),
                "error_type": error_type,
                "error_message": error_message,
                "context": context or {}
            }
            
            self.error_history.append(error_record)
            
            # Keep history size manageable
            if len(self.error_history) > self.max_history_size:
                self.error_history = self.error_history[-self.max_history_size:]
            
            logger.error("Error recorded", error_type=error_type, error_message=error_message, context=context)
            
        except Exception as e:
            logger.error("Failed to record error", error=str(e))
    
    def get_error_summary(self) -> Dict[str, Any]:
        """
        Get error summary for monitoring.
        
        Returns:
            Dictionary with error summary
        """
        try:
            total_errors = sum(self.error_counts.values())
            
            # Get recent errors (last hour)
            recent_cutoff = datetime.utcnow().timestamp() - 3600
            recent_errors = [
                error for error in self.error_history
                if datetime.fromisoformat(error["timestamp"]).timestamp() > recent_cutoff
            ]
            
            return {
                "total_errors": total_errors,
                "error_counts": self.error_counts,
                "recent_errors_count": len(recent_errors),
                "recent_errors": recent_errors[-10:],  # Last 10 errors
                "timestamp": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error("Failed to get error summary", error=str(e))
            return {"error": "Failed to get error summary"}
    
    def should_alert(self, error_type: str, threshold: int = 10) -> bool:
        """
        Check if an alert should be sent for this error type.
        
        Args:
            error_type: Type of error
            threshold: Error count threshold for alerting
            
        Returns:
            bool: True if alert should be sent
        """
        try:
            return self.error_counts.get(error_type, 0) >= threshold
        except Exception as e:
            logger.error("Failed to check alert condition", error=str(e))
            return False


# Global error tracker instance
error_tracker = ErrorTracker()


def safe_execute(func: Callable, *args, **kwargs) -> tuple:
    """
    Safely execute a function and return result with error information.
    
    Args:
        func: Function to execute
        *args: Function arguments
        **kwargs: Function keyword arguments
        
    Returns:
        Tuple of (success, result, error_message)
    """
    try:
        if asyncio.iscoroutinefunction(func):
            result = asyncio.run(func(*args, **kwargs))
        else:
            result = func(*args, **kwargs)
        return True, result, None
    except Exception as e:
        error_message = str(e)
        error_tracker.record_error(type(e).__name__, error_message)
        return False, None, error_message


async def safe_execute_async(func: Callable, *args, **kwargs) -> tuple:
    """
    Safely execute an async function and return result with error information.
    
    Args:
        func: Async function to execute
        *args: Function arguments
        **kwargs: Function keyword arguments
        
    Returns:
        Tuple of (success, result, error_message)
    """
    try:
        result = await func(*args, **kwargs)
        return True, result, None
    except Exception as e:
        error_message = str(e)
        error_tracker.record_error(type(e).__name__, error_message)
        return False, None, error_message


def create_error_response(error_type: str, error_message: str, user_message: str = None) -> Dict[str, Any]:
    """
    Create standardized error response.
    
    Args:
        error_type: Type of error
        error_message: Technical error message
        user_message: User-friendly error message
        
    Returns:
        Dictionary with error response
    """
    return {
        "success": False,
        "error_type": error_type,
        "error_message": error_message,
        "user_message": user_message or "מצטער, אירעה שגיאה. אנא נסה שוב או פנה לצוות התמיכה.",
        "timestamp": datetime.utcnow().isoformat()
    }


def handle_validation_error(error: ValidationError) -> str:
    """
    Handle validation errors and return user-friendly message.
    
    Args:
        error: Validation error
        
    Returns:
        User-friendly error message
    """
    error_tracker.record_error("ValidationError", str(error))
    
    # Map validation errors to user-friendly messages
    error_mappings = {
        "phone": "מספר הטלפון לא תקין. אנא שלח מספר טלפון ישראלי תקין.",
        "email": "כתובת האימייל לא תקינה. אנא שלח כתובת אימייל תקינה.",
        "id_number": "מספר תעודת הזהות לא תקין. אנא שלח מספר תעודת זהות ישראלי תקין.",
        "date": "תאריך לא תקין. אנא שלח תאריך בפורמט DD/MM/YYYY.",
        "amount": "סכום לא תקין. אנא שלח סכום תקין.",
        "file": "קובץ לא תקין. אנא שלח קובץ תקין.",
        "required": "שדה חובה חסר. אנא השלם את כל השדות הנדרשים."
    }
    
    error_message = str(error).lower()
    for key, message in error_mappings.items():
        if key in error_message:
            return message
    
    return "המידע ששלחת לא תקין. אנא נסה שוב."


def handle_document_processing_error(error: DocumentProcessingError) -> str:
    """
    Handle document processing errors and return user-friendly message.
    
    Args:
        error: Document processing error
        
    Returns:
        User-friendly error message
    """
    error_tracker.record_error("DocumentProcessingError", str(error))
    
    error_message = str(error).lower()
    
    if "size" in error_message:
        return "הקובץ גדול מדי. אנא שלח קובץ קטן יותר (מקסימום 16MB)."
    elif "format" in error_message or "type" in error_message:
        return "סוג הקובץ לא נתמך. אנא שלח קובץ PDF, JPG או PNG."
    elif "corrupt" in error_message or "invalid" in error_message:
        return "הקובץ פגום או לא תקין. אנא שלח קובץ תקין."
    elif "processing" in error_message:
        return "שגיאה בעיבוד הקובץ. אנא נסה שוב."
    else:
        return "שגיאה בעיבוד המסמך. אנא נסה שוב או פנה לצוות התמיכה."


def handle_conversation_flow_error(error: ConversationFlowError) -> str:
    """
    Handle conversation flow errors and return user-friendly message.
    
    Args:
        error: Conversation flow error
        
    Returns:
        User-friendly error message
    """
    error_tracker.record_error("ConversationFlowError", str(error))
    
    error_message = str(error).lower()
    
    if "timeout" in error_message:
        return "השיחה פגה. אנא התחל מחדש."
    elif "state" in error_message:
        return "שגיאה במצב השיחה. אנא התחל מחדש."
    elif "context" in error_message:
        return "שגיאה בהקשר השיחה. אנא התחל מחדש."
    else:
        return "שגיאה בזרימת השיחה. אנא התחל מחדש או פנה לצוות התמיכה."


def handle_external_service_error(error: ExternalServiceError) -> str:
    """
    Handle external service errors and return user-friendly message.
    
    Args:
        error: External service error
        
    Returns:
        User-friendly error message
    """
    error_tracker.record_error("ExternalServiceError", str(error))
    
    error_message = str(error).lower()
    
    if "supabase" in error_message or "database" in error_message:
        return "שגיאה בחיבור למסד הנתונים. אנא נסה שוב מאוחר יותר."
    elif "whatsapp" in error_message:
        return "שגיאה בחיבור לווטסאפ. אנא נסה שוב."
    elif "document" in error_message or "ai" in error_message:
        return "שגיאה בעיבוד המסמך. אנא נסה שוב."
    elif "timeout" in error_message:
        return "השירות לא זמין כרגע. אנא נסה שוב מאוחר יותר."
    else:
        return "שגיאה בשירות חיצוני. אנא נסה שוב מאוחר יותר."


def log_performance_metrics(func_name: str, execution_time: float, success: bool, error: str = None):
    """
    Log performance metrics for monitoring.
    
    Args:
        func_name: Name of the function
        execution_time: Execution time in seconds
        success: Whether the function succeeded
        error: Error message if failed
    """
    try:
        metrics = {
            "function": func_name,
            "execution_time": execution_time,
            "success": success,
            "error": error,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        if success:
            logger.info("Performance metrics", **metrics)
        else:
            logger.warning("Performance metrics - failed", **metrics)
            
    except Exception as e:
        logger.error("Failed to log performance metrics", error=str(e))


def monitor_function_performance(func: Callable) -> Callable:
    """
    Decorator to monitor function performance.
    
    Args:
        func: Function to monitor
        
    Returns:
        Wrapped function with performance monitoring
    """
    @wraps(func)
    async def async_wrapper(*args, **kwargs):
        start_time = datetime.utcnow()
        success = True
        error = None
        
        try:
            result = await func(*args, **kwargs)
            return result
        except Exception as e:
            success = False
            error = str(e)
            raise
        finally:
            execution_time = (datetime.utcnow() - start_time).total_seconds()
            log_performance_metrics(func.__name__, execution_time, success, error)
    
    @wraps(func)
    def sync_wrapper(*args, **kwargs):
        start_time = datetime.utcnow()
        success = True
        error = None
        
        try:
            result = func(*args, **kwargs)
            return result
        except Exception as e:
            success = False
            error = str(e)
            raise
        finally:
            execution_time = (datetime.utcnow() - start_time).total_seconds()
            log_performance_metrics(func.__name__, execution_time, success, error)
    
    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    else:
        return sync_wrapper
