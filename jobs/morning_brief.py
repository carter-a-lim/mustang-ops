import json
import os
from pathlib import Path

context_path = Path(os.getenv("MUSTANG_CONTEXT_PATH", "/home/ubuntu/mustang-ops/data/mustang_context.json"))
fallback = Path(__file__).resolve().parents[1] / "data" / "mustang_context.json"
if not context_path.exists() and fallback.exists():
    context_path = fallback

ctx = json.loads(context_path.read_text()) if context_path.exists() else {}
print("Morning Brief")
for p in ctx.get("priorities", [])[:3]:
    print("-", p)
print("Deadlines:", len(ctx.get("deadlines", [])))
