<div align="center">
  <img src="https://raw.githubusercontent.com/amanbhaskar/ARES/main/ares_banner.jpg" alt="ARES Banner" width="100%" style="border-radius: 12px; margin-bottom: 20px;" />

  # ✦ ARES ✦
  **Autonomous AI Research and Engineering System**

  <p align="center">
    A world-class, multi-agent platform for deep research, hybrid retrieval-augmented generation (RAG), and intelligent multi-modal content extraction.
  </p>

  <p align="center">
    <img src="https://img.shields.io/badge/Python-3.12+-blue.svg?style=for-the-badge&logo=python&logoColor=white" alt="Python" />
    <img src="https://img.shields.io/badge/TypeScript-Ready-blue.svg?style=for-the-badge&logo=typescript&logoColor=white" alt="TypeScript" />
    <img src="https://img.shields.io/badge/Next.js-14-black.svg?style=for-the-badge&logo=next.js&logoColor=white" alt="Next.js" />
    <img src="https://img.shields.io/badge/FastAPI-Modern-009688.svg?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI" />
    <img src="https://img.shields.io/badge/Qdrant-Vector_DB-FF5252.svg?style=for-the-badge&logo=qdrant&logoColor=white" alt="Qdrant" />
  </p>
</div>

<br />

## 🚀 Vision & Capabilities

ARES is engineered from the ground up to be the ultimate **AI-driven research companion**. By blending deterministic data extraction pipelines with state-of-the-art Generative AI, ARES executes complex, multi-wave research processes completely autonomously. 

Whether you are performing deep literature reviews, generating bounded financial summaries, or creating polished Markdown/PDF reports, ARES handles the entire lifecycle securely and deterministically.

### 🌟 Key Features
- **🧠 Autonomous Research Engine**: Spawns concurrent AI workers to conduct deep, iterative web and document searches.
- **⚡ Hybrid RAG Pipeline**: Merges dense semantic vector similarity (via **Qdrant**) with precise lexical token matching for unparalleled retrieval accuracy.
- **🖥️ Cinematic Web Interface**: A stunning, ultra-responsive **Next.js & React** interface, styled with **Tailwind CSS** and **Framer Motion** for a fluid, real-time streaming experience.
- **🛡️ Secure & Sandboxed Execution**: Data bounded strictly to authorized workspaces, backed by **PostgreSQL** or **SQLite**.
- **🌐 Omni-Model Architecture**: Seamlessly plug-and-play with cloud giants (OpenAI, Anthropic, Gemini) or run 100% locally with offline models via **Ollama**.

---

## 🏗️ Technology Stack

ARES is built utilizing a hardened, production-grade enterprise stack divided into distinct, scalable domains:

### 🐍 The Backend Control Plane
The nervous system of ARES, providing real-time data streaming and asynchronous job execution.
* **Core**: Python 3.12+, asynchronous event loops.
* **API Framework**: **FastAPI** with robust Pydantic schemas.
* **Database & ORM**: **SQLAlchemy** (async), **Alembic** for migrations, **PostgreSQL** (production) / **SQLite** (local).
* **Vector Store**: **Qdrant** for high-dimensional semantic search.
* **Tooling**: **uv** (lightning-fast Python package manager), **Playwright** (headless Chromium for PDF generation).

### ⚛️ The Frontend Interface
A beautiful, highly interactive SPA built for raw speed and aesthetics.
* **Core**: TypeScript, React 18+.
* **Framework**: **Next.js** (App Router).
* **Styling & Animation**: **Tailwind CSS**, **Framer Motion**.
* **State Management**: React Query / Context API.
* **Tooling**: **pnpm** (fast, disk-space efficient package manager).

---

## 🛠️ Quick Start & Installation

You can get ARES up and running on any machine (Mac, Windows, Linux) in minutes.

### 1. Prerequisites
Ensure you have the following installed on your system:
* **[uv](https://docs.astral.sh/uv/)** - An extremely fast Python package and project manager.
* **Node.js (v20+)** & **[pnpm](https://pnpm.io/)** - For the frontend.
* *(Optional)* **Ollama** - If you intend to run AI models entirely locally on your hardware.

### 2. Clone the Repository
```bash
git clone https://github.com/your-username/ARES.git
cd ARES
```

### 3. Backend Setup
We use `uv` to guarantee fast, deterministic Python environments.
```bash
# Move to the backend directory
cd backend

# Install dependencies instantly via uv
uv sync

# Setup your environment variables
cp ../.env.example ../.env
# -> Edit ../.env with your specific API keys if not using local models

# Install Playwright browser binaries (Required for PDF export capabilities)
uv run playwright install chromium
```

### 4. Frontend Setup
```bash
# Return to the root directory
cd ..

# Install all node packages via pnpm
pnpm install
```

---

## 🚦 Running ARES

To run the full suite locally, you will need to open **two separate terminal windows**.

### Terminal 1: Backend Services (API & Worker)
Start the primary FastAPI server and the background job worker.
```bash
# 1. Start the API Server (runs on port 8000)
uv run --project backend uvicorn ares.api.app:app --app-dir backend/src --reload

# 2. In a NEW tab, start the Background Job Worker
PYTHONPATH=backend/src uv run --project backend python -m ares.worker.main
```

### Terminal 2: Web Frontend
Start the stunning Next.js interface.
```bash
# Start the web UI (runs on port 3000)
pnpm --filter @ares/web dev
```

🎯 **That's it!** Open your browser and navigate to **[http://localhost:3000](http://localhost:3000)** to experience ARES.

---

## 🔋 Running 100% Locally (Offline AI)

ARES is fully compatible with local, offline LLMs via **Ollama** for maximum privacy and zero API costs.

1. Install and start [Ollama](https://ollama.com/).
2. Pull your preferred model (e.g., `qwen2.5:3b` or `llama3`):
   ```bash
   ollama pull qwen2.5:3b
   ```
3. Update your `.env` file at the root of the project:
   ```env
   LOCAL_LLM_ENABLED=true
   LOCAL_LLM_URL=http://127.0.0.1:11434
   LOCAL_LLM_MODEL=qwen2.5:3b
   ```
4. Restart your backend services. ARES will now route all autonomous research through your local GPU/CPU!

---
<div align="center">
  <i>Engineered for the future of Autonomous Intelligence.</i>
</div>
