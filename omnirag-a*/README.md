# Omnirag A*: Advanced Multi-Model RAG/Agentic AI Application

A sophisticated multi-agent RAG system that integrates multiple AI models (local-first with Ollama/vLLM and cloud APIs) to create a unified, intelligent agentic application.

## Features

- **Local-First Architecture**: Default to local models (Ollama, vLLM)
- **Multi-Agent System**: Specialized agents (Reasoning, RAG, Search) working in harmony
- **Model Agnostic**: Support for Ollama, OpenAI, Claude, and more
- **Streaming Support**: Real-time text streaming with reasoning traces
- **RAG Capabilities**: Vector-based retrieval and augmentation
- **Clean UI**: Modern frontend with collapsible reasoning traces and sources

## 📁 Project Structure

```
omnirag-a-star/
├── 📁 app/                    # Backend (FastAPI)
│   ├── agents/            # Agent implementations
│   ├── api/v1/           # API endpoints
│   ├── core/              # Core utilities
│   ├── db/                # Database configuration
│   ├── models/            # SQLAlchemy models
│   └── services/          # Business logic
├── frontend/              # Frontend (Next.js)
│   ├── src/
│   │   ├── app/          # Next.js app router
│   │   ├── components/   # React components
│   │   ├── lib/          # API client
│   │   └── store/        # State management
└── tests/                 # Test files
```

## 🛠️ Quick Start

### Backend Setup

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install fastapi uvicorn pydantic pydantic-settings httpx structlog sqlalchemy alembic chromadb sentence-transformers ollama

# Run migrations
alembic upgrade head

# Start backend
uvicorn app.main:app --reload
```

Backend will be available at `http://localhost:5000`

### Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Start development server
npm run dev
```

Frontend will be available at `http://localhost:3000`

## 📚 Documentation

Comprehensive documentation is available in the `docs/` folder:

- **00_master_plan.md**: System architecture and design
- **01_data_schema.md**: Data models and schemas
- **02_tech_stack.md**: Technology choices
- **03_frontend_spec.md**: Frontend specifications
- **04_backend_spec.md**: Backend specifications
- **05_guardrails.md**: Safety and security
- **06_task_progress.md**: Development progress

## Current Status

### ✅ Completed
- Backend API with 20+ endpoints
- 3 specialized agents (Reasoning, RAG, Search)
- Model abstraction layer (Ollama, OpenAI, Anthropic)
- Vector database integration (ChromaDB)
- Frontend MVP with streaming chat
- Error handling and validation
- Monitoring and metrics
- Caching layer

### 🚧 In Progress
- Comprehensive testing suite
- Docker deployment setup
- Redis integration

### 📋 Planned
- Additional agents (Code, Analysis, Planning)
- Authentication system
- Performance optimization
- Production deployment

## 🔌 API Endpoints

- `GET /health` - Health check
- `GET /api/v1/models` - List available models
- `POST /api/v1/chat/completion` - Non-streaming chat
- `POST /api/v1/chat/stream` - Streaming chat (SSE)
- `GET /api/v1/agents` - List agents
- `GET /api/v1/documents` - Document management
- `GET /api/v1/sessions` - Session management
- `GET /api/v1/metrics` - System metrics

## 🧪 Testing

```bash
# Run backend tests
pytest tests/

# Run frontend build
cd frontend && npm run build
```

