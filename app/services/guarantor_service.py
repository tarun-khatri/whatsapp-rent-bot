"""
Guarantor Service

This service handles all database operations for guarantors including:
- Creating guarantor records
- Linking guarantors to tenants
- Managing guarantor conversation states
- Tracking guarantor document uploads
"""

import logging
from typing import Dict, Any, Optional, List
from datetime import datetime

from app.services.supabase_service import supabase_service

logger = logging.getLogger(__name__)


class GuarantorService:
    """Service for managing guarantor data and operations."""
    
    def __init__(self):
        self.supabase = supabase_service
    
    async def create_guarantor(self, tenant_id: str, guarantor_number: int, 
                             full_name: str, phone_number: str, email: str = None) -> Dict[str, Any]:
        """Create a new guarantor record."""
        try:
            logger.info("Creating guarantor", extra={
                "tenant_id": tenant_id,
                "guarantor_number": guarantor_number,
                "full_name": full_name,
                "phone_number": phone_number
            })
            
            # Check if guarantor already exists
            existing_guarantors = await self.get_guarantors_by_tenant(tenant_id)
            for existing_guarantor in existing_guarantors:
                if existing_guarantor.get("guarantor_number") == guarantor_number:
                    logger.info("Guarantor already exists, updating instead", extra={
                        "guarantor_id": existing_guarantor.get("id"),
                        "guarantor_number": guarantor_number
                    })
                    
                    # Update existing guarantor
                    from app.models.tenant import GuarantorUpdate
                    updates = GuarantorUpdate(
                        full_name=full_name,
                        phone_number=phone_number,
                        email=email
                    )
                    
                    updated_guarantor = await self.supabase.update_guarantor(existing_guarantor["id"], updates)
                    
                    return {
                        "success": True,
                        "guarantor": updated_guarantor.dict(),
                        "was_existing": True
                    }
            
            # Create new guarantor record using SupabaseService
            from app.models.tenant import GuarantorCreate
            
            guarantor_data = GuarantorCreate(
                tenant_id=tenant_id,
                guarantor_number=guarantor_number,
                full_name=full_name,
                phone_number=phone_number,
                email=email,
                whatsapp_status="not_started",
                documents_status={},
                conversation_state={}
            )
            
            guarantor = await self.supabase.create_guarantor(guarantor_data)
            
            logger.info("Guarantor created successfully", extra={
                "guarantor_id": guarantor.id,
                "guarantor_number": guarantor_number
            })
            
            # Link guarantor to tenant
            await self._link_guarantor_to_tenant(tenant_id, guarantor.id, guarantor_number)
            
            return {
                "success": True,
                "guarantor": guarantor.dict(),
                "was_existing": False
            }
                
        except Exception as e:
            logger.error("Error creating guarantor", extra={"error": str(e)})
            return {
                "success": False,
                "error": f"Error creating guarantor: {str(e)}"
            }
    
    async def _link_guarantor_to_tenant(self, tenant_id: str, guarantor_id: str, guarantor_number: int):
        """Link guarantor to tenant in the tenants table."""
        try:
            from app.models.tenant import TenantUpdate
            
            update_data = {}
            if guarantor_number == 1:
                update_data["guarantor1_id"] = guarantor_id
            elif guarantor_number == 2:
                update_data["guarantor2_id"] = guarantor_id
            
            if update_data:
                tenant_update = TenantUpdate(**update_data)
                result = await self.supabase.update_tenant(tenant_id, tenant_update)
                
                if result:
                    logger.info("Guarantor linked to tenant", extra={
                        "tenant_id": tenant_id,
                        "guarantor_id": guarantor_id,
                        "guarantor_number": guarantor_number
                    })
                else:
                    logger.error("Failed to link guarantor to tenant", extra={
                        "tenant_id": tenant_id,
                        "guarantor_id": guarantor_id,
                        "guarantor_number": guarantor_number
                    })
                
        except Exception as e:
            logger.error("Error linking guarantor to tenant", extra={"error": str(e)})
    
    async def get_guarantor_by_phone(self, phone_number: str) -> Optional[Dict[str, Any]]:
        """Get guarantor by phone number."""
        try:
            # Ensure Supabase is initialized
            self.supabase._ensure_initialized()
            
            guarantor = await self.supabase.find_guarantor_by_phone(phone_number)
            
            if guarantor:
                return guarantor.dict()
            return None
            
        except Exception as e:
            logger.error("Error getting guarantor by phone", extra={"error": str(e)})
            return None
    
    async def get_guarantor_by_id(self, guarantor_id: str) -> Optional[Dict[str, Any]]:
        """Get guarantor by ID."""
        try:
            guarantor = await self.supabase.get_guarantor_by_id(guarantor_id)
            
            if guarantor:
                return guarantor.dict()
            return None
            
        except Exception as e:
            logger.error("Error getting guarantor by ID", extra={"error": str(e)})
            return None
    
    async def get_guarantors_by_tenant(self, tenant_id: str) -> List[Dict[str, Any]]:
        """Get all guarantors for a tenant."""
        try:
            guarantors = await self.supabase.get_guarantors_by_tenant(tenant_id)
            
            return [guarantor.dict() for guarantor in guarantors]
            
        except Exception as e:
            logger.error("Error getting guarantors by tenant", extra={"error": str(e)})
            return []
    
    async def update_guarantor_status(self, guarantor_id: str, status: str) -> bool:
        """Update guarantor WhatsApp status."""
        try:
            from app.models.tenant import GuarantorUpdate
            
            updates = GuarantorUpdate(
                whatsapp_status=status
            )
            
            result = await self.supabase.update_guarantor(guarantor_id, updates)
            
            return result is not None
            
        except Exception as e:
            logger.error("Error updating guarantor status", extra={"error": str(e)})
            return False
    
    async def update_guarantor_documents_status(self, guarantor_id: str, document_type: str, 
                                             status: str, file_url: str = None) -> bool:
        """Update guarantor documents status."""
        try:
            # Get current documents status
            guarantor = await self.get_guarantor_by_id(guarantor_id)
            if not guarantor:
                return False
            
            documents_status = guarantor.get("documents_status", {})
            documents_status[document_type] = {
                "status": status,
                "file_url": file_url,
                "updated_at": datetime.now().isoformat()
            }
            
            from app.models.tenant import GuarantorUpdate
            
            updates = GuarantorUpdate(
                documents_status=documents_status
            )
            
            result = await self.supabase.update_guarantor(guarantor_id, updates)
            
            return result is not None
            
        except Exception as e:
            logger.error("Error updating guarantor documents status", extra={"error": str(e)})
            return False
    
    async def get_guarantor_conversation_state(self, phone_number: str) -> Optional[Dict[str, Any]]:
        """Get guarantor conversation state."""
        try:
            return await self.supabase.get_guarantor_conversation_state(phone_number)
            
        except Exception as e:
            logger.error("Error getting guarantor conversation state", extra={"error": str(e)})
            return None
    
    async def update_guarantor_conversation_state(self, guarantor_id: str, phone_number: str, 
                                                 current_state: str, context_data: Dict[str, Any] = None) -> bool:
        """Update guarantor conversation state."""
        try:
            return await self.supabase.update_guarantor_conversation_state(
                guarantor_id, phone_number, current_state, context_data
            )
            
        except Exception as e:
            logger.error("Error updating guarantor conversation state", extra={"error": str(e)})
            return False
    
    async def get_tenant_by_guarantor(self, guarantor_id: str) -> Optional[Dict[str, Any]]:
        """Get tenant information by guarantor ID."""
        try:
            # Get guarantor first
            guarantor = await self.get_guarantor_by_id(guarantor_id)
            if not guarantor:
                return None
            
            # Get tenant
            result = self.supabase.table("tenants").select("*").eq("id", guarantor["tenant_id"]).execute()
            
            if result.data:
                return result.data[0]
            return None
            
        except Exception as e:
            logger.error("Error getting tenant by guarantor", extra={"error": str(e)})
            return None
    
    async def check_guarantor_completion(self, tenant_id: str) -> Dict[str, Any]:
        """Check if all guarantors have completed their documents."""
        try:
            guarantors = await self.get_guarantors_by_tenant(tenant_id)
            
            if not guarantors:
                return {
                    "all_completed": False,
                    "completed_count": 0,
                    "total_count": 0,
                    "guarantors": []
                }
            
            completed_count = 0
            guarantor_status = []
            
            for guarantor in guarantors:
                documents_status = guarantor.get("documents_status", {})
                required_docs = ["id_card", "sephach", "payslips", "pnl", "bank_statements"]
                
                completed_docs = 0
                for doc_type in required_docs:
                    if documents_status.get(doc_type, {}).get("status") == "validated":
                        completed_docs += 1
                
                is_completed = completed_docs >= len(required_docs)
                if is_completed:
                    completed_count += 1
                
                guarantor_status.append({
                    "guarantor_id": guarantor["id"],
                    "guarantor_number": guarantor["guarantor_number"],
                    "full_name": guarantor["full_name"],
                    "is_completed": is_completed,
                    "completed_docs": completed_docs,
                    "total_docs": len(required_docs)
                })
            
            all_completed = completed_count == len(guarantors)
            
            return {
                "all_completed": all_completed,
                "completed_count": completed_count,
                "total_count": len(guarantors),
                "guarantors": guarantor_status
            }
            
        except Exception as e:
            logger.error("Error checking guarantor completion", extra={"error": str(e)})
            return {
                "all_completed": False,
                "completed_count": 0,
                "total_count": 0,
                "guarantors": []
            }


# Global instance
guarantor_service = GuarantorService()
