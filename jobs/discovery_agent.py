#!/usr/bin/env python3
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add root to sys.path to import llm
ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

import llm

DISCOVERED_PATH = ROOT / "data" / "discovered_sources.json"


def main():
    print("Starting discovery agent...")

    prompt = """
    Identify 10 high-quality, active job boards, GitHub repositories, or community aggregators specifically for 2025 and 2026 software engineering internships.

    Exclude:
    - Simplify (already used)
    - General boards like LinkedIn, Indeed, Glassdoor (too broad)

    Focus on:
    - Curated GitHub 'Summer 2025' lists.
    - Niche tech internship boards (e.g., levels.fyi, Otta, etc.)
    - University-specific or regional tech talent aggregators.

    For each source, provide:
    1. Name
    2. URL
    3. Description
    4. Quality Score (0-100) based on signal-to-noise ratio and update frequency.
    5. Frequency of updates (e.g., daily, weekly).
    6. Signal Level (e.g., high, medium, low).
    7. Why it's valuable.

    Format the output as a JSON list of objects with these keys: name, url, description, quality_score, update_frequency, signal_level, value_prop.
    """

    try:
        response = llm.call_openclaw([{"role": "user", "content": prompt}])
        # Try to extract JSON from response
        # LLMs sometimes wrap in ```json ... ```
        json_pattern = re.compile(r"\[.*\]", re.DOTALL)
        match = json_pattern.search(response)
        if match:
            response = match.group(0)

        sources = json.loads(response)

        # Scoring logic (simple heuristic + AI score)
        for s in sources:
            ai_score = int(s.get("quality_score", 50))

            # Heuristics
            url = s.get("url", "").lower()
            if "github.com" in url:
                ai_score += 15
            if "levels.fyi" in url or "otta.com" in url:
                ai_score += 10
            if "intern" in url or "junior" in url:
                ai_score += 5

            if s.get("signal_level", "").lower() == "high":
                ai_score += 10

            s["final_score"] = max(0, min(100, ai_score))
            s["status"] = "discovered"
            s["discovered_at"] = datetime.now(timezone.utc).isoformat()

        # Sort by score
        sources.sort(key=lambda x: x.get("final_score", 0), reverse=True)

        output = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "sources": sources
        }

        with open(DISCOVERED_PATH, "w") as f:
            json.dump(output, f, indent=2)
            f.write("\n")

        print(f"Discovery complete. Found {len(sources)} sources. Saved to {DISCOVERED_PATH}")

    except Exception as e:
        print(f"Error during discovery: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
