import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPENAPI = ROOT / "backend" / "openapi.json"
WEB_DIR = ROOT / "apps" / "web"
OUTPUT = WEB_DIR / "src" / "lib" / "api" / "generated.ts"

def main() -> None:
    if not OPENAPI.exists():
        raise SystemExit(f"OpenAPI spec not found at {OPENAPI}")
    
    # Delegate to openapi-typescript
    print(f"Generating types using openapi-typescript from {OPENAPI} -> {OUTPUT}")
    result = subprocess.run(
        ["npx", "openapi-typescript", str(OPENAPI), "-o", str(OUTPUT)],
        cwd=str(WEB_DIR),
        capture_output=True,
        text=True,
    )
    
    if result.returncode != 0:
        print(result.stdout, file=sys.stdout)
        print(result.stderr, file=sys.stderr)
        raise SystemExit(f"openapi-typescript failed with code {result.returncode}")
        
    print(OUTPUT.relative_to(ROOT))

if __name__ == "__main__":
    main()
