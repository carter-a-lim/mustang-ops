import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen


def iso_now():
    return datetime.now(timezone.utc).isoformat()


def read_cfg_token_and_owner():
    cfg = Path.home() / '.openclaw' / 'openclaw.json'
    if not cfg.exists():
        return None, None
    try:
        data = json.loads(cfg.read_text())
        token = data.get('skills', {}).get('entries', {}).get('github', {}).get('env', {}).get('GITHUB_TOKEN')
    except Exception:
        token = None
    return token, 'carter-a-lim'


def gh_get(url, token):
    req = Request(url, headers={
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'mustang-ops'
    })
    with urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode('utf-8'))


def main():
    root = Path(__file__).resolve().parents[1]
    out_path = root / 'data' / 'github_snapshot.json'

    token = os.getenv('GITHUB_TOKEN')
    owner = os.getenv('GITHUB_OWNER', 'carter-a-lim')
    if not token:
        t2, o2 = read_cfg_token_and_owner()
        token = token or t2
        owner = owner or o2

    if not token:
        out = {'updated_at': iso_now(), 'error': 'Missing GITHUB_TOKEN', 'repos': []}
        out_path.write_text(json.dumps(out, indent=2) + '\n')
        print('sync_github: missing token')
        return

    repos = gh_get(f'https://api.github.com/users/{owner}/repos?sort=updated&per_page=12', token)

    snapshots = []
    for r in repos[:8]:
        full = r.get('full_name')
        if not full:
            continue
        prs = gh_get(f'https://api.github.com/repos/{full}/pulls?state=open&per_page=20', token)
        issues = gh_get(f'https://api.github.com/repos/{full}/issues?state=open&per_page=30', token)
        issue_count = len([i for i in issues if 'pull_request' not in i])
        snapshots.append({
            'repo': full,
            'open_prs': len(prs),
            'open_issues': issue_count,
            'updated_at': r.get('updated_at'),
            'html_url': r.get('html_url')
        })

    out = {
        'updated_at': iso_now(),
        'owner': owner,
        'repos': snapshots
    }
    out_path.write_text(json.dumps(out, indent=2) + '\n')
    print(f'sync_github done: {len(snapshots)} repos')


if __name__ == '__main__':
    main()
