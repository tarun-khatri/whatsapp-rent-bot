import logging
import structlog
from typing import Optional, Dict, Any, List
from datetime import datetime
from supabase import create_client, Client
from flask import current_app

from ..models.tenant import (
    Tenant, TenantCreate, TenantUpdate,
    ConversationStateModel, ConversationStateCreate, ConversationStateUpdate,
    DocumentUpload, DocumentUploadCreate, DocumentUploadUpdate,
    Guarantor, GuarantorCreate, GuarantorUpdate,
    WhatsAppStatus, ConversationState, DocumentType, DocumentStatus
)

logger = structlog.get_logger(__name__)


class SupabaseService:
    def __init__(self):
        self.client: Optional[Client] = None
        self._initialized = False
        logger.info("SupabaseService instance created")

    def _ensure_initialized(self):
        """Ensure the service is initialized with Flask app context."""
        logger.info("_ensure_initialized called", initialized=self._initialized, client_exists=bool(self.client))
        if not self._initialized:
            try:
                logger.info("Initializing Supabase service...")
                
                supabase_url = current_app.config.get("SUPABASE_URL")
                supabase_key = current_app.config.get("SUPABASE_PUBLISHABLE_KEY")
                
                logger.info("Supabase configuration loaded", 
                           url=supabase_url, 
                           key_length=len(supabase_key) if supabase_key else 0)
                
                if not supabase_url or not supabase_key:
                    logger.error("Supabase credentials missing", 
                               url_present=bool(supabase_url), 
                               key_present=bool(supabase_key))
                    raise ValueError("Supabase URL and key must be configured")
                
                logger.info("Creating Supabase client...")
                self.client = create_client(supabase_url, supabase_key)
                self._initialized = True
                logger.info("Supabase client initialized successfully")
                
                # Test the connection
                logger.info("Testing Supabase connection...")
                test_response = self.client.table("tenants").select("id").limit(1).execute()
                logger.info("Supabase connection test successful", 
                           response_count=len(test_response.data) if test_response.data else 0)
                
            except Exception as e:
                logger.error("Failed to initialize Supabase client", 
                           error=str(e), 
                           error_type=type(e).__name__)
                raise

    def _check_client(self):
        """Check if client is available, return False if not."""
        if not self.client:
            logger.error("Supabase client is None - initialization failed")
            return False
        return True

    # Tenant Management
    async def find_tenant_by_phone(self, phone: str) -> Optional[Tenant]:
        """Find tenant by normalized phone number."""
        logger.info("find_tenant_by_phone called", phone=phone, client_exists=bool(self.client))
        self._ensure_initialized()
        
        if not self.client:
            logger.error("Supabase client is None - initialization failed")
            return None
            
        try:
            logger.info("Searching for tenant with phone", phone=phone)
            
            # Try exact match first
            response = self.client.table("tenants").select("*").eq("phone_number", phone).execute()
            logger.info("Supabase query executed", 
                       phone=phone, 
                       response_count=len(response.data) if response.data else 0)
            
            if response.data:
                logger.info("Found tenant with exact phone match", phone=phone)
                tenant_data = response.data[0]
                return Tenant(**tenant_data)
            
            # Try without + prefix
            phone_without_plus = phone.lstrip('+')
            logger.info("Trying without + prefix", phone_without_plus=phone_without_plus)
            response = self.client.table("tenants").select("*").eq("phone_number", phone_without_plus).execute()
            
            if response.data:
                logger.info("Found tenant without + prefix", phone=phone_without_plus)
                tenant_data = response.data[0]
                return Tenant(**tenant_data)
            
            # Try with + prefix if original didn't have it
            if not phone.startswith('+'):
                phone_with_plus = f"+{phone}"
                logger.info("Trying with + prefix", phone_with_plus=phone_with_plus)
                response = self.client.table("tenants").select("*").eq("phone_number", phone_with_plus).execute()
                
                if response.data:
                    logger.info("Found tenant with + prefix", phone=phone_with_plus)
                    tenant_data = response.data[0]
                    return Tenant(**tenant_data)
            
            # Try without international code (remove country code)
            if phone.startswith('+91'):
                phone_without_country = phone[3:]  # Remove +91
                logger.info("Trying without country code", phone_without_country=phone_without_country)
                response = self.client.table("tenants").select("*").eq("phone_number", phone_without_country).execute()
                
                if response.data:
                    logger.info("Found tenant without country code", phone=phone_without_country)
                    tenant_data = response.data[0]
                    return Tenant(**tenant_data)
            
            # Try with international code if original didn't have it
            if not phone.startswith('+91') and len(phone) == 10:
                phone_with_country = f"+91{phone}"
                logger.info("Trying with country code", phone_with_country=phone_with_country)
                response = self.client.table("tenants").select("*").eq("phone_number", phone_with_country).execute()
                
                if response.data:
                    logger.info("Found tenant with country code", phone=phone_with_country)
                    tenant_data = response.data[0]
                    return Tenant(**tenant_data)
            
            logger.warning("No tenant found with any phone format", phone=phone)
            return None
        except Exception as e:
            logger.error("Error finding tenant by phone", phone=phone, error=str(e), error_type=type(e).__name__)
            raise

    async def create_tenant(self, tenant_data: TenantCreate) -> Tenant:
        """Create a new tenant record."""
        try:
            response = self.client.table("tenants").insert(tenant_data.dict()).execute()
            
            if response.data:
                return Tenant(**response.data[0])
            raise Exception("Failed to create tenant")
        except Exception as e:
            logger.error("Error creating tenant", error=str(e))
            raise

    async def update_tenant(self, tenant_id: str, updates: TenantUpdate) -> Optional[Tenant]:
        """Update tenant information."""
        try:
            update_data = {k: v for k, v in updates.dict().items() if v is not None}
            if not update_data:
                return await self.get_tenant_by_id(tenant_id)
            
            response = self.client.table("tenants").update(update_data).eq("id", tenant_id).execute()
            
            if response.data:
                return Tenant(**response.data[0])
            return None
        except Exception as e:
            logger.error("Error updating tenant", tenant_id=tenant_id, error=str(e))
            raise

    async def get_tenant_by_id(self, tenant_id: str) -> Optional[Tenant]:
        """Get tenant by ID."""
        try:
            response = self.client.table("tenants").select("*").eq("id", tenant_id).execute()
            
            if response.data:
                return Tenant(**response.data[0])
            return None
        except Exception as e:
            logger.error("Error getting tenant by ID", tenant_id=tenant_id, error=str(e))
            raise

    async def update_tenant_whatsapp_status(self, tenant_id: str, status: WhatsAppStatus) -> bool:
        """Update tenant WhatsApp status."""
        try:
            response = self.client.table("tenants").update({
                "whatsapp_status": status.value
            }).eq("id", tenant_id).execute()
            
            return len(response.data) > 0
        except Exception as e:
            logger.error("Error updating tenant WhatsApp status", tenant_id=tenant_id, status=status, error=str(e))
            raise

    # Conversation State Management
    async def get_conversation_state(self, phone: str) -> Optional[ConversationStateModel]:
        """Get conversation state for a phone number."""
        self._ensure_initialized()
        
        if not self._check_client():
            return None
            
        try:
            response = self.client.table("conversation_states").select("*").eq("phone_number", phone).execute()
            
            if response.data:
                state_data = response.data[0]
                return ConversationStateModel(**state_data)
            return None
        except Exception as e:
            logger.error("Error getting conversation state", phone=phone, error=str(e))
            raise

    async def create_conversation_state(self, state_data: ConversationStateCreate) -> ConversationStateModel:
        """Create a new conversation state."""
        try:
            # Convert datetime to string for JSON serialization
            data_dict = state_data.dict()
            if data_dict.get('last_message_time'):
                data_dict['last_message_time'] = data_dict['last_message_time'].isoformat()
            
            response = self.client.table("conversation_states").insert(data_dict).execute()
            
            if response.data:
                return ConversationStateModel(**response.data[0])
            raise Exception("Failed to create conversation state")
        except Exception as e:
            logger.error("Error creating conversation state", error=str(e))
            raise

    async def update_conversation_state(self, phone: str, updates: ConversationStateUpdate) -> Optional[ConversationStateModel]:
        """Update conversation state."""
        try:
            update_data = {k: v for k, v in updates.dict().items() if v is not None}
            if not update_data:
                return await self.get_conversation_state(phone)
            
            # Convert datetime to string for JSON serialization
            if update_data.get('last_message_time'):
                update_data['last_message_time'] = update_data['last_message_time'].isoformat()
            
            response = self.client.table("conversation_states").update(update_data).eq("phone_number", phone).execute()
            
            if response.data:
                return ConversationStateModel(**response.data[0])
            return None
        except Exception as e:
            logger.error("Error updating conversation state", phone=phone, error=str(e))
            raise

    async def delete_conversation_state(self, phone: str) -> bool:
        """Delete conversation state."""
        try:
            response = self.client.table("conversation_states").delete().eq("phone_number", phone).execute()
            return True
        except Exception as e:
            logger.error("Error deleting conversation state", phone=phone, error=str(e))
            raise

    # Document Management
    async def create_document_upload(self, document_data: DocumentUploadCreate) -> DocumentUpload:
        """Create a new document upload record."""
        try:
            response = self.client.table("document_uploads").insert(document_data.dict()).execute()
            
            if response.data:
                return DocumentUpload(**response.data[0])
            raise Exception("Failed to create document upload")
        except Exception as e:
            logger.error("Error creating document upload", error=str(e))
            raise

    async def update_document_upload(self, document_id: str, updates: DocumentUploadUpdate) -> Optional[DocumentUpload]:
        """Update document upload record."""
        try:
            update_data = {k: v for k, v in updates.dict().items() if v is not None}
            if not update_data:
                return await self.get_document_upload_by_id(document_id)
            
            response = self.client.table("document_uploads").update(update_data).eq("id", document_id).execute()
            
            if response.data:
                return DocumentUpload(**response.data[0])
            return None
        except Exception as e:
            logger.error("Error updating document upload", document_id=document_id, error=str(e))
            raise

    async def get_document_upload_by_id(self, document_id: str) -> Optional[DocumentUpload]:
        """Get document upload by ID."""
        try:
            response = self.client.table("document_uploads").select("*").eq("id", document_id).execute()
            
            if response.data:
                return DocumentUpload(**response.data[0])
            return None
        except Exception as e:
            logger.error("Error getting document upload by ID", document_id=document_id, error=str(e))
            raise

    async def get_tenant_documents(self, tenant_id: str) -> List[DocumentUpload]:
        """Get all documents for a tenant."""
        try:
            response = self.client.table("document_uploads").select("*").eq("tenant_id", tenant_id).execute()
            
            return [DocumentUpload(**doc) for doc in response.data]
        except Exception as e:
            logger.error("Error getting tenant documents", tenant_id=tenant_id, error=str(e))
            raise

    async def update_tenant_documents_status(self, tenant_id: str, document_type: DocumentType, status: DocumentStatus, file_url: str = None) -> bool:
        """Update tenant's documents status."""
        try:
            # Get current documents status
            tenant = await self.get_tenant_by_id(tenant_id)
            if not tenant:
                return False
            
            documents_status = tenant.documents_status or {}
            documents_status[document_type.value] = {
                "status": status.value,
                "file_url": file_url,
                "updated_at": datetime.utcnow().isoformat()
            }
            
            response = self.client.table("tenants").update({
                "documents_status": documents_status
            }).eq("id", tenant_id).execute()
            
            return len(response.data) > 0
        except Exception as e:
            logger.error("Error updating tenant documents status", tenant_id=tenant_id, document_type=document_type, error=str(e))
            raise

    # Guarantor Management
    async def create_guarantor(self, guarantor_data: GuarantorCreate) -> Guarantor:
        """Create a new guarantor record."""
        try:
            response = self.client.table("guarantors").insert(guarantor_data.dict()).execute()
            
            if response.data:
                return Guarantor(**response.data[0])
            raise Exception("Failed to create guarantor")
        except Exception as e:
            logger.error("Error creating guarantor", error=str(e))
            raise

    async def get_guarantors_by_tenant(self, tenant_id: str) -> List[Guarantor]:
        """Get all guarantors for a tenant."""
        try:
            response = self.client.table("guarantors").select("*").eq("tenant_id", tenant_id).execute()
            
            return [Guarantor(**guarantor) for guarantor in response.data]
        except Exception as e:
            logger.error("Error getting guarantors by tenant", tenant_id=tenant_id, error=str(e))
            raise

    async def update_guarantor(self, guarantor_id: str, updates: GuarantorUpdate) -> Optional[Guarantor]:
        """Update guarantor information."""
        try:
            update_data = {k: v for k, v in updates.dict().items() if v is not None}
            if not update_data:
                return await self.get_guarantor_by_id(guarantor_id)
            
            response = self.client.table("guarantors").update(update_data).eq("id", guarantor_id).execute()
            
            if response.data:
                return Guarantor(**response.data[0])
            return None
        except Exception as e:
            logger.error("Error updating guarantor", guarantor_id=guarantor_id, error=str(e))
            raise

    async def get_guarantor_by_id(self, guarantor_id: str) -> Optional[Guarantor]:
        """Get guarantor by ID."""
        try:
            response = self.client.table("guarantors").select("*").eq("id", guarantor_id).execute()
            
            if response.data:
                return Guarantor(**response.data[0])
            return None
        except Exception as e:
            logger.error("Error getting guarantor by ID", guarantor_id=guarantor_id, error=str(e))
            raise

    async def find_guarantor_by_phone(self, phone: str) -> Optional[Guarantor]:
        """Find guarantor by phone number."""
        try:
            self._ensure_initialized()
            if not self._check_client():
                return None
                
            response = self.client.table("guarantors").select("*").eq("phone_number", phone).execute()
            
            if response.data:
                return Guarantor(**response.data[0])
            return None
        except Exception as e:
            logger.error("Error finding guarantor by phone", phone=phone, error=str(e))
            # Don't raise the exception, return None instead
            return None

    # Utility Methods
    async def get_missing_documents(self, tenant_id: str) -> List[DocumentType]:
        """Get list of missing documents for a tenant."""
        try:
            tenant = await self.get_tenant_by_id(tenant_id)
            if not tenant:
                return list(DocumentType)
            
            documents_status = tenant.documents_status or {}
            missing_docs = []
            
            for doc_type in DocumentType:
                if doc_type.value not in documents_status or documents_status[doc_type.value].get("status") != DocumentStatus.VALIDATED.value:
                    missing_docs.append(doc_type)
            
            return missing_docs
        except Exception as e:
            logger.error("Error getting missing documents", tenant_id=tenant_id, error=str(e))
            raise

    async def mark_process_completed(self, tenant_id: str) -> bool:
        """Mark the entire process as completed for a tenant."""
        try:
            response = self.client.table("tenants").update({
                "whatsapp_status": WhatsAppStatus.COMPLETED.value
            }).eq("id", tenant_id).execute()
            
            return len(response.data) > 0
        except Exception as e:
            logger.error("Error marking process completed", tenant_id=tenant_id, error=str(e))
            raise


    # Guarantor Conversation State Methods
    async def get_guarantor_conversation_state(self, phone_number: str) -> Optional[Dict[str, Any]]:
        """Get guarantor conversation state by phone number."""
        try:
            self._ensure_initialized()
            if not self._check_client():
                return None
            
            response = self.client.table("guarantor_conversation_states").select("*").eq("phone_number", phone_number).execute()
            
            if response.data:
                return response.data[0]
            return None
            
        except Exception as e:
            logger.error("Error getting guarantor conversation state", phone=phone_number, error=str(e))
            return None
    
    async def update_guarantor_conversation_state(self, guarantor_id: str, phone_number: str, 
                                                 current_state: str, context_data: Dict[str, Any] = None) -> bool:
        """Update guarantor conversation state."""
        try:
            self._ensure_initialized()
            if not self._check_client():
                return False
            
            # Check if conversation state exists
            existing = await self.get_guarantor_conversation_state(phone_number)
            
            if existing:
                # Update existing
                response = self.client.table("guarantor_conversation_states").update({
                    "current_state": current_state,
                    "context_data": context_data or {},
                    "last_message_time": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat()
                }).eq("id", existing["id"]).execute()
            else:
                # Create new
                response = self.client.table("guarantor_conversation_states").insert({
                    "guarantor_id": guarantor_id,
                    "phone_number": phone_number,
                    "current_state": current_state,
                    "context_data": context_data or {},
                    "last_message_time": datetime.now().isoformat()
                }).execute()
            
            return len(response.data) > 0 if response.data else False
            
        except Exception as e:
            logger.error("Error updating guarantor conversation state", extra={"error": str(e)})
            return False


# Global instance
supabase_service = SupabaseService()
