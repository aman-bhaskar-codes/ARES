import argparse
import hashlib
import logging
from pathlib import Path

from fastembed import TextEmbedding

from ares.application.repository import Repository
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def hash_directory(dir_path: Path) -> str:
    """Compute a deterministic hash of the files in a directory."""
    hasher = hashlib.sha256()
    for file_path in sorted(dir_path.rglob("*")):
        if file_path.is_file():
            hasher.update(file_path.name.encode("utf-8"))
            with open(file_path, "rb") as f:
                while chunk := f.read(8192):
                    hasher.update(chunk)
    return hasher.hexdigest()

def provision_embedding_model(model_name: str, cache_dir: str):
    logger.info(f"Provisioning {model_name} in {cache_dir}")
    # Run with local_files_only=False to allow download
    client = TextEmbedding(model_name=model_name, cache_dir=cache_dir, local_files_only=False)
    
    # FastEmbed usually stores under models/fastembed/fast-xxxxx
    # We find the downloaded directory by looking at where it put it
    model_dir = Path(cache_dir) / f"fast-{model_name.replace('/', '-')}"
    if not model_dir.exists():
        # Maybe different naming convention
        model_dir_list = list(Path(cache_dir).glob(f"*{model_name.split('/')[-1]}*"))
        if model_dir_list:
            model_dir = model_dir_list[0]
        else:
            raise FileNotFoundError("Could not locate downloaded model directory.")
            
    digest = hash_directory(model_dir)
    logger.info(f"Computed digest: {digest}")
    
    # Store in DB
    import os
    engine = create_engine(os.getenv("DATABASE_URL", "sqlite+pysqlite:///./.data/ares-dev.sqlite3"))
    repo = Repository(sessionmaker(bind=engine))
    
    profile_key = f"local-{model_name.replace('/', '-')}-{digest[:8]}"
    
    profile_id = repo.create_retrieval_profile(
        profile_key=profile_key,
        provider="local_fastembed",
        model_id=model_name,
        artifact_digest=digest,
        tokenizer_version="v1",
        dimensions=384, # Ideally determined from client.dimension but hardcoded for BAAI for now
        distance_metric="cosine",
        language_coverage="en",
        chunk_policy="v1",
        extraction_revision="v1"
    )
    logger.info(f"Created retrieval profile {profile_key} with ID {profile_id}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="BAAI/bge-small-en-v1.5")
    parser.add_argument("--cache-dir", default=".data/models/fastembed")
    args = parser.parse_args()
    provision_embedding_model(args.model, args.cache_dir)
