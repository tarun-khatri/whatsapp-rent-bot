"""
Message templates for WhatsApp bot in Hebrew and English.
"""

# Hebrew Templates
GREETING_HE = "שלום {name}, זה יוני ממגורית. אנחנו שמחים שהחלטת להצטרף למשפחת מגורית ב{property}."

CONFIRM_DETAILS_HE = """אנא אשר את הפרטים הבאים:
• מספר דירה: {apartment_number}
• מספר חדרים: {number_of_rooms}
• תאריך כניסה: {move_in_date}
• שכר דירה חודשי: ₪{monthly_rent_amount}

הפרטים נכונים? השיב 'כן' או 'אישור' אם הכל תקין, או ספר לי מה צריך לשנות."""

PERSONAL_INFO_OCCUPATION_HE = "מה העיסוק שלך?"
PERSONAL_INFO_FAMILY_STATUS_HE = "מה המצב המשפחתי שלך? (רווק/נשוי/גרוש/אלמן)"
PERSONAL_INFO_CHILDREN_HE = "כמה ילדים יש לך?"

DOCUMENT_REQUEST_ID_HE = "אנא שלח את תמונת תעודת הזהות שלך (Teudat Zehut)."
DOCUMENT_REQUEST_SEPHACH_HE = "אנא שלח את הטופס ספח (Sephach)."
DOCUMENT_REQUEST_PAYSLIPS_HE = "אנא שלח את 3 תלושי השכר האחרונים שלך (כקובץ PDF או תמונות)."
DOCUMENT_REQUEST_BANK_HE = "אנא שלח את דוחות הבנק של 3 החודשים האחרונים."

GUARANTOR_REQUEST_HE = "אנא שלח את השם ומספר הטלפון של הערב {guarantor_number}."
GUARANTOR_CONFIRMATION_HE = "תודה! פרטי הערב {guarantor_number} התקבלו."

COMPLETION_MESSAGE_HE = "מעולה! כל המידע התקבל. התהליך הושלם בהצלחה! תודה שהצטרפת למשפחת מגורית."

ERROR_MESSAGE_HE = "מצטער, אירעה שגיאה. אנא נסה שוב או פנה לצוות התמיכה."
INVALID_DOCUMENT_HE = "המסמך לא אושר. {errors} אנא שלח שוב את {document_type}."
DOCUMENT_APPROVED_HE = "מעולה! {document_type} התקבל ואושר."

# English Templates
GREETING_EN = "Hello {name}, this is Yoni from Megurit. We're happy you decided to join the Megurit family at {property}."

CONFIRM_DETAILS_EN = """Please confirm these details:
• Apartment number: {apartment_number}
• Number of rooms: {number_of_rooms}
• Move-in date: {move_in_date}
• Monthly rent: ₪{monthly_rent_amount}

Are these details correct? Reply 'YES' or 'CONFIRM' if everything is correct, or tell me what needs to be changed."""

PERSONAL_INFO_OCCUPATION_EN = "What is your occupation?"
PERSONAL_INFO_FAMILY_STATUS_EN = "What is your family status? (Single/Married/Divorced/Widowed)"
PERSONAL_INFO_CHILDREN_EN = "How many children do you have?"

DOCUMENT_REQUEST_ID_EN = "Please send your ID card photo (Teudat Zehut)."
DOCUMENT_REQUEST_SEPHACH_EN = "Please send your Sephach form."
DOCUMENT_REQUEST_PAYSLIPS_EN = "Please send your 3 recent pay slips (as PDF or images)."
DOCUMENT_REQUEST_BANK_EN = "Please send your bank statements for the last 3 months."

GUARANTOR_REQUEST_EN = "Please send the name and phone number of guarantor {guarantor_number}."
GUARANTOR_CONFIRMATION_EN = "Thank you! Guarantor {guarantor_number} details received."

COMPLETION_MESSAGE_EN = "Excellent! All information has been received. The process has been completed successfully! Thank you for joining the Megurit family."

ERROR_MESSAGE_EN = "Sorry, an error occurred. Please try again or contact support."
INVALID_DOCUMENT_EN = "The document was not approved. {errors} Please send {document_type} again."
DOCUMENT_APPROVED_EN = "Great! {document_type} has been received and approved."

# Template Functions
def get_greeting_message(name: str, property_name: str, language: str = "he") -> str:
    """Get greeting message in specified language."""
    if language == "en":
        return GREETING_EN.format(name=name, property=property_name)
    return GREETING_HE.format(name=name, property=property_name)

def get_confirmation_message(tenant_data: dict, language: str = "he") -> str:
    """Get confirmation message with tenant details."""
    if language == "en":
        return CONFIRM_DETAILS_EN.format(
            apartment_number=tenant_data.get("apartment_number", ""),
            number_of_rooms=tenant_data.get("number_of_rooms", ""),
            move_in_date=tenant_data.get("move_in_date", ""),
            monthly_rent_amount=tenant_data.get("monthly_rent_amount", 0)
        )
    return CONFIRM_DETAILS_HE.format(
        apartment_number=tenant_data.get("apartment_number", ""),
        number_of_rooms=tenant_data.get("number_of_rooms", ""),
        move_in_date=tenant_data.get("move_in_date", ""),
        monthly_rent_amount=tenant_data.get("monthly_rent_amount", 0)
    )

