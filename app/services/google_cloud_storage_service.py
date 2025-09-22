"""
Google Cloud Storage Service for document storage and management.
"""

import os
import json
import structlog
from datetime import datetime
from typing import Dict, Any, Optional, List
from flask import current_app
from google.cloud import storage
from google.oauth2 import service_account

logger = structlog.get_logger(__name__)


class GoogleCloudStorageService:
    """Service for managing Google Cloud Storage operations."""
    
    def __init__(self):
        self.client: Optional[storage.Client] = None
        self.bucket_name: Optional[str] = None
        self._initialized = False
    
    def _ensure_initialized(self):
        """Initialize Google Cloud Storage service if not already done."""
        if self._initialized:
            logger.info("Google Cloud Storage service already initialized")
            return
            
        try:
            logger.info("Initializing Google Cloud Storage service...")
            
            # Get credentials from environment
            credentials_json = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
            if not credentials_json:
                logger.error("GOOGLE_APPLICATION_CREDENTIALS not found in environment")
                raise ValueError("GOOGLE_APPLICATION_CREDENTIALS not found in environment")
            
            logger.info("Found Google credentials in environment")
            
            # Parse JSON credentials
            if credentials_json.startswith('{'):
                # Direct JSON string
                credentials_info = json.loads(credentials_json)
            else:
                # File path
                with open(credentials_json, 'r') as f:
                    credentials_info = json.load(f)
            
            # Create credentials object
            credentials = service_account.Credentials.from_service_account_info(
                credentials_info,
                scopes=['https://www.googleapis.com/auth/cloud-platform']
            )
            
            # Initialize Cloud Storage client
            self.client = storage.Client(credentials=credentials)
            
            # Get bucket name from config
            self.bucket_name = current_app.config.get('GOOGLE_CLOUD_STORAGE_BUCKET')
            if not self.bucket_name:
                logger.error("GOOGLE_CLOUD_STORAGE_BUCKET not configured")
                raise ValueError("GOOGLE_CLOUD_STORAGE_BUCKET not configured")
            
            # Ensure bucket exists, create if it doesn't
            self._ensure_bucket_exists()
            
            logger.info("Google Cloud Storage service initialized successfully", 
                       bucket_name=self.bucket_name)
            
            self._initialized = True
            
        except Exception as e:
            logger.error("Failed to initialize Google Cloud Storage service", error=str(e))
            raise
    
    def _ensure_bucket_exists(self):
        """Ensure the bucket exists, create it if it doesn't."""
        try:
            # Check if bucket exists
            bucket = self.client.bucket(self.bucket_name)
            if bucket.exists():
                logger.info("Bucket already exists", bucket_name=self.bucket_name)
                return
            
            # Create bucket if it doesn't exist
            logger.info("Bucket does not exist, creating it", bucket_name=self.bucket_name)
            
            # Get project ID from credentials
            project_id = self.client.project
            
            # Create bucket with default settings
            bucket = self.client.create_bucket(
                self.bucket_name,
                location='us-central1'  # Default location
            )
            
            logger.info("Bucket created successfully", 
                       bucket_name=self.bucket_name,
                       project_id=project_id)
            
        except Exception as e:
            logger.error("Error ensuring bucket exists", 
                        bucket_name=self.bucket_name,
                        error=str(e))
            raise
    
    async def create_tenant_folder(self, tenant_name: str) -> str:
        """
        Create a folder structure for a tenant in Cloud Storage.
        Cloud Storage doesn't have folders, but we can use prefixes.
        
        Args:
            tenant_name: Name of the tenant
            
        Returns:
            Folder prefix for the tenant
        """
        self._ensure_initialized()
        
        try:
            # Clean tenant name for use as folder prefix
            clean_tenant_name = tenant_name.replace(' ', '_').replace('/', '_')
            folder_prefix = f"tenants/{clean_tenant_name}/"
            
            logger.info("Created tenant folder prefix", 
                       tenant_name=tenant_name, 
                       folder_prefix=folder_prefix)
            
            return folder_prefix
            
        except Exception as e:
            logger.error("Error creating tenant folder", 
                        tenant_name=tenant_name, 
                        error=str(e))
            raise
    
    async def upload_document(self, file_data: bytes, document_type: str, 
                            tenant_name: str, mime_type: str = "application/octet-stream") -> Dict[str, Any]:
        """
        Upload a document to Google Cloud Storage.
        
        Args:
            file_data: Binary data of the file
            document_type: Type of document (id_card, payslip, etc.)
            tenant_name: Name of the tenant
            mime_type: MIME type of the file
            
        Returns:
            Dictionary with upload information
        """
        self._ensure_initialized()
        
        try:
            # Create tenant folder prefix
            folder_prefix = await self.create_tenant_folder(tenant_name)
            
            # Generate file name with versioning
            file_name = await self._generate_file_name(tenant_name, document_type, folder_prefix)
            
            # Get bucket
            bucket = self.client.bucket(self.bucket_name)
            
            # Create blob
            blob = bucket.blob(file_name)
            
            # Set metadata
            blob.metadata = {
                'tenant_name': tenant_name,
                'document_type': document_type,
                'upload_date': datetime.utcnow().isoformat(),
                'uploaded_by': 'whatsapp-bot'
            }
            
            # Upload file
            blob.upload_from_string(file_data, content_type=mime_type)
            
            # For uniform bucket-level access, we can't make individual files public
            # Instead, we'll use the storage URL format
            public_url = f"https://storage.googleapis.com/{self.bucket_name}/{blob.name}"
            
            logger.info("Document uploaded successfully", 
                       tenant_name=tenant_name,
                       document_type=document_type,
                       file_name=file_name,
                       file_size=len(file_data),
                       public_url=public_url)
            
            return {
                'file_name': file_name,
                'file_id': blob.name,
                'file_size': len(file_data),
                'public_url': public_url,
                'bucket_name': self.bucket_name,
                'upload_date': datetime.utcnow().isoformat(),
                'metadata': blob.metadata
            }
            
        except Exception as e:
            logger.error("Error uploading document", 
                        tenant_name=tenant_name,
                        document_type=document_type,
                        error=str(e))
            raise
    
    async def _generate_file_name(self, tenant_name: str, document_type: str, folder_prefix: str) -> str:
        """
        Generate a unique file name with versioning.
        
        Args:
            tenant_name: Name of the tenant
            document_type: Type of document
            folder_prefix: Folder prefix for the tenant
            
        Returns:
            Unique file name
        """
        try:
            # Clean names for file system
            clean_tenant_name = tenant_name.replace(' ', '_').replace('/', '_')
            clean_document_type = document_type.replace(' ', '_').replace('/', '_')
            
            # Get current date
            current_date = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            
            # Get version number
            version_number = await self._get_next_version_number(tenant_name, document_type, folder_prefix)
            
            # Generate base name
            base_name = f"{clean_document_type}_{clean_tenant_name}_{current_date}"
            
            # Add version if not first version
            if version_number > 1:
                file_name = f"{folder_prefix}{base_name}({version_number}).jpg"
            else:
                file_name = f"{folder_prefix}{base_name}.jpg"
            
            logger.info("Generated file name", 
                       original_name=f"{document_type}_{tenant_name}",
                       proper_name=file_name,
                       version_number=version_number)
            
            return file_name
            
        except Exception as e:
            logger.error("Error generating file name", 
                        tenant_name=tenant_name,
                        document_type=document_type,
                        error=str(e))
            # Fallback to simple name
            clean_tenant_name = tenant_name.replace(' ', '_').replace('/', '_')
            clean_document_type = document_type.replace(' ', '_').replace('/', '_')
            current_date = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            return f"{folder_prefix}{clean_document_type}_{clean_tenant_name}_{current_date}.jpg"
    
    async def _get_next_version_number(self, tenant_name: str, document_type: str, folder_prefix: str) -> int:
        """
        Get the next version number for a document type for a specific tenant.
        
        Args:
            tenant_name: Name of the tenant
            document_type: Type of document
            folder_prefix: Folder prefix for the tenant
            
        Returns:
            Next version number (1, 2, 3, etc.)
        """
        try:
            # List files in the tenant folder
            bucket = self.client.bucket(self.bucket_name)
            blobs = bucket.list_blobs(prefix=folder_prefix)
            
            # Filter documents by type
            same_type_docs = []
            for blob in blobs:
                blob_name = blob.name
                if document_type in blob_name:
                    same_type_docs.append(blob_name)
            
            # Find the highest version number
            max_version = 0
            for doc_name in same_type_docs:
                # Look for version numbers in parentheses
                import re
                version_match = re.search(r'\((\d+)\)', doc_name)
                if version_match:
                    version = int(version_match.group(1))
                    max_version = max(max_version, version)
            
            return max_version + 1
            
        except Exception as e:
            logger.error("Error getting version number", 
                        tenant_name=tenant_name, 
                        error=str(e))
            return 1
    
    async def get_tenant_documents(self, tenant_name: str) -> List[Dict[str, Any]]:
        """
        Get all documents for a tenant.
        
        Args:
            tenant_name: Name of the tenant
            
        Returns:
            List of document information
        """
        self._ensure_initialized()
        
        try:
            # Create tenant folder prefix
            folder_prefix = await self.create_tenant_folder(tenant_name)
            
            # List files in the tenant folder
            bucket = self.client.bucket(self.bucket_name)
            blobs = bucket.list_blobs(prefix=folder_prefix)
            
            documents = []
            for blob in blobs:
                documents.append({
                    'name': blob.name,
                    'size': blob.size,
                    'created': blob.time_created.isoformat() if blob.time_created else None,
                    'updated': blob.updated.isoformat() if blob.updated else None,
                    'public_url': blob.public_url,
                    'metadata': blob.metadata or {}
                })
            
            logger.info("Retrieved tenant documents", 
                       tenant_name=tenant_name, 
                       document_count=len(documents))
            
            return documents
            
        except Exception as e:
            logger.error("Error getting tenant documents", 
                        tenant_name=tenant_name, 
                        error=str(e))
            return []
    
    async def upload_guarantor_document(self, file_data: bytes, document_type: str, 
                                        guarantor_name: str, guarantor_number: int, 
                                        tenant_name: str, is_valid: bool = True) -> Dict[str, Any]:
        """
        Upload a guarantor document to Google Cloud Storage.
        
        Args:
            file_data: Raw file data
            document_type: Type of document (id_card, sephach, payslips, pnl, bank_statements)
            guarantor_name: Name of the guarantor
            guarantor_number: Guarantor number (1 or 2)
            tenant_name: Name of the tenant
            is_valid: Whether the document is valid
            
        Returns:
            Dict containing upload results
        """
        try:
            self._ensure_initialized()
            
            # Create guarantor folder structure
            folder_prefix = f"tenants/{tenant_name}/guarantors/guarantor_{guarantor_number}/"
            
            # Generate file name
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_extension = self._get_file_extension(file_data)
            original_name = f"{document_type}_guarantor{guarantor_number}_{guarantor_name}"
            proper_name = f"{folder_prefix}{document_type}_guarantor{guarantor_number}_{guarantor_name}_{timestamp}{file_extension}"
            
            # Handle duplicate names
            version_number = 1
            while self._file_exists(proper_name):
                proper_name = f"{folder_prefix}{document_type}_guarantor{guarantor_number}_{guarantor_name}_{timestamp}_v{version_number}{file_extension}"
                version_number += 1
            
            logger.info("Generated guarantor file name", extra={
                "original_name": original_name,
                "proper_name": proper_name,
                "version_number": version_number
            })
            
            # Upload file
            blob = self.bucket.blob(proper_name)
            blob.upload_from_string(file_data)
            
            # Make file public
            blob.make_public()
            public_url = blob.public_url
            
            logger.info("Guarantor document uploaded successfully", extra={
                "guarantor_name": guarantor_name,
                "guarantor_number": guarantor_number,
                "tenant_name": tenant_name,
                "document_type": document_type,
                "file_name": proper_name,
                "file_size": len(file_data),
                "public_url": public_url
            })
            
            return {
                "success": True,
                "file_id": proper_name,
                "file_name": proper_name,
                "public_url": public_url,
                "is_valid": is_valid
            }
            
        except Exception as e:
            logger.error("Error uploading guarantor document", extra={
                "error": str(e),
                "guarantor_name": guarantor_name,
                "guarantor_number": guarantor_number,
                "tenant_name": tenant_name,
                "document_type": document_type
            })
            return {
                "success": False,
                "error": f"Error uploading guarantor document: {str(e)}"
            }


# Global instance
google_cloud_storage_service = GoogleCloudStorageService()
