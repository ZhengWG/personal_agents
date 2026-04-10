#!/usr/bin/env python3
"""Generate a weekly repository brief with an LLM."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import subprocess
import sys
import urllib.error
import urllib.request


DEFAULT_MODEL = "gpt-4.1-mini"
DEFAULT_API_BASE = "https://api.openai.com/v1"

SYSTEM_PROMPT = (
    "You are an engineering assistant that writes concise weekly repository briefings. "
    "Use only the provided context. "
    "Output must be valid Markdown in Simplified Chinese. "
    "Include exactly these sections in order: "
    "## 本周仓库动态, ## 风险与阻塞, ## 下周建议动作. "
    "Keep it practical and specific."
)


def run_cmd(command: list[str]) -> str:
    """Run a shell command and return stripped output."""
    try:
        result = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as exc:
        return f"(command failed to start: {exc})"

    if result.returncode != 0:
        return f"(command failed: {' '.join(command)}; stderr={result.stderr.strip()})"
    return result.stdout.strip()


def collect_repo_context() -> str:
    """Collect lightweight git context for the prompt."""
    branch = run_cmd(["git", "branch", "--show-current"])
    recent_commits = run_cmd(
        ["git", "log", "--since=7.days", "--pretty=format:%h %ad %s", "--date=short"]
    )
    short_status = run_cmd(["git", "status", "--short"])

    if not recent_commits:
        recent_commits = "(过去 7 天没有提交记录)"
    if not short_status:
        short_status = "(工作区干净)"

    today = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
    return (
        f"日期(UTC): {today}\n"
        f"当前分支: {branch or '(unknown)'}\n\n"
        f"[最近 7 天提交]\n{recent_commits}\n\n"
        f"[当前工作区状态]\n{short_status}\n"
    )


def extract_text_from_response(payload: dict) -> str:
    """Extract text content from OpenAI responses API payload."""
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    output = payload.get("output", [])
    chunks: list[str] = []
    for item in output:
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                chunks.append(content["text"])
    return "\n".join(chunks).strip()


def call_openai(model: str, context: str, api_key: str, api_base: str) -> str:
    """Call OpenAI Responses API and return model text."""
    endpoint = f"{api_base.rstrip('/')}/responses"
    user_prompt = (
        "请基于以下仓库上下文生成周报草稿：\n\n"
        f"{context}\n\n"
        "要求：不要杜撰未提供的信息；重点写可执行建议。"
    )
    body = {
        "model": model,
        "input": [
            {"role": "system", "content": [{"type": "text", "text": SYSTEM_PROMPT}]},
            {"role": "user", "content": [{"type": "text", "text": user_prompt}]},
        ],
        "temperature": 0.2,
        "max_output_tokens": 1200,
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API error: HTTP {exc.code}: {details}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"OpenAI API connection error: {exc}") from exc

    text = extract_text_from_response(response_payload)
    if not text:
        raise RuntimeError("OpenAI API returned empty content.")
    return text


def write_report(output_dir: pathlib.Path, model: str, content: str) -> pathlib.Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.UTC)
    timestamp = now.strftime("%Y%m%d-%H%M%S")
    report_file = output_dir / f"weekly-brief-{timestamp}.md"
    report_file.write_text(
        f"# Weekly Repo Brief\n\n"
        f"- generated_at_utc: {now.isoformat()}\n"
        f"- model: {model}\n\n"
        f"{content}\n",
        encoding="utf-8",
    )
    return report_file


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Weekly repo brief agent")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate a local mock report without API call",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    model = (os.getenv("AGENT_MODEL") or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    api_base = (os.getenv("OPENAI_API_BASE") or DEFAULT_API_BASE).strip() or DEFAULT_API_BASE
    output_dir = pathlib.Path(os.getenv("AGENT_OUTPUT_DIR", "agent_outputs"))
    context = collect_repo_context()

    if args.dry_run:
        content = (
            "## 本周仓库动态\n"
            "- Dry-run 模式：未调用远程模型。\n"
            "- 已采集仓库最近 7 天提交和当前状态。\n\n"
            "## 风险与阻塞\n"
            "- 当前输出仅用于流程验证，不代表真实分析结果。\n\n"
            "## 下周建议动作\n"
            "- 配置 OPENAI_API_KEY 后执行正式任务。\n"
        )
    else:
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            print("ERROR: OPENAI_API_KEY is required (or run with --dry-run).", file=sys.stderr)
            return 2
        content = call_openai(model=model, context=context, api_key=api_key, api_base=api_base)

    report_file = write_report(output_dir=output_dir, model=model, content=content)
    print(f"Generated report: {report_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
