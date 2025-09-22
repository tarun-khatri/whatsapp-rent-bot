# WhatsApp Document Collection Bot for Megurit

A production-level WhatsApp bot for collecting tenant documents and information for Megurit, an Israeli rental company.

## Features

- Complete conversation flow for tenant onboarding
- Document processing with Google Document AI
- Multi-language support (Hebrew/English)
- Intelligent validation with Vertex AI
- Supabase database integration
- Comprehensive error handling
- Production-ready monitoring

## Quick Start

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Configure environment:
```bash
cp example.env .env
# Edit .env with your configuration
```

3. Run the application:
```bash
python run.py
```

## Configuration

See `example.env` for all required environment variables including:
- WhatsApp Business API credentials
- Supabase configuration
- Google Cloud services
- Document AI processors

## API Endpoints

- `GET /webhook` - Webhook verification
- `POST /webhook` - Message processing
- `GET /health` - Health check
- `GET /status` - Service status

## Conversation Flow

1. Greeting & tenant identification
2. Property details confirmation
3. Personal information collection
4. Document uploads (ID, payslips, bank statements)
5. Guarantor information
6. Process completion

## Documentation

For detailed documentation, see the inline code comments and service implementations.