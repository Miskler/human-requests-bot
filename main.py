import os
import re
import hashlib
import requests
from datetime import datetime
from jinja2 import Template

TOKEN = os.getenv("INPUT_GITHUB_TOKEN")
LOG_PATH = os.getenv("INPUT_LOG_PATH")
SCREENSHOT = os.getenv("INPUT_SCREENSHOT_PATH")
LABELS = os.getenv("INPUT_LABELS", "bug,playwright").split(",")

REPO = os.getenv("GITHUB_REPOSITORY")
RUN_URL = f"https://github.com/{REPO}/actions/runs/{os.getenv('GITHUB_RUN_ID')}"
OWNER, REPO_NAME = REPO.split("/")

API = "https://api.github.com"
headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json"
}


def read_log():
    with open(LOG_PATH, "r", encoding="utf8", errors="ignore") as f:
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


def search_issue(hash_id):
    url = f"{API}/repos/{OWNER}/{REPO_NAME}/issues?state=all&per_page=100"
    r = requests.get(url, headers=headers)
    r.raise_for_status()
    for issue in r.json():
        body = issue.get("body") or ""
        if f"<!-- human-requests-hash:{hash_id} -->" in body:
            return issue
    return None


def reopen_issue(num):
    requests.patch(f"{API}/repos/{OWNER}/{REPO_NAME}/issues/{num}", headers=headers, json={"state": "open"})


def comment_issue(num, text):
    requests.post(f"{API}/repos/{OWNER}/{REPO_NAME}/issues/{num}/comments", headers=headers, json={"body": text})


def create_issue(title, body):
    r = requests.post(f"{API}/repos/{OWNER}/{REPO_NAME}/issues", headers=headers,
                      json={"title": title, "body": body, "labels": LABELS})
    r.raise_for_status()
    return r.json()


def write_summary(screenshot_path):
    summary_file = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_file and os.path.exists(screenshot_path):
        with open(summary_file, "a") as f:
            f.write(f"### Screenshot\n![screenshot]({screenshot_path})\n")


# Шаблон Jinja2 для issue и комментариев
ISSUE_TEMPLATE = """
{{ hidden_tag }}

### HumanRequests failure

Run: {{ run_url }}

```python
{{ error }}
```

{% if screenshot_url %}
![screenshot]({{ screenshot_url }})
{% endif %}
"""

COMMENT_TEMPLATE = """

New incident

time: {{ timestamp }}

Run: {{ run_url }}

```python
{{ error }}
```
"""

def main():
    log = read_log()
    error = extract_stacktrace(log)
    hash_id = fingerprint(error)
    hidden_tag = f"<!-- human-requests-hash:{hash_id} -->"

    # Для скриншота можно вставить относительный путь, summary покажет картинку
    screenshot_url = SCREENSHOT if SCREENSHOT and os.path.exists(SCREENSHOT) else None

    title = "HumanRequests test failure"
    body = Template(ISSUE_TEMPLATE).render(hidden_tag=hidden_tag, run_url=RUN_URL,
                                        error=error, screenshot_url=screenshot_url)

    issue = search_issue(hash_id)
    timestamp = datetime.utcnow().isoformat()

    if issue:
        num = issue["number"]
        if issue["state"] == "closed":
            reopen_issue(num)

        comment = Template(COMMENT_TEMPLATE).render(timestamp=timestamp, run_url=RUN_URL, error=error)
        comment_issue(num, comment)
        print(f"Updated issue #{num}")
    else:
        issue = create_issue(title, body)
        print(f"Created issue #{issue['number']}")

    # Summary для GitHub Actions
    if screenshot_url:
        write_summary(screenshot_url)

if __name__ == "__main__":
    main()