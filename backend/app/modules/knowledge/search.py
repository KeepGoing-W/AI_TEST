import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings
from app.modules.projects.models import SourceArtifact, SourceType
from app.modules.source_scans.reader import validate_local_source_root

MAX_KEYWORD_LENGTH = 128
MAX_SEARCH_RESULTS = 20


@dataclass(frozen=True)
class KeywordSearchHit:
    """受控关键词搜索命中的文件位置。"""

    relative_path: str
    line_number: int
    line_content: str


def search_with_ripgrep(artifact: SourceArtifact | None, keyword: str, settings: Settings) -> list[KeywordSearchHit]:
    """仅在已登记本地目录内使用固定参数的 ripgrep 搜索 Java 源码。"""

    # 仅支持登记的本地源码目录；ZIP 快照不允许为了搜索而解压到任意位置。
    if artifact is None or artifact.source_type != SourceType.LOCAL_PATH or not _is_safe_keyword(keyword):
        return []
    executable = shutil.which("rg")
    if executable is None:
        return []
    # 复用源码扫描的白名单校验，并固定 rg 参数，调用方无法注入额外命令参数。
    root = validate_local_source_root(Path(artifact.storage_location), settings)
    command = [
        executable,
        "--json",
        "--glob",
        "*.java",
        "--max-count",
        str(MAX_SEARCH_RESULTS),
        "--",
        keyword,
        str(root),
    ]
    try:
        completed = subprocess.run(command, capture_output=True, check=False, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return []
    # rg 的 1 表示“无匹配”，不是执行错误。
    if completed.returncode not in {0, 1}:
        return []
    return _parse_ripgrep_matches(completed.stdout, root)


def _is_safe_keyword(keyword: str) -> bool:
    return 0 < len(keyword) <= MAX_KEYWORD_LENGTH and all(character.isalnum() or character in "._$" for character in keyword)


def _parse_ripgrep_matches(output: str, root: Path) -> list[KeywordSearchHit]:
    hits: list[KeywordSearchHit] = []
    for line in output.splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("type") != "match":
            continue
        data = payload.get("data")
        if not isinstance(data, dict):
            continue
        path_value = _nested_text(data, "path")
        line_value = _nested_text(data, "lines")
        line_number = data.get("line_number")
        if path_value is None or line_value is None or not isinstance(line_number, int):
            continue
        try:
            path = Path(path_value).resolve(strict=True)
        except OSError:
            continue
        # 即使 rg 返回异常路径，也必须再次验证其仍位于登记根目录内。
        if not path.is_relative_to(root):
            continue
        hits.append(
            KeywordSearchHit(
                relative_path=path.relative_to(root).as_posix(),
                line_number=line_number,
                line_content=line_value.strip()[:500],
            )
        )
        if len(hits) >= MAX_SEARCH_RESULTS:
            break
    return hits


def _nested_text(data: dict[str, object], key: str) -> str | None:
    value = data.get(key)
    if not isinstance(value, dict):
        return None
    text = value.get("text")
    return text if isinstance(text, str) else None
