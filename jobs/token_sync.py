import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts.common import CONTEXT_PATH, log_job, read_json, utc_now, write_json


def main() -> None:
    started = utc_now()
    job = "token_sync"
    try:
        context = read_json(CONTEXT_PATH, default={})
        kpis = context.setdefault("kpis", {})
        # TODO: Pull real token usage from your provider/status endpoint.
        kpis["token_gauge_last_sync"] = utc_now()
        context["updated_at"] = utc_now()
        write_json(CONTEXT_PATH, context)
        log_job(job, started_at=started, status="ok", output_path=str(CONTEXT_PATH))
        print("Token gauge synced")
    except Exception as e:
        log_job(job, started_at=started, status="error", error=str(e))
        raise


if __name__ == "__main__":
    main()
