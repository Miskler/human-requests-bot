import os
import re
import hashlib
import requests
from datetime import datetime

TOKEN = os.getenv("INPUT_GITHUB_TOKEN")
LOG_PATH = os.getenv("INPUT_LOG_PATH")
SCREENSHOT = os.getenv("INPUT_SCREENSHOT_PATH")
LABELS = os.getenv("INPUT_LABELS", "bug,playwright").split(",")

REPO = os.getenv("GITHUB_REPOSITORY")
RUN_URL = f"https://github.com/{REPO}/actions/runs/{os.getenv('GITHUB_RUN_ID')}"

OWNER, REPO_NAME = REPO.split("/")

API = "https://api.github.com"
UPLOAD = f"https://uploads.github.com/repos/{OWNER}/{REPO_NAME}/issues/attachments"

headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json"
}


def read_log():
    with open(LOG_PATH, "r", encoding="utf8", errors="ignore") as f:
        return f.read()


def extract_stacktrace(log):
    """
    Выделяет python traceback.
    """
    match = re.search(r"Traceback \(most recent call last\):(.+)", log, re.S)
    if match:
        return match.group(0)

    return log[-4000:]


def fingerprint(error):
    """
    Создаёт стабильный hash ошибки
    """
    normalized = re.sub(r'".*?"', '"X"', error)
    normalized = re.sub(r"\d+", "N", normalized)

    return hashlib.sha1(normalized.encode()).hexdigest()[:12]


def upload_attachment(path):
    if not path or not os.path.exists(path):
        return None

    with open(path, "rb") as f:
        r = requests.post(
            UPLOAD,
            headers=headers,
            files={"file": f}
        )

    r.raise_for_status()
    return r.json()["url"]


def search_issue(hash_id):
    url = f"{API}/repos/{OWNER}/{REPO_NAME}/issues?state=all"

    r = requests.get(url, headers=headers)
    r.raise_for_status()

    for issue in r.json():
        body = issue.get("body") or ""
        if f"<!-- human-requests-hash:{hash_id} -->" in body:
            return issue

    return None


def reopen_issue(num):
    requests.patch(
        f"{API}/repos/{OWNER}/{REPO_NAME}/issues/{num}",
        headers=headers,
        json={"state": "open"}
    )


def comment_issue(num, text):
    requests.post(
        f"{API}/repos/{OWNER}/{REPO_NAME}/issues/{num}/comments",
        headers=headers,
        json={"body": text}
    )


def create_issue(title, body):
    r = requests.post(
        f"{API}/repos/{OWNER}/{REPO_NAME}/issues",
        headers=headers,
        json={
            "title": title,
            "body": body,
            "labels": LABELS
        }
    )

    r.raise_for_status()
    return r.json()


def main():
    log = read_log()

    error = extract_stacktrace(log)

    hash_id = fingerprint(error)

    screenshot_url = upload_attachment(SCREENSHOT)

    hidden_tag = f"<!-- human-requests-hash:{hash_id} -->"

    title = "HumanRequests test failure"

    body = f"""
{hidden_tag}

### HumanRequests failure

Run: {RUN_URL}


{error}


"""

    if screenshot_url:
        body += f"\n![screenshot]({screenshot_url})\n"

    issue = search_issue(hash_id)

    timestamp = datetime.utcnow().isoformat()

    if issue:
        num = issue["number"]

        if issue["state"] == "closed":
            reopen_issue(num)

        comment_issue(
            num,
            f"""
### New incident

time: {timestamp}

Run: {RUN_URL}


{error}

""")

        print(f"Updated issue #{num}")

    else:
        issue = create_issue(title, body)
        print(f"Created issue #{issue['number']}")


if __name__ == "__main__":
    main()