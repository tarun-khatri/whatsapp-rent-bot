#!/usr/bin/env python3
"""
Simple test script to verify the app starts correctly.
"""

import sys
import os

def test_imports():
    """Test if all modules can be imported."""
    try:
        print("Testing imports...")
        
        # Test basic imports
        from app import create_app
        print("✅ App module imported successfully")
        
        # Test service imports
        from app.services.supabase_service import supabase_service
        print("✅ Supabase service imported successfully")
        
        from app.services.whatsapp_service import whatsapp_service
        print("✅ WhatsApp service imported successfully")
        
        from app.services.vertex_ai_service import vertex_ai_service
        print("✅ Vertex AI service imported successfully")
        
        from app.services.document_ai_service import document_ai_service
        print("✅ Document AI service imported successfully")
        
        from app.services.conversation_flow_service import conversation_flow_service
        print("✅ Conversation flow service imported successfully")
        
        # Test model imports
        from app.models.tenant import Tenant, ConversationState, DocumentType
        print("✅ Models imported successfully")
        
        # Test utility imports
        from app.utils.phone_utils import normalize_phone_number
        from app.utils.validation_utils import validate_phone_number
        from app.utils.file_utils import get_file_extension
        print("✅ Utilities imported successfully")
        
        return True
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

def test_app_creation():
    """Test if the Flask app can be created."""
    try:
        print("\nTesting app creation...")
        
        # Set minimal environment variables for testing
        os.environ.setdefault('ACCESS_TOKEN', 'test_token')
        os.environ.setdefault('PHONE_NUMBER_ID', 'test_phone_id')
        os.environ.setdefault('VERIFY_TOKEN', 'test_verify_token')
        os.environ.setdefault('SUPABASE_URL', 'https://test.supabase.co')
        os.environ.setdefault('SUPABASE_PUBLISHABLE_KEY', 'test_key')
        os.environ.setdefault('VERTEX_AI_PROJECT', 'test_project')
        
        from app import create_app
        app = create_app()
        
        print("✅ Flask app created successfully")
        print(f"✅ App has {len(app.blueprints)} blueprints registered")
        
        # Test if routes are registered
        with app.app_context():
            rules = [rule.rule for rule in app.url_map.iter_rules()]
            print(f"✅ App has {len(rules)} routes registered")
            print(f"✅ Routes: {rules}")
            
            # Test service imports (they should not initialize yet)
            from app.services.supabase_service import supabase_service
            from app.services.whatsapp_service import whatsapp_service
            from app.services.vertex_ai_service import vertex_ai_service
            from app.services.document_ai_service import document_ai_service
            from app.services.conversation_flow_service import conversation_flow_service
            
            print("✅ All services imported successfully (lazy initialization)")
        
        return True
        
    except Exception as e:
        print(f"❌ App creation error: {e}")
        return False

def main():
    """Run all tests."""
    print("🚀 Testing WhatsApp Bot Application")
    print("=" * 50)
    
    # Test imports
    imports_ok = test_imports()
    
    # Test app creation
    app_ok = test_app_creation()
    
    print("\n" + "=" * 50)
    if imports_ok and app_ok:
        print("🎉 All tests passed! The app should run correctly.")
        print("\nTo start the app, run:")
        print("python run.py")
        return 0
    else:
        print("❌ Some tests failed. Please check the errors above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
