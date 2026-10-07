# ARES: AI Research and Engineering System

ARES is an autonomous, scalable, and highly capable AI research and engineering system. It provides a full-stack platform for running deep research tasks, retrieving multi-modal evidence, extracting semantic content, and producing high-quality generated reports. 

## Capabilities

- **Autonomous Research Engine:** Operates deep, multi-wave research cycles to answer complex queries.
- **Hybrid Retrieval-Augmented Generation (RAG):** Combines lexical search and semantic vector similarity (using Qdrant) for highly accurate context retrieval.
- **Multi-Modal Support:** Capable of processing documents, web content, PDFs, and structuring data into rich formats.
- **Interactive Web Interface:** A highly polished Next.js/React frontend with real-time streaming updates, fluid animations, and a rich, responsive user experience.
- **Local & Cloud LLM Support:** Works seamlessly with cloud providers (OpenAI, Anthropic, Gemini) and local models via Ollama.
- **Export & Portability:** Generates polished, formatted PDF and Markdown exports of research sessions.

## Tech Stack

### Backend
- **Python 3.12+**
- **FastAPI:** High-performance async API server.
- **SQLAlchemy & Alembic:** Robust ORM and database migrations.
- **PostgreSQL / SQLite:** Persistent state storage (SQLite for local dev, PostgreSQL for production).
- **Qdrant:** Vector database for semantic search and embeddings.
- **Playwright:** Headless browser automation for PDF exports.

### Frontend
- **TypeScript & React 18+**
- **Next.js:** Server-side rendering and API routes.
- **Tailwind CSS & Framer Motion:** Fluid, modern, and responsive UI components.
- **PNPM:** Fast, disk-space efficient package manager.

## Getting Started

### Prerequisites

Ensure you have the following installed on your machine (Mac, Windows, or Linux):
1. **Python 3.12+** (We recommend using [uv](https://github.com/astral-sh/uv) for fast Python package management)
2. **Node.js 20+** & **pnpm** (For the frontend)
3. **Ollama** (Optional, if you want to run models locally)

### Installation & Setup

**1. Clone the repository**
```bash
git clone <your-repo-url>
cd ares
```

**2. Backend Setup**
```bash
# Navigate to the backend directory
cd backend

# Install dependencies using uv
uv sync

# Set up environment variables
cp ../.env.example ../.env

# Install Playwright dependencies (required for PDF exports)
uv run playwright install chromium
```

**3. Frontend Setup**
```bash
# Navigate back to the root directory
cd ..

# Install frontend dependencies
pnpm install
```

### Running the Application

You need to start two processes (in separate terminal windows) to run ARES locally.

**Terminal 1: Start the Backend API & Background Worker**
```bash
# Start the FastAPI server
uv run --project backend uvicorn ares.api.app:app --app-dir backend/src --reload

# In another tab, start the background worker (processes research jobs)
PYTHONPATH=backend/src uv run --project backend python -m ares.worker.main
```

**Terminal 2: Start the Web Frontend**
```bash
# Start the Next.js frontend
pnpm --filter @ares/web dev
```

Once both are running, open your browser and navigate to `http://localhost:3000`.

### Using Local Models (Optional)
To run ARES completely locally without relying on external APIs, you can use Ollama:
1. Ensure Ollama is running (`ollama serve`).
2. Download your preferred model (e.g., `ollama pull qwen2.5:3b`).
3. Set `LOCAL_LLM_ENABLED=true` and `LOCAL_LLM_MODEL=qwen2.5:3b` in your `.env` file.