def get_personal_info_message(field: str, language: str = "he") -> str:
    """Get personal info request message."""
    if language == "en":
        messages = {
            "occupation": PERSONAL_INFO_OCCUPATION_EN,
            "family_status": PERSONAL_INFO_FAMILY_STATUS_EN,
            "number_of_children": PERSONAL_INFO_CHILDREN_EN
        }
    else:
        messages = {
            "occupation": PERSONAL_INFO_OCCUPATION_HE,
            "family_status": PERSONAL_INFO_FAMILY_STATUS_HE,
            "number_of_children": PERSONAL_INFO_CHILDREN_HE
        }
    
    return messages.get(field, "")

def get_document_request_message(document_type: str, language: str = "he") -> str:
    """Get document request message."""
    if language == "en":
        messages = {
            "id_card": DOCUMENT_REQUEST_ID_EN,
            "sephach": DOCUMENT_REQUEST_SEPHACH_EN,
            "payslips": DOCUMENT_REQUEST_PAYSLIPS_EN,
            "bank_statements": DOCUMENT_REQUEST_BANK_EN
        }
    else:
        messages = {
            "id_card": DOCUMENT_REQUEST_ID_HE,
            "sephach": DOCUMENT_REQUEST_SEPHACH_HE,
            "payslips": DOCUMENT_REQUEST_PAYSLIPS_HE,
            "bank_statements": DOCUMENT_REQUEST_BANK_HE
        }
    
    return messages.get(document_type, "")

def get_guarantor_request_message(guarantor_number: int, language: str = "he") -> str:
    """Get guarantor request message."""
    if language == "en":
        return GUARANTOR_REQUEST_EN.format(guarantor_number=guarantor_number)
    return GUARANTOR_REQUEST_HE.format(guarantor_number=guarantor_number)

def get_guarantor_confirmation_message(guarantor_number: int, language: str = "he") -> str:
    """Get guarantor confirmation message."""
    if language == "en":
        return GUARANTOR_CONFIRMATION_EN.format(guarantor_number=guarantor_number)
    return GUARANTOR_CONFIRMATION_HE.format(guarantor_number=guarantor_number)

def get_completion_message(language: str = "he") -> str:
    """Get completion message."""
    if language == "en":
        return COMPLETION_MESSAGE_EN
    return COMPLETION_MESSAGE_HE

def get_error_message(language: str = "he") -> str:
    """Get error message."""
    if language == "en":
        return ERROR_MESSAGE_EN
    return ERROR_MESSAGE_HE

def get_invalid_document_message(errors: str, document_type: str, language: str = "he") -> str:
    """Get invalid document message."""
    if language == "en":
        return INVALID_DOCUMENT_EN.format(errors=errors, document_type=document_type)
    return INVALID_DOCUMENT_HE.format(errors=errors, document_type=document_type)

def get_document_approved_message(document_type: str, language: str = "he") -> str:
    """Get document approved message."""
    if language == "en":
        return DOCUMENT_APPROVED_EN.format(document_type=document_type)
    return DOCUMENT_APPROVED_HE.format(document_type=document_type)

# Button Templates
def get_confirmation_buttons(language: str = "he") -> list:
    """Get confirmation buttons."""
    if language == "en":
        return [
            {"id": "confirm_yes", "title": "Yes, Correct"},
            {"id": "confirm_no", "title": "No, Change"}
        ]
    return [
        {"id": "confirm_yes", "title": "כן, נכון"},
        {"id": "confirm_no", "title": "לא, לשנות"}
    ]

def get_family_status_buttons(language: str = "he") -> list:
    """Get family status buttons."""
    if language == "en":
        return [
            {"id": "family_single", "title": "Single"},
            {"id": "family_married", "title": "Married"},
            {"id": "family_divorced", "title": "Divorced"},
            {"id": "family_widowed", "title": "Widowed"}
        ]
    return [
        {"id": "family_single", "title": "רווק/רווקה"},
        {"id": "family_married", "title": "נשוי/נשואה"},
        {"id": "family_divorced", "title": "גרוש/גרושה"},
        {"id": "family_widowed", "title": "אלמן/אלמנה"}
    ]

def get_children_buttons(language: str = "he") -> list:
    """Get number of children buttons."""
    if language == "en":
        return [
            {"id": "children_0", "title": "0"},
            {"id": "children_1", "title": "1"},
            {"id": "children_2", "title": "2"},
            {"id": "children_3", "title": "3+"}
        ]
    return [
        {"id": "children_0", "title": "0"},
        {"id": "children_1", "title": "1"},
        {"id": "children_2", "title": "2"},
        {"id": "children_3", "title": "3+"}
    ]

# Quick Reply Templates
def get_quick_replies(language: str = "he") -> dict:
    """Get quick reply options."""
    if language == "en":
        return {
            "yes": ["yes", "y", "correct", "confirm", "ok", "okay"],
            "no": ["no", "n", "incorrect", "wrong", "change"],
            "help": ["help", "support", "contact"],
            "start_over": ["start", "restart", "begin"]
        }
    return {
        "yes": ["כן", "נכון", "אישור", "בסדר", "אוקיי"],
        "no": ["לא", "לא נכון", "שגוי", "לשנות"],
        "help": ["עזרה", "תמיכה", "צור קשר"],
        "start_over": ["התחל", "התחל מחדש", "מתחיל"]
    }
