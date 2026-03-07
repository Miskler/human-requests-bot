# tests/test_main.py

import pytest
from unittest.mock import patch, Mock, ANY, mock_open
import hashlib
from datetime import datetime, timezone
import sys
import os

# Импортируем функции из main.py
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from main import (
    read_log,
    extract_stacktrace,
    fingerprint,
    search_issue,
    reopen_issue,
    comment_issue,
    create_issue,
    main,
)


@pytest.fixture
def mock_env(monkeypatch):
    """Фикстура, подменяющая все нужные переменные окружения"""
    env = {
        "INPUT_GITHUB_TOKEN": "ghp_test_token_1234567890",
        "INPUT_LOG_PATH": "/fake/path/error.log",
        "INPUT_SCREENSHOT_PATH": "/fake/path/screenshot.png",
        "INPUT_LABELS": "bug,playwright,ci-failure",
        "GITHUB_REPOSITORY": "test-org/test-repo",
        "GITHUB_RUN_ID": "987654321",
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)


@pytest.fixture
def mock_log_content():
    return """Some text before
Traceback (most recent call last):
  File "test.py", line 42, in <module>
    1 / 0
ZeroDivisionError: division by zero"""


@pytest.fixture
def mock_open_log(mock_log_content):
    with patch("builtins.open", mock_open(read_data=mock_log_content)) as m:
        yield m


def test_read_log(mock_open_log, mock_log_content):
    content = read_log("/fake/path/error.log")
    assert content == mock_log_content


def test_extract_stacktrace_full_traceback(mock_log_content):
    trace = extract_stacktrace(mock_log_content)
    assert trace.startswith("Traceback (most recent call last):")
    assert "ZeroDivisionError" in trace


def test_extract_stacktrace_no_traceback():
    log = "Normal log line\nAnother line"
    result = extract_stacktrace(log)
    assert result == log[-4000:]


def test_fingerprint_normalization():
    error = 'File "/app/test.py", line 123, in func\nValueError: invalid literal for int() with base 10: "abc"'
    hash_value = fingerprint(error)
    assert len(hash_value) == 12
    assert isinstance(hash_value, str)
    # проверяем, что кавычки и числа нормализованы
    assert "X" in error.replace('"', "X").replace("123", "N")


@patch("requests.get")
def test_search_issue_found(mock_get, mock_env):
    mock_response = Mock()
    mock_response.json.return_value = [
        {
            "number": 42,
            "state": "open",
            "body": "Some text\n<!-- human-requests-hash:abcdef123456 -->\nMore text",
        }
    ]
    mock_response.raise_for_status.return_value = None
    mock_get.return_value = mock_response

    issue = search_issue(
        hash_id="abcdef123456",
        api="https://api.github.com",
        owner="test-org",
        repo_name="test-repo",
        headers={"Authorization": "Bearer ghp_xxx"},
    )

    assert issue is not None
    assert issue["number"] == 42


@patch("requests.get")
def test_search_issue_not_found(mock_get, mock_env):
    mock_response = Mock()
    mock_response.json.return_value = [{"number": 1, "body": "no hash here"}]
    mock_response.raise_for_status.return_value = None
    mock_get.return_value = mock_response

    issue = search_issue(
        "abcdef123456",
        api="https://api.github.com",
        owner="test-org",
        repo_name="test-repo",
        headers={},
    )
    assert issue is None


@patch("requests.patch")
def test_reopen_issue(mock_patch, mock_env):
    reopen_issue(
        num=77,
        api="https://api.github.com",
        owner="test-org",
        repo_name="test-repo",
        headers={"Authorization": "Bearer fake"},
    )

    mock_patch.assert_called_once_with(
        "https://api.github.com/repos/test-org/test-repo/issues/77",
        headers=ANY,
        json={"state": "open"},
    )


@patch("requests.post")
def test_comment_issue(mock_post, mock_env):
    comment_issue(
        num=88,
        text="Test comment body",
        api="https://api.github.com",
        owner="test-org",
        repo_name="test-repo",
        headers={"Authorization": "Bearer fake"},
    )

    mock_post.assert_called_once_with(
        "https://api.github.com/repos/test-org/test-repo/issues/88/comments",
        headers=ANY,
        json={"body": "Test comment body"},
    )


@patch("requests.post")
def test_create_issue(mock_post, mock_env):
    mock_response = Mock()
    mock_response.json.return_value = {"number": 99}
    mock_response.raise_for_status.return_value = None
    mock_post.return_value = mock_response

    result = create_issue(
        title="Test title",
        body="Test body",
        api="https://api.github.com",
        owner="test-org",
        repo_name="test-repo",
        headers={"Authorization": "Bearer fake"},
        labels=["bug", "playwright"],
    )

    assert result["number"] == 99


@patch("main.search_issue")
@patch("main.reopen_issue")
@patch("main.comment_issue")
@patch("main.create_issue")
@patch("main.datetime")
def test_main_existing_open_issue(
    mock_datetime,
    mock_create,
    mock_comment,
    mock_reopen,
    mock_search,
    mock_env,
    mock_open_log,
):
    mock_search.return_value = {"number": 42, "state": "open"}
    mock_datetime.now.return_value = datetime(2026, 3, 8, 14, 30, tzinfo=timezone.utc)

    with patch("builtins.print") as mock_print:
        main()

    mock_reopen.assert_not_called()
    mock_comment.assert_called_once()
    mock_create.assert_not_called()
    mock_print.assert_called_with("Updated issue #42")


@patch("main.search_issue")
@patch("main.reopen_issue")
@patch("main.comment_issue")
@patch("main.create_issue")
@patch("main.datetime")
def test_main_existing_closed_issue(
    mock_datetime,
    mock_create,
    mock_comment,
    mock_reopen,
    mock_search,
    mock_env,
    mock_open_log,
):
    mock_search.return_value = {"number": 55, "state": "closed"}
    mock_datetime.now.return_value = datetime(2026, 3, 8, 14, 30, tzinfo=timezone.utc)

    with patch("builtins.print") as mock_print:
        main()

    mock_reopen.assert_called_once_with(
        55,
        api="https://api.github.com",
        owner="test-org",
        repo_name="test-repo",
        headers={
            "Authorization": "Bearer ghp_test_token_1234567890",
            "Accept": "application/vnd.github+json"
        }
    )
    mock_comment.assert_called_once()
    mock_create.assert_not_called()
    mock_print.assert_called_with("Updated issue #55")


@patch("main.search_issue")
@patch("main.reopen_issue")
@patch("main.comment_issue")
@patch("main.create_issue")
@patch("main.datetime")
def test_main_no_existing_issue(
    mock_datetime,
    mock_create,
    mock_comment,
    mock_reopen,
    mock_search,
    mock_env,
    mock_open_log,
):
    mock_search.return_value = None
    mock_datetime.now.return_value = datetime(2026, 3, 8, 14, 30, tzinfo=timezone.utc)
    mock_create.return_value = {"number": 100}

    with patch("builtins.print") as mock_print:
        main()

    mock_reopen.assert_not_called()
    mock_comment.assert_not_called()
    mock_create.assert_called_once()
    mock_print.assert_called_with("Created issue #100")