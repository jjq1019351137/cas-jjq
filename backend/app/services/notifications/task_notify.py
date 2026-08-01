from __future__ import annotations

import re

from app.models.task import Task
from app.models.task_execution import TaskExecution


DRAMA_NOTIFY_TITLE = "【智能追剧平台】"


def _normalize_savepath(value: str) -> str:
    s = str(value or "").strip()
    if not s:
        return "/"
    if not s.startswith("/"):
        s = "/" + s
    return re.sub(r"/{2,}", "/", s)


def extract_root_new_files(tree_summary: str | None) -> list[str]:
    if not tree_summary:
        return []
    result: list[str] = []
    for raw in str(tree_summary).splitlines():
        if "->" not in raw:
            continue
        right = str(raw).split("->", 1)[1].strip()
        if right:
            result.append(right)
    return result


def format_root_file_tree(names: list[str]) -> str:
    if not names:
        return ""
    if len(names) == 1:
        return f"└── 🎞️{names[0]}"
    lines: list[str] = []
    for idx, name in enumerate(names):
        prefix = "└── " if idx == len(names) - 1 else "├── "
        lines.append(f"{prefix}🎞️{name}")
    return "\n".join(lines)


def build_invalid_links_section(task: Task, execution: TaskExecution) -> str:
    """多链接场景下本次新失效的链接明细；无新失效时返回空串。

    数据由 TaskExecutor._attach_link_runtime_meta 挂在 execution 上（运行时属性，不入库）。
    """
    raw = getattr(execution, "_invalid_links", None)
    if not isinstance(raw, list) or not raw:
        return ""
    taskname = str(getattr(task, "taskname", "") or "")
    total = int(getattr(execution, "_link_total", 0) or 0)
    ok_count = int(getattr(execution, "_link_ok_count", 0) or 0)
    head = f"⚠️《{taskname}》分享链接失效 {len(raw)} 条"
    if total:
        head += f"（共 {total} 条，仍可用 {ok_count} 条）"
    lines = [head + "："]
    for item in raw:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        reason = str(item.get("reason") or "").strip()
        if not url:
            continue
        lines.append(f"• {url}")
        if reason:
            lines.append(f"  原因: {reason}")
    if len(lines) == 1:
        return ""
    return "\n".join(lines)


def build_task_section(task: Task, execution: TaskExecution) -> tuple[str, bool]:
    status = str(getattr(execution, "status", "") or "")
    taskname = str(getattr(task, "taskname", "") or "")
    message = str(getattr(execution, "message", "") or "").strip()
    # 多链接场景：部分链接失效但其他链接成功时任务整体仍为 success，
    # 必须单独抛出失效链接，否则链接逐条死掉而用户全程无感知
    invalid_section = build_invalid_links_section(task, execution)

    if status == "success":
        names = extract_root_new_files(getattr(execution, "tree_summary", None))
        if not names:
            # 无新增文件本不通知，但有链接失效时仍需告知
            return (invalid_section, True) if invalid_section else ("", False)
        savepath = _normalize_savepath(str(getattr(task, "savepath", "") or ""))
        tree = format_root_file_tree(names)
        section = f"✅《{taskname}》添加追更：\n{savepath}\n{tree}"
        if invalid_section:
            section = f"{section}\n\n{invalid_section}"
        return section, True

    if status == "skipped":
        return (invalid_section, True) if invalid_section else ("", False)

    if status == "failed":
        text = message or "未知错误"
        section = f"❌《{taskname}》执行失败：\n{text}"
        if invalid_section:
            section = f"{section}\n\n{invalid_section}"
        return section, True

    return (invalid_section, True) if invalid_section else ("", False)
