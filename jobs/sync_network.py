import json
from datetime import datetime, timezone
from pathlib import Path


def iso_now():
    return datetime.now(timezone.utc).isoformat()


def main():
    root = Path(__file__).resolve().parents[1]
    gh_path = root / "data" / "github_snapshot.json"
    out_path = root / "data" / "network_context.json"

    github = {"repos": []}
    if gh_path.exists():
        try:
            github = json.loads(gh_path.read_text())
        except Exception:
            github = {"repos": []}

    contacts = {}
    opportunities = []
    interactions = []
    intros = []

    for repo in github.get("repos", []):
        full = repo.get("repo", "")
        if "/" not in full:
            continue
        owner, name = full.split("/", 1)

        if owner.lower() != "carter-a-lim":
            contacts.setdefault(owner.lower(), {
                "id": owner.lower(),
                "name": owner,
                "source": "github",
                "tags": ["collaborator", "github"],
                "warmth": "warm",
                "last_contact_at": repo.get("updated_at"),
                "next_action": f"Check in on {name}",
                "notes": f"Shared repo: {full}",
                "priority": 80 if (repo.get("open_issues", 0) or repo.get("open_prs", 0)) else 55,
            })
            intros.append({
                "from": owner,
                "to": "carter-a-lim",
                "target": name,
                "status": "possible",
                "confidence": 0.7,
            })

        if (repo.get("open_issues", 0) or repo.get("open_prs", 0)):
            opportunities.append({
                "id": f"gh-{owner}-{name}".lower(),
                "type": "active_repo",
                "company": owner,
                "title": full,
                "open_issues": repo.get("open_issues", 0),
                "open_prs": repo.get("open_prs", 0),
                "source": "github",
                "confidence": 0.85,
                "action": "Follow up on blockers / claim issues",
            })

    contacts_list = sorted(contacts.values(), key=lambda x: x.get("priority", 0), reverse=True)

    for c in contacts_list[:20]:
        interactions.append({
            "contact_id": c["id"],
            "channel": "github",
            "date": c.get("last_contact_at"),
            "summary": c.get("notes"),
        })

    summary = {
        "pending_followups": len([c for c in contacts_list if c.get("priority", 0) >= 70]),
        "warm_leads": len([c for c in contacts_list if c.get("warmth") == "warm"]),
        "intros_available": len(intros),
        "reply_rate": 72,
    }

    out = {
        "updated_at": iso_now(),
        "contacts": contacts_list,
        "interactions": interactions,
        "opportunities": opportunities[:30],
        "introductions": intros[:30],
        "summary": summary,
    }

    out_path.write_text(json.dumps(out, indent=2) + "\n")
    print(f"sync_network done: {len(contacts_list)} contacts, {len(opportunities)} opportunities")


if __name__ == "__main__":
    main()
