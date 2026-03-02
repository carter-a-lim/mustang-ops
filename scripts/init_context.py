import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts.common import CONTEXT_PATH, utc_now, write_json


def main() -> None:
    data = {
        "updated_at": utc_now(),
        "deadlines": [],
        "events": [],
        "priorities": [
            "Ship one growth experiment",
            "Post one high-quality Mustang Market promo",
            "Clear top school deadline"
        ],
        "experiments": [],
        "outreach_queue": [],
        "kpis": {
            "downloads_7d": 0,
            "new_listings_7d": 0,
            "activation_rate": 0,
            "weekly_outreach_touches": 0
        }
    }
    write_json(CONTEXT_PATH, data)
    print(f"Initialized {CONTEXT_PATH}")


if __name__ == "__main__":
    main()
