from __future__ import annotations

import json
import os
import re
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
INPUT_DIR = ROOT / "input"
MEMORY_DIR = ROOT / "memory"
OUTPUT_DIR = ROOT / "output"
STATIC_DIR = ROOT / "static"

PROJECT_FILES = {
    "outline": INPUT_DIR / "outline.txt",
    "characters": INPUT_DIR / "characters.txt",
    "chapters": INPUT_DIR / "chapters.txt",
    "style": INPUT_DIR / "style.txt",
}

SUMMARY_FILE = MEMORY_DIR / "summary.txt"
STATE_FILE = MEMORY_DIR / "character-state.txt"
NOVEL_FILE = OUTPUT_DIR / "novel.md"


def ensure_dirs() -> None:
    for directory in (INPUT_DIR, MEMORY_DIR, OUTPUT_DIR, STATIC_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def json_response(handler: SimpleHTTPRequestHandler, data: dict[str, Any], status: int = 200) -> None:
    body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def read_json_body(handler: SimpleHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0"))
    raw = handler.rfile.read(length) if length else b"{}"
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def parse_chapters(chapters_text: str) -> list[dict[str, str]]:
    blocks: list[str] = []
    current: list[str] = []

    for line in chapters_text.splitlines():
        stripped = line.strip()
        if re.match(r"^(第\s*[一二三四五六七八九十百千万\d]+\s*章|Chapter\s+\d+|\d+[\.、])", stripped, re.I):
            if current:
                blocks.append("\n".join(current).strip())
            current = [stripped]
        elif stripped:
            current.append(stripped)

    if current:
        blocks.append("\n".join(current).strip())

    if not blocks:
        blocks = [block.strip() for block in re.split(r"\n\s*\n", chapters_text) if block.strip()]

    chapters: list[dict[str, str]] = []
    for index, block in enumerate(blocks, start=1):
        first_line = block.splitlines()[0].strip()
        title = first_line
        match = re.match(r"^(第\s*[一二三四五六七八九十百千万\d]+\s*章[:：\s-]*|Chapter\s+\d+[:：\s-]*|\d+[\.、]\s*)?(.*)$", first_line, re.I)
        if match and match.group(2).strip():
            title = match.group(2).strip()
        chapters.append({"number": str(index), "title": title, "requirement": block})

    return chapters


@dataclass
class ApiConfig:
    style: str
    api_key: str
    base_url: str
    model: str
    timeout: int
    max_tokens: int
    anthropic_version: str
    reasoning_depth: str

    @classmethod
    def from_options(cls, options: dict[str, Any]) -> "ApiConfig":
        style = normalize_api_style(str(options.get("apiStyle") or os.getenv("NOVEL_API_STYLE") or "chat"))
        base_url = str(options.get("baseUrl") or os.getenv("OPENAI_BASE_URL") or default_base_url(style)).strip()
        model = str(options.get("model") or os.getenv("OPENAI_MODEL") or default_model(style)).strip()
        return cls(
            style=style,
            api_key=str(options.get("apiKey") or os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY") or "").strip(),
            base_url=base_url.rstrip("/"),
            model=model,
            timeout=int(options.get("timeout") or os.getenv("OPENAI_TIMEOUT") or 180),
            max_tokens=int(options.get("maxTokens") or os.getenv("OPENAI_MAX_TOKENS") or 8192),
            anthropic_version=str(options.get("anthropicVersion") or os.getenv("ANTHROPIC_VERSION") or "2023-06-01").strip(),
            reasoning_depth=normalize_reasoning_depth(str(options.get("reasoningDepth") or os.getenv("REASONING_DEPTH") or "none")),
        )


def normalize_api_style(style: str) -> str:
    value = style.strip().lower().replace("_", "-")
    if value in {"response", "responses"}:
        return "responses"
    if value in {"anthropic", "authpic", "claude"}:
        return "anthropic"
    return "chat"


def normalize_reasoning_depth(depth: str) -> str:
    value = depth.strip().lower()
    if value in {"low", "medium", "high"}:
        return value
    return "none"


def default_base_url(style: str) -> str:
    if style == "anthropic":
        return "https://api.anthropic.com/v1"
    return "https://api.openai.com/v1"


def default_model(style: str) -> str:
    if style == "anthropic":
        return "claude-sonnet-4-5"
    if style == "responses":
        return "gpt-4.1-mini"
    return "gpt-4.1-mini"


def join_url(base_url: str, path: str) -> str:
    parsed = urllib.parse.urlparse(base_url)
    if parsed.path.endswith(path):
        return base_url
    return f"{base_url.rstrip('/')}{path}"


def extract_response_text(result: dict[str, Any], style: str) -> str:
    if style == "chat":
        return result["choices"][0]["message"]["content"].strip()
    if style == "anthropic":
        parts = []
        for item in result.get("content", []):
            if item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "\n".join(parts).strip()

    if result.get("output_text"):
        return str(result["output_text"]).strip()

    parts: list[str] = []
    for item in result.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"}:
                parts.append(str(content.get("text", "")))
    return "\n".join(parts).strip()


def chat_completion(messages: list[dict[str, str]], api_config: ApiConfig, temperature: float = 0.7) -> str:
    if os.getenv("NOVEL_MOCK") == "1":
        return mock_completion(messages)

    if not api_config.api_key:
        raise RuntimeError("请先在页面填写 API Key。")

    payload = build_payload(messages, api_config, temperature)
    endpoint = api_endpoint(api_config)
    headers = api_headers(api_config)
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    request = urllib.request.Request(
        endpoint,
        data=data,
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=api_config.timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"AI 接口返回错误 {exc.code}: {detail}") from exc

    text = extract_response_text(result, api_config.style)
    if not text:
        raise RuntimeError("AI 接口返回了空内容，请检查接口风格和模型是否匹配。")
    return text


def test_api_config(api_config: ApiConfig) -> str:
    test_config = ApiConfig(
        style=api_config.style,
        api_key=api_config.api_key,
        base_url=api_config.base_url,
        model=api_config.model,
        timeout=api_config.timeout,
        max_tokens=min(api_config.max_tokens, 64),
        anthropic_version=api_config.anthropic_version,
        reasoning_depth="none",
    )
    return chat_completion(
        [
            {"role": "system", "content": "你只用于测试 API 连通性。"},
            {"role": "user", "content": "请只回复：连接成功"},
        ],
        test_config,
        temperature=0,
    )


def list_models(api_config: ApiConfig) -> list[str]:
    if os.getenv("NOVEL_MOCK") == "1":
        if api_config.style == "anthropic":
            return ["claude-sonnet-4-5", "claude-opus-4-1"]
        return ["gpt-4.1-mini", "gpt-4.1", "o4-mini"]

    if not api_config.api_key:
        raise RuntimeError("请先填写 API Key。")

    request = urllib.request.Request(
        join_url(api_config.base_url, "/models"),
        headers=api_headers(api_config),
        method="GET",
    )

    try:
        with urllib.request.urlopen(request, timeout=api_config.timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"获取模型失败 {exc.code}: {detail}") from exc

    raw_models = result.get("data", [])
    models: list[str] = []
    for item in raw_models:
        model_id = item.get("id") if isinstance(item, dict) else str(item)
        if model_id:
            models.append(str(model_id))
    return sorted(models)


def build_payload(messages: list[dict[str, str]], api_config: ApiConfig, temperature: float) -> dict[str, Any]:
    if api_config.style == "chat":
        payload: dict[str, Any] = {
            "model": api_config.model,
            "messages": messages,
            "temperature": temperature,
        }
        if api_config.max_tokens > 0:
            payload["max_tokens"] = api_config.max_tokens
        if api_config.reasoning_depth != "none":
            payload["reasoning_effort"] = api_config.reasoning_depth
        return payload

    if api_config.style == "responses":
        payload = {
            "model": api_config.model,
            "input": messages,
            "temperature": temperature,
        }
        if api_config.max_tokens > 0:
            payload["max_output_tokens"] = api_config.max_tokens
        if api_config.reasoning_depth != "none":
            payload["reasoning"] = {"effort": api_config.reasoning_depth}
        return payload

    system_parts = [message["content"] for message in messages if message["role"] == "system"]
    anthropic_messages = [
        {"role": message["role"], "content": message["content"]}
        for message in messages
        if message["role"] in {"user", "assistant"}
    ]
    return {
        "model": api_config.model,
        "system": "\n\n".join(system_parts),
        "messages": anthropic_messages,
        "max_tokens": max(api_config.max_tokens, 1),
        "temperature": temperature,
    }
    if api_config.reasoning_depth != "none":
        # Anthropic 风格接口用 thinking 预算表达推理深度，预算必须小于最大输出。
        if api_config.max_tokens > 1024:
            budget = {"low": 1024, "medium": 4096, "high": 8192}[api_config.reasoning_depth]
            payload["thinking"] = {"type": "enabled", "budget_tokens": min(budget, api_config.max_tokens - 1)}
    return payload


def api_endpoint(api_config: ApiConfig) -> str:
    if api_config.style == "responses":
        return join_url(api_config.base_url, "/responses")
    if api_config.style == "anthropic":
        return join_url(api_config.base_url, "/messages")
    return join_url(api_config.base_url, "/chat/completions")


def api_headers(api_config: ApiConfig) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_config.style == "anthropic":
        headers["x-api-key"] = api_config.api_key
        headers["anthropic-version"] = api_config.anthropic_version
        return headers
    headers["Authorization"] = f"Bearer {api_config.api_key}"
    return headers


def mock_completion(messages: list[dict[str, str]]) -> str:
    text = messages[-1]["content"]
    chapter_match = re.search(r"【当前章节】\s*(.*?)\n", text, re.S)
    chapter = chapter_match.group(1).strip() if chapter_match else "测试章节"
    if "请检查这一章是否" in text:
        return "通过"
    if "请更新前文记忆" in text:
        return "本章完成了当前章节要求，人物状态与主线继续向前推进。"
    if "请更新人物状态" in text:
        return "主要人物保持既定性格与动机，关系随本章事件产生了细微变化。"
    return f"# {chapter}\n\n这是模拟生成内容。当前章节严格承接前文记忆，遵守人物设定，并完成本章要求。\n"


@dataclass
class Job:
    id: str
    status: str = "running"
    current: int = 0
    total: int = 0
    message: str = "准备生成"
    error: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    stop_requested: bool = False
    logs: list[str] = field(default_factory=list)

    def log(self, message: str) -> None:
        self.message = message
        self.logs.append(message)
        self.logs = self.logs[-120:]


jobs: dict[str, Job] = {}
jobs_lock = threading.Lock()


class NovelGenerator:
    def __init__(self, job: Job, options: dict[str, Any]) -> None:
        self.job = job
        self.target_words = int(options.get("targetWords") or 3000)
        self.max_revisions = int(options.get("maxRevisions") or 1)
        self.temperature = float(options.get("temperature") or 0.75)
        self.api_config = ApiConfig.from_options(options)
        self.project = {key: read_text(path).strip() for key, path in PROJECT_FILES.items()}
        self.summary = read_text(SUMMARY_FILE).strip()
        self.state = read_text(STATE_FILE).strip()
        self.chapters = parse_chapters(self.project["chapters"])
        self.job.total = len(self.chapters)

    def run(self) -> None:
        if not self.project["outline"]:
            raise RuntimeError("请先填写故事大纲。")
        if not self.project["characters"]:
            raise RuntimeError("请先填写人物设定。")
        if not self.chapters:
            raise RuntimeError("请先填写章节目录。")

        generated_files: list[Path] = []
        for chapter in self.chapters:
            if self.job.stop_requested:
                self.job.status = "stopped"
                self.job.log("已暂停")
                return

            chapter_number = int(chapter["number"])
            self.job.current = chapter_number
            chapter_file = OUTPUT_DIR / f"chapter-{chapter_number:03d}.md"
            self.job.log(f"正在生成第 {chapter_number}/{self.job.total} 章：{chapter['title']}")

            content = self.generate_chapter(chapter)
            content = self.revise_until_pass(chapter, content)
            write_text(chapter_file, content.strip() + "\n")
            generated_files.append(chapter_file)

            self.summary = self.update_summary(chapter, content)
            self.state = self.update_state(chapter, content)
            write_text(SUMMARY_FILE, self.summary.strip() + "\n")
            write_text(STATE_FILE, self.state.strip() + "\n")

        self.merge_novel(generated_files)
        self.job.status = "done"
        self.job.finished_at = time.time()
        self.job.log(f"整本小说已生成：{NOVEL_FILE}")

    def generate_chapter(self, chapter: dict[str, str]) -> str:
        prompt = f"""你是长篇小说写作助手。

你必须严格遵守以下规则：
1. 只能创作当前章节，不得跳到后续剧情。
2. 必须严格遵守故事大纲、人物设定、章节目录。
3. 不得改变人物性格、关系、动机和背景。
4. 不得提前揭露后续章节的秘密。
5. 必须承接前文，保持时间线和人物状态一致。
6. 当前章节必须完成“本章要求”里的所有事件。
7. 如果设定和剧情冲突，以人物设定和故事大纲为准。
8. 只输出小说正文，不要解释生成过程。

【故事大纲】
{self.project["outline"]}

【人物设定】
{self.project["characters"]}

【写作风格】
{self.project["style"] or "语言自然，叙事连贯，人物行动符合动机。"}

【完整章节目录】
{self.project["chapters"]}

【已发生剧情摘要】
{self.summary or "暂无，这是第一章。"}

【当前人物状态】
{self.state or "以人物设定为准。"}

【当前章节】
第 {chapter["number"]} 章：{chapter["title"]}

【本章要求】
{chapter["requirement"]}

请创作本章正文，字数约 {self.target_words} 字。"""

        return chat_completion(
            [
                {"role": "system", "content": "你是严谨的长篇小说代写引擎，必须服从结构化设定。"},
                {"role": "user", "content": prompt},
            ],
            self.api_config,
            temperature=self.temperature,
        )

    def revise_until_pass(self, chapter: dict[str, str], content: str) -> str:
        revised = content
        for attempt in range(self.max_revisions + 1):
            check = self.check_chapter(chapter, revised)
            if "通过" in check[:80]:
                return revised
            if attempt >= self.max_revisions:
                self.job.log(f"第 {chapter['number']} 章检查仍有问题，已保留最后一次修订版本")
                return revised
            self.job.log(f"第 {chapter['number']} 章检查未通过，正在按问题修订")
            revised = self.revise_chapter(chapter, revised, check)
        return revised

    def check_chapter(self, chapter: dict[str, str], content: str) -> str:
        prompt = f"""请检查这一章是否：
1. 偏离故事大纲
2. 违反人物设定
3. 提前剧透后续剧情
4. 漏掉本章必须事件
5. 和前文摘要或人物状态矛盾

如果没有问题，只输出：通过
如果有问题，请用简短清单列出必须修正的问题。

【故事大纲】
{self.project["outline"]}

【人物设定】
{self.project["characters"]}

【完整章节目录】
{self.project["chapters"]}

【已发生剧情摘要】
{self.summary or "暂无"}

【当前人物状态】
{self.state or "以人物设定为准"}

【当前章节要求】
{chapter["requirement"]}

【待检查正文】
{content}"""

        return chat_completion(
            [
                {"role": "system", "content": "你是小说连续性审稿人，只判断是否违背既定设定。"},
                {"role": "user", "content": prompt},
            ],
            self.api_config,
            temperature=0.2,
        )

    def revise_chapter(self, chapter: dict[str, str], content: str, issues: str) -> str:
        prompt = f"""请根据问题清单修订当前章节。必须保留章节正文形式，只输出修订后的小说正文。

【问题清单】
{issues}

【故事大纲】
{self.project["outline"]}

【人物设定】
{self.project["characters"]}

【完整章节目录】
{self.project["chapters"]}

【已发生剧情摘要】
{self.summary or "暂无"}

【当前人物状态】
{self.state or "以人物设定为准"}

【当前章节要求】
{chapter["requirement"]}

【原正文】
{content}"""

        return chat_completion(
            [
                {"role": "system", "content": "你是小说修订助手，只修正偏离设定的问题。"},
                {"role": "user", "content": prompt},
            ],
            self.api_config,
            temperature=0.55,
        )

    def update_summary(self, chapter: dict[str, str], content: str) -> str:
        prompt = f"""请更新前文记忆，用简洁中文记录已经发生的剧情、时间线、重要线索和未回收伏笔。
保留旧摘要中的关键信息，合并本章新增信息。不要写评价。

【旧前文记忆】
{self.summary or "暂无"}

【当前章节】
第 {chapter["number"]} 章：{chapter["title"]}

【本章正文】
{content}"""

        return chat_completion(
            [
                {"role": "system", "content": "你是长篇小说记忆管理员，负责压缩剧情上下文。"},
                {"role": "user", "content": prompt},
            ],
            self.api_config,
            temperature=0.2,
        )

    def update_state(self, chapter: dict[str, str], content: str) -> str:
        prompt = f"""请更新人物状态表，记录主要人物的当前处境、动机、关系变化、掌握的信息和不能遗忘的伤病/物品/秘密。
保留旧状态中的关键信息，合并本章新增信息。不要写评价。

【人物设定】
{self.project["characters"]}

【旧人物状态】
{self.state or "暂无"}

【当前章节】
第 {chapter["number"]} 章：{chapter["title"]}

【本章正文】
{content}"""

        return chat_completion(
            [
                {"role": "system", "content": "你是长篇小说人物状态管理员，负责保持人设连续。"},
                {"role": "user", "content": prompt},
            ],
            self.api_config,
            temperature=0.2,
        )

    def merge_novel(self, files: list[Path]) -> None:
        parts = [read_text(path).strip() for path in files if path.exists()]
        write_text(NOVEL_FILE, "\n\n".join(parts).strip() + "\n")


def start_generation(options: dict[str, Any]) -> Job:
    job = Job(id=str(int(time.time() * 1000)))
    with jobs_lock:
        jobs[job.id] = job

    def worker() -> None:
        try:
            NovelGenerator(job, options).run()
        except Exception as exc:
            job.status = "error"
            job.error = str(exc)
            job.finished_at = time.time()
            job.log(f"生成失败：{exc}")
            traceback.print_exc()

    threading.Thread(target=worker, daemon=True).start()
    return job


class Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path: str) -> str:
        if path == "/":
            return str(STATIC_DIR / "index.html")
        if path.startswith("/static/"):
            return str(ROOT / path.lstrip("/"))
        return str(STATIC_DIR / path.lstrip("/"))

    def do_GET(self) -> None:
        if self.path == "/api/project":
            json_response(self, {key: read_text(path) for key, path in PROJECT_FILES.items()})
            return
        if self.path == "/api/memory":
            json_response(self, {"summary": read_text(SUMMARY_FILE), "state": read_text(STATE_FILE)})
            return
        if self.path.startswith("/api/status/"):
            job_id = self.path.rsplit("/", 1)[-1]
            with jobs_lock:
                job = jobs.get(job_id)
            if not job:
                json_response(self, {"error": "任务不存在"}, HTTPStatus.NOT_FOUND)
                return
            json_response(self, job.__dict__)
            return
        if self.path == "/api/output":
            json_response(
                self,
                {
                    "novel": read_text(NOVEL_FILE),
                    "path": str(NOVEL_FILE),
                    "exists": NOVEL_FILE.exists(),
                },
            )
            return
        super().do_GET()

    def do_POST(self) -> None:
        if self.path == "/api/project":
            data = read_json_body(self)
            for key, path in PROJECT_FILES.items():
                write_text(path, str(data.get(key, "")))
            json_response(self, {"ok": True})
            return
        if self.path == "/api/test-config":
            data = read_json_body(self)
            reply = test_api_config(ApiConfig.from_options(data))
            json_response(self, {"ok": True, "reply": reply})
            return
        if self.path == "/api/models":
            data = read_json_body(self)
            models = list_models(ApiConfig.from_options(data))
            json_response(self, {"ok": True, "models": models})
            return
        if self.path == "/api/generate":
            data = read_json_body(self)
            job = start_generation(data)
            json_response(self, {"jobId": job.id})
            return
        if self.path.startswith("/api/stop/"):
            job_id = self.path.rsplit("/", 1)[-1]
            with jobs_lock:
                job = jobs.get(job_id)
            if not job:
                json_response(self, {"error": "任务不存在"}, HTTPStatus.NOT_FOUND)
                return
            job.stop_requested = True
            json_response(self, {"ok": True})
            return
        json_response(self, {"error": "未知接口"}, HTTPStatus.NOT_FOUND)


def main() -> None:
    ensure_dirs()
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"EasyNovel running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
