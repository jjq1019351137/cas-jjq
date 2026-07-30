from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable


@dataclass
class ExecutionLog:
    lines: list[str] = field(default_factory=list)
    stage: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now())
    emit_line: Callable[[str], None] | None = field(default=None, repr=False)
    emit_stage: Callable[[str], None] | None = field(default=None, repr=False)
    emit_progress: Callable[[dict[str, Any]], None] | None = field(default=None, repr=False)
    # 日志行数上限：超过后保留头部 head_keep 行 + 尾部，其余截断（0 表示不限制，保持旧行为）
    max_lines: int = 0
    head_keep: int = 200
    # 每追加一行自增，用于持久化侧判断日志是否有变化，避免无变化时重复写库
    version: int = 0
    truncated_lines: int = 0

    def _append(self, line: str) -> None:
        self.version += 1
        self.lines.append(line)
        limit = int(self.max_lines or 0)
        if limit > 0 and len(self.lines) > limit:
            head = max(0, min(int(self.head_keep or 0), limit - 1))
            overflow = len(self.lines) - limit
            del self.lines[head : head + overflow]
            self.truncated_lines += overflow

    def set_stage(self, stage: str | None) -> None:
        self.stage = stage
        if self.emit_stage and stage:
            self.emit_stage(str(stage))

    def section(self, title: str) -> None:
        title = str(title or "").strip() or "阶段"
        line = f"==============={title}==============="
        self._append(line)
        if self.emit_line:
            self.emit_line(line)

    def line(self, text: str = "") -> None:
        line = str(text)
        self._append(line)
        if self.emit_line:
            self.emit_line(line)

    def progress(self, payload: dict[str, Any]) -> None:
        if self.emit_progress:
            self.emit_progress(dict(payload or {}))

    def render(self) -> str:
        if self.truncated_lines > 0:
            head = max(0, min(int(self.head_keep or 0), len(self.lines)))
            marker = f"...（日志过长，中间已省略 {self.truncated_lines} 行）..."
            merged = self.lines[:head] + [marker] + self.lines[head:]
            return "\n".join(merged).rstrip() + "\n"
        return "\n".join(self.lines).rstrip() + "\n"
