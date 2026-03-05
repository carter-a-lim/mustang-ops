import json
import re
from typing import Any, Dict, List, Tuple

def extract_keywords(jd_text: str) -> List[str]:
    """
    Simplistic keyword extraction from JD text.
    In a real app, this might use an LLM or a more complex NLP model.
    """
    # Just split by common separators and clean up
    words = re.findall(r'\b\w+\b', jd_text.lower())
    # Exclude common stop words (very short list for demo)
    stop_words = {'and', 'the', 'for', 'with', 'you', 'will', 'our', 'is', 'in', 'to', 'of'}
    return list(set(w for w in words if w not in stop_words and len(w) > 2))

def score_bullet(bullet: Dict[str, Any], jd_keywords: List[str]) -> float:
    """
    Scores a single bullet based on keyword overlap and metric presence.
    """
    score = 0.0
    text = bullet.get("text", "").lower()
    tags = [t.lower() for t in bullet.get("tags", [])]

    # Overlap with JD keywords
    for kw in jd_keywords:
        if kw in text:
            score += 1.0
        if any(kw in t for t in tags):
            score += 2.0  # Tags are weighted more heavily

    # Presence of a metric is a boost
    if bullet.get("metric"):
        score += 5.0

    return score

def _score_and_attach(bullet: Dict[str, Any], jd_keywords: List[str]) -> Dict[str, Any]:
    b = bullet.copy()
    b["_score"] = score_bullet(b, jd_keywords)
    return b

def generate_resume_variant(
    resume_profile: Dict[str, Any],
    jd_text: str,
    max_bullets_per_entry: int = 3,
    total_bullet_limit: int = 15
) -> Dict[str, Any]:
    """
    Generates a resume variant by selecting the best bullets for each entry.
    """
    jd_keywords = extract_keywords(jd_text)

    variant_experience = []
    variant_projects = []

    all_scored_bullets = [] # To keep track of what was dropped globally if needed

    # Process Experience
    for entry in resume_profile.get("profile", {}).get("experience", []):
        bullet_bank = entry.get("bullet_bank", [])
        scored_bullets = [_score_and_attach(b, jd_keywords) for b in bullet_bank]

        # Sort by score descending
        scored_bullets.sort(key=lambda x: x["_score"], reverse=True)

        chosen = scored_bullets[:max_bullets_per_entry]
        dropped = scored_bullets[max_bullets_per_entry:]

        variant_experience.append({
            **{k: v for k, v in entry.items() if k != 'bullet_bank'},
            "bullets": [b["text"] for b in chosen],
            "chosen_bullets": chosen,
            "dropped_bullets": dropped
        })

    # Process Projects
    for entry in resume_profile.get("profile", {}).get("projects", []):
        bullet_bank = entry.get("bullet_bank", [])
        scored_bullets = [_score_and_attach(b, jd_keywords) for b in bullet_bank]

        scored_bullets.sort(key=lambda x: x["_score"], reverse=True)

        chosen = scored_bullets[:max_bullets_per_entry]
        dropped = scored_bullets[max_bullets_per_entry:]

        variant_projects.append({
            **{k: v for k, v in entry.items() if k != 'bullet_bank'},
            "bullets": [b["text"] for b in chosen],
            "chosen_bullets": chosen,
            "dropped_bullets": dropped
        })

    # Enforce total bullet budget (simplified: just drop lowest scoring chosen bullets across all entries if needed)
    all_chosen = []
    for entry in variant_experience:
        for b in entry["chosen_bullets"]:
            all_chosen.append((b.get("_score", 0), b, entry))
    for entry in variant_projects:
        for b in entry["chosen_bullets"]:
            all_chosen.append((b.get("_score", 0), b, entry))

    if len(all_chosen) > total_bullet_limit:
        all_chosen.sort(key=lambda x: x[0], reverse=True)
        to_keep = all_chosen[:total_bullet_limit]
        to_drop = all_chosen[total_bullet_limit:]

        # Re-build bullets for each entry
        for entry in variant_experience + variant_projects:
            entry["bullets"] = []
            entry["chosen_bullets"] = []

        for score, b, entry in to_keep:
            entry["bullets"].append(b["text"])
            entry["chosen_bullets"].append(b)

        for score, b, entry in to_drop:
            entry["dropped_bullets"].append(b)

    final_variant = {
        "profile_summary": resume_profile.get("profile", {}),
        "experience": variant_experience,
        "projects": variant_projects,
        "jd_keywords_detected": jd_keywords[:20] # Return some for review
    }

    return final_variant

if __name__ == "__main__":
    # Simple CLI test
    import sys
    if len(sys.argv) > 1:
        with open("data/resume_profile.json", "r") as f:
            profile = json.load(f)
        jd = sys.argv[1]
        print(json.dumps(generate_resume_variant(profile, jd), indent=2))
