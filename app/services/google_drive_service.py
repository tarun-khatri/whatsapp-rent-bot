#!/usr/bin/env python3
"""
Google Drive Service for Document Storage

This service handles:
- Authentication with Google Drive API
- Creating tenant-specific folders
- Uploading documents with proper naming
- Managing file permissions and organization
"""

import os
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload
import io
import structlog

logger = structlog.get_logger(__name__)


class GoogleDriveService:
    """Service for managing Google Drive operations."""
    
    def __init__(self):
        self.service = None
        self.credentials = None
        self.root_folder_id = None
        self._initialized = False
    
    def _ensure_initialized(self):
        """Initialize Google Drive service if not already done."""
        if self._initialized:
            logger.info("Google Drive service already initialized")
            return
            
        try:
            logger.info("Initializing Google Drive service...")
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
            self.credentials = service_account.Credentials.from_service_account_info(
                credentials_info,
                scopes=['https://www.googleapis.com/auth/drive']
            )
            
            # Build the service
            self.service = build('drive', 'v3', credentials=self.credentials)
            
            # Get root folder ID
            self.root_folder_id = os.getenv('GOOGLE_DRIVE_FOLDER_ID')
            if not self.root_folder_id:
                logger.warning("GOOGLE_DRIVE_FOLDER_ID not set, will use Drive root")
            else:
                logger.info("Using Google Drive root folder", folder_id=self.root_folder_id)
            
            self._initialized = True
            logger.info("Google Drive service initialized successfully")
            
        except Exception as e:
            logger.error("Failed to initialize Google Drive service", error=str(e))
            raise
    
    async def create_tenant_folder(self, tenant_name: str) -> Optional[str]:
        """
        Create a folder for a tenant if it doesn't exist.
        
        Args:
            tenant_name: Name of the tenant
            
        Returns:
            Folder ID if successful, None otherwise
        """
        self._ensure_initialized()
        
        try:
            # Check if folder already exists
            existing_folder_id = await self._find_tenant_folder(tenant_name)
            if existing_folder_id:
                logger.info("Tenant folder already exists", tenant_name=tenant_name, folder_id=existing_folder_id)
                return existing_folder_id
            
            # Create folder metadata
            folder_metadata = {
                'name': tenant_name,
                'mimeType': 'application/vnd.google-apps.folder',
                'parents': [self.root_folder_id] if self.root_folder_id else None
            }
            
            # Create the folder
            folder = self.service.files().create(
                body=folder_metadata,
                fields='id'
            ).execute()
            
            folder_id = folder.get('id')
            logger.info("Created tenant folder", tenant_name=tenant_name, folder_id=folder_id)
            
            return folder_id
            
        except HttpError as error:
            logger.error("Error creating tenant folder", tenant_name=tenant_name, error=str(error))
            return None
        except Exception as e:
            logger.error("Unexpected error creating tenant folder", tenant_name=tenant_name, error=str(e))
            return None
    
    async def _find_tenant_folder(self, tenant_name: str) -> Optional[str]:
        """Find existing tenant folder by name."""
        try:
            query = f"name='{tenant_name}' and mimeType='application/vnd.google-apps.folder'"
            if self.root_folder_id:
                query += f" and '{self.root_folder_id}' in parents"
            
            results = self.service.files().list(
                q=query,
                fields='files(id, name)'
            ).execute()
            
            files = results.get('files', [])
            if files:
                return files[0]['id']
            
            return None
            
        except Exception as e:
            logger.error("Error finding tenant folder", tenant_name=tenant_name, error=str(e))
            return None
    
    async def upload_document(
        self, 
        file_data: bytes, 
        file_name: str, 
        mime_type: str, 
        tenant_name: str,
        document_type: str
    ) -> Optional[Dict[str, Any]]:
        """
        Upload a document to Google Drive.
        
        Args:
            file_data: Raw file data
            file_name: Name for the file
            mime_type: MIME type of the file
            tenant_name: Name of the tenant
            document_type: Type of document (ID_CARD, PAYSLIPS, etc.)
            
        Returns:
            Dictionary with file info if successful, None otherwise
        """
        logger.info("Starting Google Drive upload", 
                   tenant_name=tenant_name, 
                   document_type=document_type,
                   file_name=file_name,
                   file_size=len(file_data),
                   mime_type=mime_type)
        
        self._ensure_initialized()
        
        try:
            # Create or get tenant folder
            logger.info("Creating/getting tenant folder", tenant_name=tenant_name)
            tenant_folder_id = await self.create_tenant_folder(tenant_name)
            if not tenant_folder_id:
                logger.error("Failed to create tenant folder", tenant_name=tenant_name)
                return None
            
            logger.info("Tenant folder ready", tenant_name=tenant_name, folder_id=tenant_folder_id)
            
            # Generate proper file name with version numbering
            base_file_name = self._generate_file_name(file_name, tenant_name, document_type)
            
            # Check if this document type already exists and get version number
            version_number = await self._get_next_version_number(tenant_name, document_type, base_file_name)
            
            # Add version number if needed
            if version_number > 1:
                # Insert version number before file extension
                if '.' in base_file_name:
                    name_part, ext_part = base_file_name.rsplit('.', 1)
                    proper_file_name = f"{name_part}({version_number}).{ext_part}"
                else:
                    proper_file_name = f"{base_file_name}({version_number})"
            else:
                proper_file_name = base_file_name
            
            logger.info("Generated file name with version", 
                       original_name=file_name, 
                       proper_name=proper_file_name,
                       version_number=version_number)
            
            # Create file metadata
            file_metadata = {
                'name': proper_file_name,
                'parents': [tenant_folder_id]
            }
            logger.info("File metadata created", metadata=file_metadata)
            
            # Create media upload
            media = MediaIoBaseUpload(
                io.BytesIO(file_data),
                mimetype=mime_type,
                resumable=True
            )
            logger.info("Media upload object created", mime_type=mime_type, file_size=len(file_data))
            
            # Upload the file
            logger.info("Starting file upload to Google Drive...")
            file = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id,name,size,createdTime,webViewLink'
            ).execute()
            logger.info("File upload completed", file_id=file.get('id'))
            
            file_info = {
                'id': file.get('id'),
                'name': file.get('name'),
                'size': file.get('size'),
                'created_time': file.get('createdTime'),
                'web_view_link': file.get('webViewLink'),
                'folder_id': tenant_folder_id
            }
            
            logger.info("Document uploaded successfully", 
                       tenant_name=tenant_name, 
                       document_type=document_type,
                       file_id=file_info['id'],
                       file_name=file_info['name'])
            
            return file_info
            
        except HttpError as error:
            logger.error("Error uploading document", 
                        tenant_name=tenant_name, 
                        document_type=document_type, 
                        error=str(error))
            return None
        except Exception as e:
            logger.error("Unexpected error uploading document", 
                        tenant_name=tenant_name, 
                        document_type=document_type, 
                        error=str(e))
            return None
    
    def _generate_file_name(self, original_name: str, tenant_name: str, document_type: str) -> str:
        """
        Generate a proper file name with version numbering for multiple uploads.
        Format: DocumentType_TenantName_Date.ext or DocumentType_TenantName_Date(2).ext
        
        Args:
            original_name: Original file name
            tenant_name: Name of the tenant
            document_type: Type of document
            
        Returns:
            Properly formatted file name with version number if needed
        """
        # Get current date
        current_date = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Get file extension
        file_extension = ""
        if '.' in original_name:
            file_extension = original_name.split('.')[-1]
        
        # Clean tenant name for filename
        clean_tenant_name = tenant_name.replace(' ', '_').replace('/', '_').replace('\\', '_')
        
        # Generate base filename
        base_name = f"{document_type}_{clean_tenant_name}_{current_date}"
        
        if file_extension:
            base_name += f".{file_extension}"
        
        return base_name
    
    async def _get_next_version_number(self, tenant_name: str, document_type: str, base_name: str) -> int:
        """
        Get the next version number for a document type for a specific tenant.
        
        Args:
            tenant_name: Name of the tenant
            document_type: Type of document
            base_name: Base file name without version
            
        Returns:
            Next version number (1, 2, 3, etc.)
        """
        try:
            # Get all documents for the tenant
            documents = await self.get_tenant_documents(tenant_name)
            
            # Filter documents by type
            same_type_docs = []
            for doc in documents:
                doc_name = doc.get('name', '')
                if document_type in doc_name:
                    same_type_docs.append(doc_name)
            
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
            logger.error("Error getting version number", tenant_name=tenant_name, error=str(e))
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
            # Find tenant folder
            tenant_folder_id = await self._find_tenant_folder(tenant_name)
            if not tenant_folder_id:
                logger.warning("Tenant folder not found", tenant_name=tenant_name)
                return []
            
            # List files in the folder
            results = self.service.files().list(
                q=f"'{tenant_folder_id}' in parents",
                fields='files(id,name,size,createdTime,webViewLink,mimeType)'
            ).execute()
            
            files = results.get('files', [])
            
            # Filter out folders
            documents = []
            for file in files:
                if file.get('mimeType') != 'application/vnd.google-apps.folder':
                    documents.append({
                        'id': file.get('id'),
                        'name': file.get('name'),
                        'size': file.get('size'),
                        'created_time': file.get('createdTime'),
                        'web_view_link': file.get('webViewLink'),
                        'mime_type': file.get('mimeType')
                    })
            
            logger.info("Retrieved tenant documents", 
                       tenant_name=tenant_name, 
                       document_count=len(documents))
            
            return documents
            
        except Exception as e:
            logger.error("Error retrieving tenant documents", 
                        tenant_name=tenant_name, 
                        error=str(e))
            return []
    
    async def delete_document(self, file_id: str) -> bool:
        """
        Delete a document from Google Drive.
        
        Args:
            file_id: ID of the file to delete
            
        Returns:
            True if successful, False otherwise
        """
        self._ensure_initialized()
        
        try:
            self.service.files().delete(fileId=file_id).execute()
            logger.info("Document deleted successfully", file_id=file_id)
            return True
            
        except HttpError as error:
            logger.error("Error deleting document", file_id=file_id, error=str(error))
            return False
        except Exception as e:
            logger.error("Unexpected error deleting document", file_id=file_id, error=str(e))
            return False
    
    async def get_document_info(self, file_id: str) -> Optional[Dict[str, Any]]:
        """
        Get information about a specific document.
        
        Args:
            file_id: ID of the file
            
        Returns:
            Document information if found, None otherwise
        """
        self._ensure_initialized()
        
        try:
            file = self.service.files().get(
                fileId=file_id,
                fields='id,name,size,createdTime,modifiedTime,webViewLink,mimeType,parents'
            ).execute()
            
            return {
                'id': file.get('id'),
                'name': file.get('name'),
                'size': file.get('size'),
                'created_time': file.get('createdTime'),
                'modified_time': file.get('modifiedTime'),
                'web_view_link': file.get('webViewLink'),
                'mime_type': file.get('mimeType'),
                'parents': file.get('parents', [])
            }
            
        except HttpError as error:
            logger.error("Error getting document info", file_id=file_id, error=str(error))
            return None
        except Exception as e:
            logger.error("Unexpected error getting document info", file_id=file_id, error=str(e))
            return None


# Global instance
google_drive_service = GoogleDriveService()
