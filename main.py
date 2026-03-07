import os
import re
import hashlib
import requests
from datetime import datetime
from jinja2 import Template
import base64
from io import BytesIO
from PIL import Image

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
        json={"title": title, "body": body, "labels": LABELS}
    )
    r.raise_for_status()
    return r.json()


def get_screenshot_data_url(screenshot_path, quality=80):
    if not screenshot_path or not os.path.exists(screenshot_path):
        return None

    try:
        with Image.open(screenshot_path) as img:
            # Если изображение в RGBA → конвертируем в RGB (WebP lossy не поддерживает альфа-канал)
            if img.mode in ("RGBA", "LA"):
                background = Image.new("RGB", img.size, (255, 255, 255))
                background.paste(img, mask=img.split()[-1])
                img = background
            elif img.mode != "RGB":
                img = img.convert("RGB")

            buffer = BytesIO()
            img.save(
                buffer,
                format="WEBP",
                quality=quality,         # 0–100; 75–85 — хороший баланс
                method=6                 # 0–6; 4–6 — лучшее сжатие
            )
            buffer.seek(0)
            b64_data = base64.b64encode(buffer.read()).decode("utf-8")
            return f"data:image/webp;base64,{b64_data}"

    except Exception as e:
        print(f"Error converting image to WebP: {e}")
        # Fallback: оригинальный PNG в base64
        with open(screenshot_path, "rb") as f:
            data = base64.b64encode(f.read()).decode("utf-8")
        return f"data:image/png;base64,{data}"


def write_summary(screenshot_path):
    data_url = get_screenshot_data_url(screenshot_path, quality=82)
    if data_url:
        summary_file = os.getenv("GITHUB_STEP_SUMMARY")
        if summary_file and os.path.exists(summary_file):
            with open(summary_file, "a", encoding="utf-8") as f:
                f.write(f"### Screenshot\n![Screenshot]({data_url})\n")

ISSUE_TEMPLATE = """
{{ hidden_tag }}

### Error HumanRequests

Run: {{ run_url }}

```python
{{ error }}
```
{% if screenshot_url %}
![Screenshot]({{ screenshot_url }})
{% endif %}
"""
COMMENT_TEMPLATE = """
New incident
Time: {{ timestamp }}
Run: {{ run_url }}

```python
{{ error }}
```
{% if screenshot_url %}
![Screenshot]({{ screenshot_url }})
{% endif %}
"""
def main():
    log = read_log()
    error = extract_stacktrace(log)
    hash_id = fingerprint(error)
    hidden_tag = f"<!-- human-requests-hash:{hash_id} -->"
    screenshot_data_url = get_screenshot_data_url(SCREENSHOT, quality=82)
    title = "Test error HumanRequests"
    body = Template(ISSUE_TEMPLATE).render(
        hidden_tag=hidden_tag,
        run_url=RUN_URL,
        error=error,
        screenshot_url=screenshot_data_url
    )
    issue = search_issue(hash_id)
    timestamp = datetime.utcnow().isoformat()
    if issue:
        num = issue["number"]
    if issue["state"] == "closed":
        reopen_issue(num)
        comment = Template(COMMENT_TEMPLATE).render(
            timestamp=timestamp,
            run_url=RUN_URL,
            error=error,
            screenshot_url=screenshot_data_url
        )
        comment_issue(num, comment)
        print(f"Updated issue #{num}")
    else:
        issue = create_issue(title, body)
        print(f"Created issue #{issue['number']}")
    
    if SCREENSHOT:
        write_summary(SCREENSHOT)

if __name__ == "__main__":
    main()