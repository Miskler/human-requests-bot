import os
import re
import hashlib
import requests
from datetime import datetime, timezone


def read_log(log_path):
    with open(log_path, "r", encoding="utf8", errors="ignore") as f:
        return f.read()


def extract_stacktrace(log):
    match = re.search(r"Traceback \(most recent call last\):(.+)", log, re.S)
    if match:
        return match.group(0)
    return log[-4000:]


def fingerprint(error):
    normalized = re.sub(r'".*?"', '"X"', error)
    normalized = re.sub(r"\d+", "N", normalized)
    return hashlib.sha1(normalized.encode()).hexdigest()[:12]


def search_issue(hash_id, api, owner, repo_name, headers):
    url = f"{api}/repos/{owner}/{repo_name}/issues?state=all&per_page=100"
    r = requests.get(url, headers=headers)
    r.raise_for_status()
    for issue in r.json():
        body = issue.get("body") or ""
        if f"<!-- human-requests-hash:{hash_id} -->" in body:
            return issue
    return None


def reopen_issue(num, api, owner, repo_name, headers):
    requests.patch(
        f"{api}/repos/{owner}/{repo_name}/issues/{num}",
        headers=headers,
        json={"state": "open"}
    )


def comment_issue(num, text, api, owner, repo_name, headers):
    requests.post(
        f"{api}/repos/{owner}/{repo_name}/issues/{num}/comments",
        headers=headers,
        json={"body": text}
    )


def create_issue(title, body, api, owner, repo_name, headers, labels):
    r = requests.post(
        f"{api}/repos/{owner}/{repo_name}/issues",
        headers=headers,
        json={"title": title, "body": body, "labels": labels}
    )
    r.raise_for_status()
    return r.json()

def main():
    TOKEN = os.getenv("INPUT_GITHUB_TOKEN")
    LOG_PATH = os.getenv("INPUT_LOG_PATH")
    SCREENSHOT = os.getenv("INPUT_SCREENSHOT_PATH")
    LABELS = os.getenv("INPUT_LABELS", "bug,playwright").split(",")

    REPO = os.getenv("GITHUB_REPOSITORY")
    RUN_ID = os.getenv("GITHUB_RUN_ID")
    RUN_URL = f"https://github.com/{REPO}/actions/runs/{RUN_ID}"
    ARTIFACTS_URL = f"https://github.com/{REPO}/actions/runs/{RUN_ID}#artifacts"
    OWNER, REPO_NAME = REPO.split("/")

    API = "https://api.github.com"
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json"
    }

    log = read_log(log_path=LOG_PATH)
    error = extract_stacktrace(log)
    hash_id = fingerprint(error)
    hidden_tag = f"<!-- human-requests-hash:{hash_id} -->"

    title = "HumanRequests test failure"

    body = f"""
{hidden_tag}

### HumanRequests failure

Run: {RUN_URL}

```python
{error}
```
Screenshot is available in the workflow artifacts.
"""
    issue = search_issue(hash_id, api=API, owner=OWNER, repo_name=REPO_NAME, headers=headers)
    timestamp = datetime.now(timezone.utc).isoformat()
    if issue:
        num = issue["number"]
        if issue["state"] == "closed":
            reopen_issue(num, api=API, owner=OWNER, repo_name=REPO_NAME, headers=headers)
        comment = f"""
New incident
Time: {timestamp}
Run: {RUN_URL}
```python
{error}
```
Screenshot is available in the workflow artifacts.
"""
        comment_issue(num, comment, api=API, owner=OWNER, repo_name=REPO_NAME, headers=headers)
        print(f"Updated issue #{num}")
    else:
        issue = create_issue(title, body, api=API, owner=OWNER, repo_name=REPO_NAME, headers=headers, labels=LABELS)
        print(f"Created issue #{issue['number']}")

if __name__ == "__main__":
    main()