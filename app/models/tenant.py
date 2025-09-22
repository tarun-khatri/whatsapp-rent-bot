from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime, date
from enum import Enum


class WhatsAppStatus(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    STUCK = "stuck"


class ConversationState(str, Enum):
    GREETING = "GREETING"
    CONFIRMATION = "CONFIRMATION"
    PERSONAL_INFO = "PERSONAL_INFO"
    DOCUMENTS = "DOCUMENTS"
    GUARANTOR_1 = "GUARANTOR_1"
    GUARANTOR_2 = "GUARANTOR_2"
    COMPLETED = "COMPLETED"


class DocumentType(str, Enum):
    ID_CARD = "id_card"
    SEPHACH = "sephach"
    PAYSLIPS = "payslips"
    PNL = "pnl"
    BANK_STATEMENTS = "bank_statements"


class DocumentStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    VALIDATED = "validated"
    REJECTED = "rejected"
    ERROR = "error"


class TenantBase(BaseModel):
    full_name: str
    phone_number: str
    id_number: Optional[str] = None  # Israeli ID number
    property_name: str
    apartment_number: str
    number_of_rooms: int
    monthly_rent_amount: float
    move_in_date: date
    has_co_tenants: Optional[bool] = False
    co_tenant_names: Optional[str] = None
    whatsapp_status: Optional[WhatsAppStatus] = WhatsAppStatus.NOT_STARTED
    occupation: Optional[str] = None
    family_status: Optional[str] = None
    number_of_children: Optional[int] = 0
    documents_status: Optional[Dict[str, Any]] = {}
    guarantor1_name: Optional[str] = None
    guarantor1_phone: Optional[str] = None
    guarantor2_name: Optional[str] = None
    guarantor2_phone: Optional[str] = None
    conversation_state: Optional[Dict[str, Any]] = {}


class TenantCreate(TenantBase):
    pass


class TenantUpdate(BaseModel):
    full_name: Optional[str] = None
    phone_number: Optional[str] = None
    id_number: Optional[str] = None
    property_name: Optional[str] = None
    apartment_number: Optional[str] = None
    number_of_rooms: Optional[int] = None
    monthly_rent_amount: Optional[float] = None
    move_in_date: Optional[date] = None
    has_co_tenants: Optional[bool] = None
    co_tenant_names: Optional[str] = None
    whatsapp_status: Optional[WhatsAppStatus] = None
    occupation: Optional[str] = None
    family_status: Optional[str] = None
    number_of_children: Optional[int] = None
    documents_status: Optional[Dict[str, Any]] = None
    guarantor1_name: Optional[str] = None
    guarantor1_phone: Optional[str] = None
    guarantor2_name: Optional[str] = None
    guarantor2_phone: Optional[str] = None
    conversation_state: Optional[Dict[str, Any]] = None


class Tenant(TenantBase):
    id: str
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ConversationStateModel(BaseModel):
    phone_number: str
    current_state: ConversationState
    context_data: Optional[Dict[str, Any]] = {}
    last_message_time: Optional[datetime] = None


class ConversationStateCreate(ConversationStateModel):
    pass


class ConversationStateUpdate(BaseModel):
    current_state: Optional[ConversationState] = None
    context_data: Optional[Dict[str, Any]] = None
    last_message_time: Optional[datetime] = None


class ConversationStateResponse(ConversationStateModel):
    id: str
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class DocumentUpload(BaseModel):
    tenant_id: str
    document_type: DocumentType
    file_url: Optional[str] = None
    file_name: Optional[str] = None
    processing_status: Optional[DocumentStatus] = DocumentStatus.PENDING
    extracted_data: Optional[Dict[str, Any]] = None
    validation_result: Optional[Dict[str, Any]] = None


class DocumentUploadCreate(DocumentUpload):
    pass


class DocumentUploadUpdate(BaseModel):
    file_url: Optional[str] = None
    file_name: Optional[str] = None
    processing_status: Optional[DocumentStatus] = None
    extracted_data: Optional[Dict[str, Any]] = None
    validation_result: Optional[Dict[str, Any]] = None


class DocumentUploadResponse(DocumentUpload):
    id: str
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class GuarantorBase(BaseModel):
    tenant_id: str
    guarantor_number: int
    full_name: str
    phone_number: str
    email: Optional[str] = None
    whatsapp_status: Optional[WhatsAppStatus] = WhatsAppStatus.NOT_STARTED
    documents_status: Optional[Dict[str, Any]] = {}
    conversation_state: Optional[Dict[str, Any]] = {}


class Guarantor(GuarantorBase):
    id: str
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class GuarantorCreate(GuarantorBase):
    pass


class GuarantorUpdate(BaseModel):
    full_name: Optional[str] = None
    phone_number: Optional[str] = None
    email: Optional[str] = None
    whatsapp_status: Optional[WhatsAppStatus] = None
    documents_status: Optional[Dict[str, Any]] = None
    conversation_state: Optional[Dict[str, Any]] = None


class GuarantorResponse(Guarantor):
    id: str
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class WhatsAppMessage(BaseModel):
    wa_id: str
    name: str
    message_body: str
    message_type: str = "text"
    media_url: Optional[str] = None
    media_type: Optional[str] = None


class WhatsAppResponse(BaseModel):
    recipient: str
    message: str
    message_type: str = "text"
