from functools import wraps
from flask import current_app, jsonify, request
import logging
import hashlib
import hmac


def validate_signature(payload, signature):
    """
    Validate the incoming payload's signature against our expected signature
    """
    try:
        app_secret = current_app.config.get("APP_SECRET")
        
        if not app_secret:
            logging.error("APP_SECRET not configured in environment variables")
            return False
            
        if not signature:
            logging.error("No signature provided in request headers")
            return False
        
        # Use the App Secret to hash the payload
        expected_signature = hmac.new(
            bytes(app_secret, "latin-1"),
            msg=payload.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()

        # Check if the signature matches
        is_valid = hmac.compare_digest(expected_signature, signature)
        
        if not is_valid:
            logging.error("Signature mismatch", extra={
                "expected_signature_prefix": expected_signature[:10] + "...",
                "received_signature_prefix": signature[:10] + "..." if len(signature) > 10 else signature,
                "payload_length": len(payload)
            })
        
        return is_valid
        
    except Exception as e:
        logging.error("Error validating signature", error=str(e))
        return False


def signature_required(f):
    """
    Decorator to ensure that the incoming requests to our webhook are valid and signed with the correct signature.
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Get the signature header
        signature_header = request.headers.get("X-Hub-Signature-256", "")
        
        logging.info("Signature validation attempt", extra={
            "has_signature_header": bool(signature_header),
            "signature_header_length": len(signature_header),
            "signature_starts_with_sha256": signature_header.startswith("sha256="),
            "request_method": request.method,
            "content_type": request.headers.get("Content-Type"),
            "request_data_length": len(request.data) if request.data else 0
        })
        
        # Extract signature (remove 'sha256=' prefix)
        if signature_header.startswith("sha256="):
            signature = signature_header[7:]
        else:
            logging.error("Invalid signature header format", extra={
                "signature_header": signature_header[:20] + "..." if len(signature_header) > 20 else signature_header
            })
            return jsonify({"status": "error", "message": "Invalid signature format"}), 403
        
        # Validate signature
        if not validate_signature(request.data.decode("utf-8"), signature):
            logging.error("Signature verification failed!", extra={
                "signature_prefix": signature[:10] + "..." if len(signature) > 10 else signature,
                "payload_preview": request.data.decode("utf-8")[:100] + "..." if len(request.data) > 100 else request.data.decode("utf-8")
            })
            return jsonify({"status": "error", "message": "Invalid signature"}), 403
            
        logging.info("Signature verification successful!")
        return f(*args, **kwargs)

    return decorated_function
