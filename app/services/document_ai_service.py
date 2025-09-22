import logging
import structlog
import asyncio
import os
import tempfile
import json
from typing import Dict, Any, Optional, List
from datetime import datetime
import base64
import io
from google.cloud import documentai
from google.cloud import storage
from flask import current_app

from ..models.tenant import DocumentType, DocumentStatus
from .vertex_ai_document_parser import vertex_ai_document_parser
from .google_cloud_storage_service import google_cloud_storage_service

logger = structlog.get_logger(__name__)


class DocumentAIService:
    def __init__(self):
        self.client: Optional[documentai.DocumentProcessorServiceClient] = None
        self.storage_client: Optional[storage.Client] = None
        self._initialized = False

    def _ensure_initialized(self):
        """Ensure the service is initialized with Flask app context."""
        if not self._initialized:
            try:
                # Set up authentication
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
                
                # Initialize Document AI client with EU endpoint
                from google.api_core.client_options import ClientOptions
                opts = ClientOptions(api_endpoint="eu-documentai.googleapis.com")
                self.client = documentai.DocumentProcessorServiceClient(client_options=opts)
                
                # Initialize Cloud Storage client
                self.storage_client = storage.Client()
                
                self._initialized = True
                logger.info("Document AI and Storage clients initialized successfully")
            except Exception as e:
                logger.error("Failed to initialize Google Cloud clients", error=str(e))
                raise

    def _get_processor_name(self, document_type: DocumentType) -> str:
        """Get the processor name for a document type."""
        processor_mapping = {
            DocumentType.ID_CARD: current_app.config.get("OCR_PROCESSOR"),  # Use OCR processor for Hebrew text
            DocumentType.SEPHACH: current_app.config.get("OCR_PROCESSOR"),  # Use OCR processor for Hebrew Sephach
            DocumentType.PAYSLIPS: current_app.config.get("OCR_PROCESSOR"),  # Use OCR processor for Hebrew payslips
            DocumentType.PNL: current_app.config.get("OCR_PROCESSOR"),  # Use OCR processor for Hebrew PNL
            DocumentType.BANK_STATEMENTS: current_app.config.get("OCR_PROCESSOR"),  # Use OCR processor for Hebrew bank statements
        }
        
        processor = processor_mapping.get(document_type)
        if not processor:
            raise ValueError(f"No processor configured for document type: {document_type}")
        
        return processor

    async def process_document(self, file_data: bytes, document_type: DocumentType, tenant_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a document using the appropriate Document AI processor.
        
        Args:
            file_data: Raw file data
            document_type: Type of document being processed
            tenant_info: Tenant information for validation
            
        Returns:
            Dict containing processing results and validation
        """
        self._ensure_initialized()
        try:
            # For ID cards, try multiple processors to get better Hebrew text extraction
            processors_to_try = []
            if document_type == DocumentType.ID_CARD:
                processors_to_try = [
                    current_app.config.get("OCR_PROCESSOR"),
                    current_app.config.get("IDENTITY_PROCESSOR"),
                    current_app.config.get("FORM_PROCESSOR")
                ]
            else:
                processors_to_try = [self._get_processor_name(document_type)]
            
            document_result = None
            for processor_name in processors_to_try:
                if not processor_name:
                    continue
                    
                try:
                    logger.info("Trying processor", processor=processor_name, document_type=document_type)
                    
                    # Create the raw document (input)
                    raw_document = documentai.RawDocument(
                        content=file_data,
                        mime_type=self._get_mime_type(file_data, document_type)
                    )
                    
                    # Create the request with optimized OCR configuration for multi-page documents
                    request = documentai.ProcessRequest(
                        name=processor_name,
                        raw_document=raw_document,
                        process_options=documentai.ProcessOptions(
                            ocr_config=documentai.OcrConfig(
                                # Enable language hints for better Hebrew text recognition
                                hints=documentai.OcrConfig.Hints(
                                    language_hints=["he", "en", "ar"]  # Hebrew, English, Arabic
                                ),
                                # Enable native PDF parsing for better PDF text extraction
                                enable_native_pdf_parsing=True,
                                # Enable symbol detection for better character recognition
                                enable_symbol=True,
                                # Enable image quality scores for better document assessment
                                enable_image_quality_scores=True,
                                # Disable character box detection for better table recognition
                                disable_character_boxes_detection=False,
                                # Enable premium features for better financial document processing
                                premium_features=documentai.OcrConfig.PremiumFeatures(
                                    enable_selection_mark_detection=True,
                                    compute_style_info=True
                                )
                            ),
                            # Process all pages for multi-page documents
                            individual_page_selector=documentai.ProcessOptions.IndividualPageSelector(
                                pages=list(range(1, 10))  # Process up to 10 pages
                            )
                        )
                    )
                    
                    # Process the document
                    result = self.client.process_document(request=request)
                    document_result = result.document
                    
                    # Check if we got meaningful text (not just garbled OCR)
                    if document_result.text and len(document_result.text.strip()) > 10:
                        logger.info("Processor succeeded", processor=processor_name, text_length=len(document_result.text))
                        break
                    else:
                        logger.warning("Processor returned poor quality text", processor=processor_name, text_preview=document_result.text[:100])
                        
                except Exception as e:
                    logger.warning("Processor failed", processor=processor_name, error=str(e))
                    continue
            
            if not document_result:
                raise Exception("All processors failed to process the document")
            
            # Extract information based on document type
            extracted_data = await self._extract_document_data(document_result, document_type, tenant_info)
            
            # Validate the document
            validation_result = await self._validate_document(extracted_data, document_type, tenant_info)
            
            # Store in Google Cloud Storage regardless of validation status
            file_url = None
            storage_file_info = None
            
            # Always upload to Google Cloud Storage for record-keeping
            logger.info("Uploading document to Google Cloud Storage", 
                       document_type=document_type.value, 
                       tenant_name=tenant_info.get("full_name", "Unknown"),
                       is_valid=validation_result.get("is_valid", False))
            
            storage_file_info = await self._upload_to_cloud_storage(file_data, document_type, tenant_info)
            if storage_file_info:
                file_url = storage_file_info.get('public_url')
                logger.info("Google Cloud Storage upload successful", 
                           file_id=storage_file_info.get('file_id'),
                           file_name=storage_file_info.get('file_name'),
                           public_url=file_url,
                           is_valid=validation_result.get("is_valid", False))
            else:
                logger.error("Google Cloud Storage upload failed", 
                            document_type=document_type.value,
                            tenant_name=tenant_info.get("full_name", "Unknown"))
            
            return {
                "extracted_data": extracted_data,
                "validation_result": validation_result,
                "file_url": file_url,
                "storage_file_info": storage_file_info,
                "processing_status": DocumentStatus.VALIDATED if validation_result.get("is_valid") else DocumentStatus.REJECTED,
                "confidence_score": self._calculate_confidence_score(document_result),
                "processed_at": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error("Error processing document", document_type=document_type, error=str(e))
            return {
                "extracted_data": {},
                "validation_result": {"is_valid": False, "error": str(e)},
                "file_url": None,
                "processing_status": DocumentStatus.ERROR,
                "confidence_score": 0.0,
                "processed_at": datetime.utcnow().isoformat()
            }

    def _get_mime_type(self, file_data: bytes, document_type: DocumentType) -> str:
        """Determine MIME type from file data."""
        # Check file signatures
        if file_data.startswith(b'\x89PNG'):
            return "image/png"
        elif file_data.startswith(b'\xff\xd8\xff'):
            return "image/jpeg"
        elif file_data.startswith(b'%PDF'):
            return "application/pdf"
        else:
            # Default to JPEG for images
            return "image/jpeg"

    async def _extract_document_data(self, document_result, document_type: DocumentType, tenant_info: Dict[str, Any] = None) -> Dict[str, Any]:
        """Extract relevant data from processed document based on type."""
        try:
            extracted_data = {
                "text": document_result.text,
                "entities": {},
                "form_fields": {},
                "tables": []
            }
            
            # Extract entities
            for entity in document_result.entities:
                extracted_data["entities"][entity.type_] = {
                    "value": entity.mention_text,
                    "confidence": entity.confidence
                }
            
            # Extract form fields
            for page in document_result.pages:
                for form_field in page.form_fields:
                    if form_field.field_name and form_field.field_value:
                        extracted_data["form_fields"][form_field.field_name.text_anchor.content] = {
                            "value": form_field.field_value.text_anchor.content,
                            "confidence": form_field.field_name.confidence
                        }
            
            # Extract tables
            for page in document_result.pages:
                for table in page.tables:
                    table_data = []
                    for row in table.body_rows:
                        row_data = []
                        for cell in row.cells:
                            cell_text = ""
                            for segment in cell.layout.text_anchor.text_segments:
                                start_index = int(segment.start_index)
                                end_index = int(segment.end_index)
                                cell_text += document_result.text[start_index:end_index]
                            row_data.append(cell_text.strip())
                        table_data.append(row_data)
                    extracted_data["tables"].append(table_data)
            
            # Extract specific data based on document type
            if document_type == DocumentType.ID_CARD:
                tenant_name = tenant_info.get("full_name") if tenant_info else None
                extracted_data.update(await self._extract_id_card_data(document_result, tenant_name))
            elif document_type == DocumentType.PAYSLIPS:
                tenant_name = tenant_info.get("full_name") if tenant_info else None
                tenant_id = tenant_info.get("id") if tenant_info else None
                extracted_data.update(await self._extract_payslip_data(document_result, tenant_name, tenant_id))
            elif document_type == DocumentType.PNL:
                tenant_name = tenant_info.get("full_name") if tenant_info else None
                tenant_id = tenant_info.get("id") if tenant_info else None
                extracted_data.update(await self._extract_pnl_data(document_result, tenant_name, tenant_id))
            elif document_type == DocumentType.BANK_STATEMENTS:
                tenant_name = tenant_info.get("full_name") if tenant_info else None
                tenant_id = tenant_info.get("id") if tenant_info else None
                extracted_data.update(await self._extract_bank_statement_data(document_result, tenant_name, tenant_id))
            elif document_type == DocumentType.SEPHACH:
                extracted_data.update(await self._extract_sephach_data(document_result, tenant_info))
            
            return extracted_data
            
        except Exception as e:
            logger.error("Error extracting document data", document_type=document_type, error=str(e))
            return {"text": "", "entities": {}, "form_fields": {}, "tables": []}

    async def _extract_id_card_data(self, document_result, tenant_name: str = None) -> Dict[str, Any]:
        """Extract specific data from Israeli ID card using Vertex AI."""
        try:
            text = document_result.text
            
            # Debug: Log the extracted text to see what Document AI is returning
            logger.info("Document AI extracted text", text_length=len(text), text_preview=text[:200])
            
            # Use Vertex AI for intelligent parsing
            logger.info("Using Vertex AI for ID card parsing", tenant_name=tenant_name)
            result = await vertex_ai_document_parser.parse_id_card(text, tenant_name)
            
            if result["success"]:
                logger.info("Vertex AI parsing successful", 
                           extracted_fields=list(result["data"].keys()),
                           confidence=result["confidence"])
                # Include validation results in the returned data
                data = result["data"].copy()
                data["validation"] = result.get("validation", {})
                return data
            else:
                logger.error("Vertex AI parsing failed", error=result.get("error"))
                # Return the validation results from Vertex AI even when parsing fails
                validation_results = result.get("validation", {})
                return {
                    "id_number": result.get("data", {}).get("id_number"),
                    "full_name": result.get("data", {}).get("full_name"),
                    "confidence": result.get("confidence", 0.0),
                    "extraction_notes": f"Parsing failed: {result.get('error', 'Unknown error')}",
                    "validation": validation_results
                }
                
        except Exception as e:
            logger.error("Error in ID card data extraction", error=str(e))
            return {}

    async def _extract_payslip_data(self, document_result, tenant_name: str = None, tenant_id: str = None) -> Dict[str, Any]:
        """Extract specific data from payslip using Vertex AI."""
        try:
            text = document_result.text
            
            # Debug: Log the extracted text to see what Document AI is returning
            logger.info("Document AI extracted payslip text", text_length=len(text), text_preview=text[:200])
            
            # Use Vertex AI for intelligent parsing
            parsing_result = await vertex_ai_document_parser.parse_payslip(text, tenant_name, tenant_id)
            
            if parsing_result.get("success"):
                logger.info("Payslip parsing successful", extra={"validation": parsing_result.get("validation")})
                return {
                    "extracted_data": parsing_result.get("data", {}),
                    "validation": parsing_result.get("validation", {})
                }
            else:
                logger.warning("Payslip parsing failed", extra={"validation": parsing_result.get("validation")})
                return {
                    "extracted_data": parsing_result.get("data", {}),
                    "validation": parsing_result.get("validation", {})
                }
                
        except Exception as e:
            logger.error("Error in payslip data extraction", error=str(e))
            return {
                "extracted_data": {},
                "validation": {
                    "is_valid": False,
                    "errors": [f"Payslip extraction failed: {str(e)}"],
                    "warnings": []
                }
            }

    async def _extract_pnl_data(self, document_result, tenant_name: str = None, tenant_id: str = None) -> Dict[str, Any]:
        """Extract specific data from PNL statement using Vertex AI."""
        try:
            text = document_result.text
            
            # Debug: Log the extracted text to see what Document AI is returning
            logger.info("Document AI extracted PNL text", text_length=len(text), text_preview=text[:200])
            
            # Use Vertex AI for intelligent parsing
            parsing_result = await vertex_ai_document_parser.parse_pnl(text, tenant_name, tenant_id)
            
            if parsing_result.get("success"):
                logger.info("PNL parsing successful", extra={"validation": parsing_result.get("validation")})
                return {
                    "extracted_data": parsing_result.get("data", {}),
                    "validation": parsing_result.get("validation", {})
                }
            else:
                logger.warning("PNL parsing failed", extra={"validation": parsing_result.get("validation")})
                return {
                    "extracted_data": parsing_result.get("data", {}),
                    "validation": parsing_result.get("validation", {})
                }
                
        except Exception as e:
            logger.error("Error in PNL data extraction", error=str(e))
            return {
                "extracted_data": {},
                "validation": {
                    "is_valid": False,
                    "errors": [f"PNL extraction failed: {str(e)}"],
                    "warnings": []
                }
            }

    async def _extract_bank_statement_data(self, document_result, tenant_name: str = None, tenant_id: str = None) -> Dict[str, Any]:
        """Extract bank statement data using Vertex AI."""
        try:
            from app.services.vertex_ai_document_parser import vertex_ai_document_parser
            
            # Use Vertex AI for intelligent bank statement parsing
            result = await vertex_ai_document_parser.parse_bank_statement(
                document_result.text, 
                tenant_name, 
                tenant_id
            )
            
            if result["success"]:
                logger.info("Bank statement parsing successful", 
                           extra={"extracted_fields": list(result["data"].keys()),
                                  "validation_passed": result["validation"]["is_valid"]})
                # Include validation results in the returned data
                bank_data = result["data"]
                bank_data["validation"] = result["validation"]
                return bank_data
            else:
                logger.warning("Bank statement parsing failed", 
                              extra={"errors": result["validation"].get("errors", [])})
                # Return validation results even if parsing failed
                return {"validation": result["validation"]}
                
        except Exception as e:
            logger.error("Error in bank statement extraction", extra={"error": str(e)})
            return {}

    async def _extract_sephach_data(self, document_result, tenant_info: Dict[str, Any] = None) -> Dict[str, Any]:
        """Extract specific data from Sephach (appendix form) using Vertex AI."""
        try:
            text = document_result.text
            
            # Debug: Log the extracted text to see what Document AI is returning
            logger.info("Document AI extracted text for Sephach", 
                       text_length=len(text), 
                       text_preview=text[:200],
                       tenant_name=tenant_info.get("full_name", "Unknown") if tenant_info else "Unknown")
            
            # Use Vertex AI for intelligent Sephach parsing
            logger.info("Using Vertex AI for Sephach parsing", 
                       tenant_name=tenant_info.get("full_name", "Unknown") if tenant_info else "Unknown")
            result = await vertex_ai_document_parser.parse_sephach(text, tenant_info)
            
            if result["success"]:
                logger.info("Vertex AI Sephach parsing successful", 
                           extracted_fields=list(result["data"].keys()),
                           confidence=result["confidence"])
                # Include validation results in the returned data
                data = result["data"].copy()
                data["validation"] = result.get("validation", {})
                return data
            else:
                logger.error("Vertex AI Sephach parsing failed", error=result.get("error"))
                # Return the validation results from Vertex AI even when parsing fails
                validation_results = result.get("validation", {})
                return {
                    "id_number": result.get("data", {}).get("id_number"),
                    "full_name": result.get("data", {}).get("full_name"),
                    "confidence": result.get("confidence", 0.0),
                    "extraction_notes": f"Sephach parsing failed: {result.get('error', 'Unknown error')}",
                    "validation": validation_results
                }
                
        except Exception as e:
            logger.error("Error in Sephach data extraction", error=str(e))
            return {}

    async def _validate_document(self, extracted_data: Dict[str, Any], document_type: DocumentType, tenant_info: Dict[str, Any]) -> Dict[str, Any]:
        """Validate extracted document data against tenant information."""
        try:
            validation_result = {
                "is_valid": True,
                "errors": [],
                "warnings": [],
                "confidence_score": 0.0
            }
            
            # Check confidence threshold
            confidence_threshold = current_app.config.get("DOCUMENT_AI_CONFIDENCE_THRESHOLD", 0.7)
            
            # Validate based on document type
            if document_type == DocumentType.ID_CARD:
                validation_result = self._validate_id_card(extracted_data, tenant_info, confidence_threshold)
            elif document_type == DocumentType.PAYSLIPS:
                validation_result = self._validate_payslip(extracted_data, tenant_info, confidence_threshold)
            elif document_type == DocumentType.BANK_STATEMENTS:
                validation_result = self._validate_bank_statement(extracted_data, tenant_info, confidence_threshold)
            elif document_type == DocumentType.SEPHACH:
                validation_result = self._validate_sephach(extracted_data, tenant_info, confidence_threshold)
            elif document_type == DocumentType.PNL:
                validation_result = self._validate_pnl(extracted_data, tenant_info, confidence_threshold)
            
            return validation_result
            
        except Exception as e:
            logger.error("Error validating document", document_type=document_type, error=str(e))
            return {
                "is_valid": False,
                "errors": [f"Validation error: {str(e)}"],
                "warnings": [],
                "confidence_score": 0.0
            }

    def _validate_id_card(self, extracted_data: Dict[str, Any], tenant_info: Dict[str, Any], confidence_threshold: float) -> Dict[str, Any]:
        """Validate Israeli ID card data comprehensively."""
        validation_result = {
            "is_valid": True,
            "errors": [],
            "warnings": [],
            "confidence_score": 0.0
        }
        
        # Use Vertex AI validation results if available
        if "validation" in extracted_data:
            ai_validation = extracted_data["validation"]
            validation_result["is_valid"] = ai_validation.get("is_valid", True)
            validation_result["errors"] = ai_validation.get("errors", [])
            validation_result["warnings"] = ai_validation.get("warnings", [])
            validation_result["confidence_score"] = extracted_data.get("confidence", 0.8)
        else:
            # Fallback to basic validation
            id_number = extracted_data.get("id_number")
            if not id_number:
                validation_result["errors"].append("ID number not found in document")
                validation_result["is_valid"] = False
            elif len(id_number) != 9:
                validation_result["errors"].append("Invalid ID number format (must be 9 digits)")
                validation_result["is_valid"] = False
            elif not id_number.isdigit():
                validation_result["errors"].append("ID number must contain only digits")
                validation_result["is_valid"] = False
        
        # Name validation is handled by Vertex AI validation results above
        # No need for duplicate validation here
        
        # Check if ID card is expired
        expiry_date = extracted_data.get("date_of_expiry")
        if expiry_date:
            try:
                from datetime import datetime
                # Try to parse the date (assuming DD.MM.YYYY format)
                if '.' in expiry_date:
                    parsed_date = datetime.strptime(expiry_date, "%d.%m.%Y")
                    if parsed_date < datetime.now():
                        validation_result["errors"].append("ID card has expired")
                        validation_result["is_valid"] = False
                    elif parsed_date < datetime.now().replace(year=datetime.now().year + 1):
                        validation_result["warnings"].append("ID card expires within one year")
            except ValueError:
                validation_result["warnings"].append("Could not parse expiry date")
        
        # Check if required fields are present (more lenient validation)
        required_fields = ["id_number"]  # Only ID number is truly required
        for field in required_fields:
            if not extracted_data.get(field):
                validation_result["errors"].append(f"Required field '{field}' not found")
                validation_result["is_valid"] = False
        
        # Check for name (warning only, not error)
        if not extracted_data.get("name"):
            validation_result["warnings"].append("Name not found in document")
        
        # Check for date of birth (warning only, not error)
        if not extracted_data.get("date_of_birth"):
            validation_result["warnings"].append("Date of birth not found in document")
        
        # Check if gender is present (optional but useful)
        if not extracted_data.get("gender"):
            validation_result["warnings"].append("Gender information not found")
        
        # Check if nationality is Israeli
        nationality = extracted_data.get("nationality", "").lower()
        if nationality and "ישראלי" not in nationality and "israeli" not in nationality:
            validation_result["warnings"].append("Nationality may not be Israeli")
        
        # Check if place of birth is present
        if not extracted_data.get("place_of_birth"):
            validation_result["warnings"].append("Place of birth not found")
        
        # Check if parents' names are present (optional but useful for verification)
        if not extracted_data.get("father_name"):
            validation_result["warnings"].append("Father's name not found")
        
        if not extracted_data.get("mother_name"):
            validation_result["warnings"].append("Mother's name not found")
        
        return validation_result

    def _validate_payslip(self, extracted_data: Dict[str, Any], tenant_info: Dict[str, Any], confidence_threshold: float) -> Dict[str, Any]:
        """Validate payslip data using Vertex AI validation results."""
        # Use validation results from Vertex AI if available
        if "validation" in extracted_data:
            vertex_validation = extracted_data["validation"]
            return {
                "is_valid": vertex_validation.get("is_valid", False),
                "errors": vertex_validation.get("errors", []),
                "warnings": vertex_validation.get("warnings", []),
                "confidence_score": 0.9 if vertex_validation.get("is_valid", False) else 0.1
            }
        
        # Fallback validation if Vertex AI results not available
        validation_result = {
            "is_valid": True,
            "errors": [],
            "warnings": [],
            "confidence_score": 0.0
        }
        
        # Check if salary is present
        gross_salary = extracted_data.get("gross_salary")
        if not gross_salary:
            validation_result["errors"].append("Salary information not found")
            validation_result["is_valid"] = False
        else:
            try:
                salary_amount = float(gross_salary)
                rent_amount = float(tenant_info.get("monthly_rent_amount", 0))
                
                # Check if salary is at least 3x rent
                if rent_amount > 0 and salary_amount < (rent_amount * 3):
                    validation_result["warnings"].append("Salary may be insufficient (less than 3x rent)")
            except ValueError:
                validation_result["errors"].append("Invalid salary format")
                validation_result["is_valid"] = False
        
        return validation_result

    def _validate_pnl(self, extracted_data: Dict[str, Any], tenant_info: Dict[str, Any], confidence_threshold: float) -> Dict[str, Any]:
        """Validate PNL data using Vertex AI validation results."""
        # Use validation results from Vertex AI if available
        if "validation" in extracted_data:
            vertex_validation = extracted_data["validation"]
            return {
                "is_valid": vertex_validation.get("is_valid", False),
                "errors": vertex_validation.get("errors", []),
                "warnings": vertex_validation.get("warnings", []),
                "confidence_score": 0.9 if vertex_validation.get("is_valid", False) else 0.1
            }
        
        # Fallback validation if Vertex AI results not available
        validation_result = {
            "is_valid": True,
            "errors": [],
            "warnings": [],
            "confidence_score": 0.0
        }
        
        # Check if accountant signature is present
        accountant_signature = extracted_data.get("accountant_signature")
        if not accountant_signature or accountant_signature.lower() not in ["yes", "כן", "true"]:
            validation_result["errors"].append("Accountant signature is required for PNL validation")
            validation_result["is_valid"] = False
        
        # Check if financial data is present
        revenue = extracted_data.get("revenue")
        expenses = extracted_data.get("expenses")
        net_income = extracted_data.get("net_income")
        
        if not revenue or not expenses or not net_income:
            validation_result["errors"].append("Required financial data not found")
            validation_result["is_valid"] = False
        else:
            try:
                revenue_amount = float(revenue)
                expenses_amount = float(expenses)
                net_income_amount = float(net_income)
                
                # Check financial consistency
                calculated_net = revenue_amount - expenses_amount
                if abs(calculated_net - net_income_amount) > 100:  # Allow small rounding differences
                    validation_result["warnings"].append("Financial data inconsistency detected")
                
                # Check if income is reasonable for rent
                rent_amount = float(tenant_info.get("monthly_rent_amount", 0))
                if rent_amount > 0 and net_income_amount < (rent_amount * 3):
                    validation_result["warnings"].append("Net income may be insufficient (less than 3x rent)")
                    
            except ValueError:
                validation_result["errors"].append("Invalid financial data format")
                validation_result["is_valid"] = False
        
        return validation_result

    def _validate_bank_statement(self, extracted_data: Dict[str, Any], tenant_info: Dict[str, Any], confidence_threshold: float) -> Dict[str, Any]:
        """Validate bank statement data using Vertex AI results."""
        try:
            # The validation is already done by Vertex AI in _extract_bank_statement_data
            # We just need to return the validation results from the extraction
            if "validation" in extracted_data:
                return extracted_data["validation"]
            
            # Fallback validation if no Vertex AI results
            validation_result = {
                "is_valid": True,
                "errors": [],
                "warnings": [],
                "confidence_score": 0.0
            }
            
            # Check if account number is present
            account_number = extracted_data.get("account_number")
            if not account_number:
                validation_result["warnings"].append("Account number not found")
            
            # Check if balance is present
            balance = extracted_data.get("balance")
            if not balance:
                validation_result["warnings"].append("Balance information not found")
            
            return validation_result
            
        except Exception as e:
            logger.error("Error in bank statement validation", extra={"error": str(e)})
            return {
                "is_valid": False,
                "errors": [f"Validation error: {str(e)}"],
                "warnings": [],
                "confidence_score": 0.0
            }

    def _validate_sephach(self, extracted_data: Dict[str, Any], tenant_info: Dict[str, Any], confidence_threshold: float) -> Dict[str, Any]:
        """Validate Sephach form data comprehensively."""
        validation_result = {
            "is_valid": True,
            "errors": [],
            "warnings": [],
            "confidence_score": 0.0
        }
        
        # Use Vertex AI validation results if available
        if "validation" in extracted_data:
            ai_validation = extracted_data["validation"]
            validation_result["is_valid"] = ai_validation.get("is_valid", True)
            validation_result["errors"] = ai_validation.get("errors", [])
            validation_result["warnings"] = ai_validation.get("warnings", [])
            validation_result["confidence_score"] = extracted_data.get("confidence", 0.8)
            
            logger.info("Using Vertex AI Sephach validation results", 
                       extra={"is_valid": validation_result["is_valid"],
                              "errors_count": len(validation_result["errors"]),
                              "warnings_count": len(validation_result["warnings"])})
        else:
            # Fallback to basic validation
            logger.warning("No Vertex AI validation results found, using basic validation")
            
            # Check if required fields are present
            required_fields = ["full_name", "id_number", "address", "marital_status"]
            missing_fields = []
            
            for field in required_fields:
                if not extracted_data.get(field):
                    missing_fields.append(field)
            
            if missing_fields:
                validation_result["errors"].append(f"Missing required fields: {', '.join(missing_fields)}")
                validation_result["is_valid"] = False
                logger.warning("Sephach rejected - missing required fields", 
                             extra={"missing_fields": missing_fields})
        
        # Additional business logic validation
        if validation_result["is_valid"]:
            # Check if Sephach ID matches tenant ID (if we have it from previous ID card)
            sephach_id = extracted_data.get("id_number")
            tenant_id = tenant_info.get("id_number")  # This would come from previous ID card processing
            
            if tenant_id and sephach_id and sephach_id != tenant_id:
                validation_result["warnings"].append("Sephach ID number doesn't match main ID card")
                logger.warning("Sephach ID mismatch", 
                             extra={"sephach_id": sephach_id, "tenant_id": tenant_id})
        
        # Log final validation result
        logger.info("Sephach validation completed", 
                   extra={"is_valid": validation_result["is_valid"],
                          "errors_count": len(validation_result["errors"]),
                          "warnings_count": len(validation_result["warnings"]),
                          "confidence_score": validation_result["confidence_score"]})
        
        return validation_result

    def _calculate_confidence_score(self, document_result) -> float:
        """Calculate overall confidence score for the document."""
        try:
            total_confidence = 0.0
            count = 0
            
            # Calculate average confidence from entities
            for entity in document_result.entities:
                total_confidence += entity.confidence
                count += 1
            
            # Calculate average confidence from form fields
            for page in document_result.pages:
                for form_field in page.form_fields:
                    if form_field.field_name:
                        total_confidence += form_field.field_name.confidence
                        count += 1
            
            return total_confidence / count if count > 0 else 0.0
            
        except Exception as e:
            logger.error("Error calculating confidence score", error=str(e))
            return 0.0

    async def _upload_to_cloud_storage(self, file_data: bytes, document_type: DocumentType, tenant_info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Upload document to Google Cloud Storage with proper organization."""
        try:
            # Get tenant information
            tenant_name = tenant_info.get("full_name", "Unknown")
            tenant_id = tenant_info.get("id", "unknown")
            
            # Determine MIME type based on document type
            mime_type = self._get_mime_type_for_document(document_type)
            
            # Upload to Google Cloud Storage
            storage_file_info = await google_cloud_storage_service.upload_document(
                file_data=file_data,
                document_type=document_type.value,
                tenant_name=tenant_name,
                mime_type=mime_type
            )
            
            if storage_file_info:
                logger.info("Document uploaded to Google Cloud Storage successfully", 
                           tenant_name=tenant_name, 
                           document_type=document_type.value,
                           file_id=storage_file_info.get('file_id'))
                return storage_file_info
            else:
                logger.error("Failed to upload document to Google Cloud Storage", 
                           tenant_name=tenant_name, 
                           document_type=document_type.value)
                return None
            
        except Exception as e:
            logger.error("Error uploading document to Google Cloud Storage", 
                        document_type=document_type, 
                        tenant_name=tenant_info.get("full_name", "Unknown"),
                        error=str(e))
            return None
    
    def _get_mime_type_for_document(self, document_type: DocumentType) -> str:
        """Get appropriate MIME type for document type."""
        mime_types = {
            DocumentType.ID_CARD: "image/jpeg",
            DocumentType.PAYSLIPS: "application/pdf",
            DocumentType.BANK_STATEMENTS: "application/pdf",
            DocumentType.SEPHACH: "application/pdf"
        }
        return mime_types.get(document_type, "application/octet-stream")
    
    async def process_guarantor_document(self, file_data: bytes, document_type: DocumentType, guarantor_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a guarantor document using the appropriate Document AI processor.
        
        Args:
            file_data: Raw file data
            document_type: Type of document being processed
            guarantor_info: Guarantor information for validation
            
        Returns:
            Dict containing processing results and validation
        """
        try:
            logger.info("Processing guarantor document", extra={
                "document_type": document_type.value,
                "guarantor_name": guarantor_info.get("full_name"),
                "guarantor_id": guarantor_info.get("id")
            })
            
            # Process document using existing logic
            result = await self.process_document(file_data, document_type, guarantor_info)
            
            if result.get("is_valid", False):
                # Update guarantor documents status
                from .guarantor_service import guarantor_service
                await guarantor_service.update_guarantor_documents_status(
                    guarantor_info["id"],
                    document_type.value,
                    "validated",
                    result.get("file_url")
                )
                
                logger.info("Guarantor document processed successfully", extra={
                    "guarantor_id": guarantor_info.get("id"),
                    "document_type": document_type.value,
                    "file_url": result.get("file_url")
                })
            else:
                logger.warning("Guarantor document validation failed", extra={
                    "guarantor_id": guarantor_info.get("id"),
                    "document_type": document_type.value,
                    "errors": result.get("validation_result", {}).get("errors", [])
                })
            
            return result
            
        except Exception as e:
            logger.error("Error processing guarantor document", extra={
                "error": str(e),
                "guarantor_id": guarantor_info.get("id"),
                "document_type": document_type.value
            })
            return {
                "is_valid": False,
                "error": f"Error processing guarantor document: {str(e)}",
                "validation_result": {
                    "is_valid": False,
                    "errors": [f"Processing error: {str(e)}"],
                    "warnings": []
                }
            }


# Global instance
document_ai_service = DocumentAIService()
