import json
import os
from datetime import datetime, timezone
from pathlib import Path

context_path = Path(os.getenv("MUSTANG_CONTEXT_PATH", "/home/ubuntu/mustang-ops/data/mustang_context.json"))
fallback = Path(__file__).resolve().parents[1] / "data" / "mustang_context.json"
if not context_path.exists() and fallback.exists():
    context_path = fallback

ctx = json.loads(context_path.read_text()) if context_path.exists() else {}
queue = ctx.setdefault("outreach_queue", [])
queue.append({
  "name": "Sample Prospect",
  "segment": "SLO local business owner",
  "status": "queued",
  "added_at": datetime.now(timezone.utc).isoformat()
})
ctx["updated_at"] = datetime.now(timezone.utc).isoformat()
context_path.parent.mkdir(parents=True, exist_ok=True)
context_path.write_text(json.dumps(ctx, indent=2) + "\n")
print("linkedin_scout done")
