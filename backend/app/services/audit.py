from __future__ import annotations

import logging
from typing import Any, Iterable, Mapping

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog

logger = logging.getLogger(__name__)

# detail 最大字符数（约 512KB），超出则头尾保留并标注省略
_DETAIL_LIMIT = 512 * 1024


# ==================== 操作方 / 来源 ====================
class SystemActor:
    """非人类操作方（调度器 / 自动流程 / 联动触发 / 机器人等）。"""

    def __init__(self, username: str) -> None:
        self.username = username

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"SystemActor({self.username!r})"


SCHEDULER_ACTOR = SystemActor("调度器")
AUTO_ACTOR = SystemActor("自动流程")
LINKED_ACTOR = SystemActor("联动触发")

SOURCE_MANUAL = "manual"
SOURCE_SCHEDULER = "scheduler"
SOURCE_LINKED = "linked"
SOURCE_AUTO = "auto"

SOURCES: dict[str, str] = {
    SOURCE_MANUAL: "手动",
    SOURCE_SCHEDULER: "调度器",
    SOURCE_LINKED: "联动触发",
    SOURCE_AUTO: "自动流程",
}

_SOURCE_ACTOR: dict[str, SystemActor] = {
    SOURCE_SCHEDULER: SCHEDULER_ACTOR,
    SOURCE_LINKED: LINKED_ACTOR,
    SOURCE_AUTO: AUTO_ACTOR,
}


# ==================== 业务分类 ====================
CATEGORIES: dict[str, str] = {
    "auth": "认证",
    "setup": "初始化",
    "user": "用户",
    "role": "角色",
    "task": "追剧任务",
    "sync_task": "同步任务",
    "drive_account": "网盘账号",
    "plugin": "插件",
    "sync_plugin": "同步插件",
    "magic_regex": "魔法正则",
    "resource_search": "资源搜索",
    "notify": "通知",
    "openlist": "OpenList",
    "dl302": "DL302",
    "tmdb": "TMDB",
    "system_settings": "系统设置",
}


# ==================== action 注册表 ====================
# action -> (category, 中文名)
AUDIT_ACTIONS: dict[str, tuple[str, str]] = {
    # 认证
    "auth.login": ("auth", "登录"),
    "auth.logout": ("auth", "登出"),
    "auth.refresh": ("auth", "刷新令牌"),
    "setup.init_admin": ("setup", "初始化管理员"),
    # 用户 / 角色
    "user.create": ("user", "创建用户"),
    "user.set_roles": ("user", "设置用户角色"),
    "user.set_status": ("user", "设置用户状态"),
    "user.batch_set_roles": ("user", "批量设置角色"),
    "user.batch_set_status": ("user", "批量设置状态"),
    "role.create": ("role", "创建角色"),
    "role.update": ("role", "更新角色"),
    "role.delete": ("role", "删除角色"),
    "role.set_permissions": ("role", "设置角色权限"),
    # 追剧任务
    "task.create": ("task", "创建任务"),
    "task.update": ("task", "更新任务"),
    "task.delete": ("task", "删除任务"),
    "task.status": ("task", "启停任务"),
    "task.run": ("task", "运行任务"),
    "task.run.stream": ("task", "运行任务"),
    "task.run.preview_stream": ("task", "预览运行"),
    "task.scheduler.update": ("task", "更新调度"),
    "task.drama.stop_completed": ("task", "停止完结剧"),
    "task.drama.sync_savepath_snapshots": ("task", "同步保存路径快照"),
    "task.shareurl_repair": ("task", "修复失效分享链接"),
    "task.shareurl_autoupdate": ("task", "自动换链"),
    # 同步任务
    "sync_task.create": ("sync_task", "创建同步任务"),
    "sync_task.update": ("sync_task", "更新同步任务"),
    "sync_task.delete": ("sync_task", "删除同步任务"),
    "sync_task.run": ("sync_task", "运行同步任务"),
    "sync_task.run.stream": ("sync_task", "运行同步任务"),
    "sync_task.execution.cancel": ("sync_task", "取消同步执行"),
    # 网盘账号
    "drive_account.create": ("drive_account", "创建账号"),
    "drive_account.update": ("drive_account", "更新账号"),
    "drive_account.delete": ("drive_account", "删除账号"),
    "drive_account.default": ("drive_account", "设为默认账号"),
    "drive_account.status": ("drive_account", "账号状态"),
    "drive_account.probe": ("drive_account", "探测账号"),
    "drive_account.probe_scheduler.update": ("drive_account", "更新探测调度"),
    "drive_account.refresh_profiles": ("drive_account", "刷新账号资料"),
    "drive_account.lsdir_cache_refresh": ("drive_account", "刷新目录缓存"),
    "drive_account.sign_in": ("drive_account", "账号签到"),
    "drive_account.sign_in.submit": ("drive_account", "提交签到"),
    "drive_account.auth_start": ("drive_account", "开始登录"),
    "drive_account.auth_captcha": ("drive_account", "登录验证码"),
    "drive_account.auth_sms_send": ("drive_account", "发送短信验证码"),
    "drive_account.auth_sms_submit": ("drive_account", "提交短信验证码"),
    "drive_account.auth_qrcode_start": ("drive_account", "开始扫码登录"),
    "drive_account.auth_qrcode_poll": ("drive_account", "轮询扫码状态"),
    "drive_account.auth_qrcode_confirm": ("drive_account", "确认扫码登录"),
    # 插件
    "plugin.refresh": ("plugin", "刷新插件"),
    "plugin.update": ("plugin", "更新插件"),
    "sync_plugin.refresh": ("sync_plugin", "刷新同步插件"),
    "sync_plugin.update": ("sync_plugin", "更新同步插件"),
    # 其它设置
    "magic_regex.upsert": ("magic_regex", "保存正则规则"),
    "magic_regex.delete": ("magic_regex", "删除正则规则"),
    "resource_search.source.update": ("resource_search", "更新搜索源"),
    "notify.config.update": ("notify", "更新通知配置"),
    "notify.test.send": ("notify", "发送测试通知"),
    "openlist.config.update": ("openlist", "更新 OpenList 配置"),
    "system_settings.save_rules.update": ("system_settings", "更新保存规则"),
    "tmdb.config.update": ("tmdb", "更新 TMDB 配置"),
    "tmdb.cache.refresh": ("tmdb", "刷新 TMDB 缓存"),
    "tmdb.cache.refresh_linked_tasks": ("tmdb", "刷新关联任务缓存"),
    "tmdb.cache.delete": ("tmdb", "删除 TMDB 缓存"),
    "tmdb.cache.purge": ("tmdb", "清空 TMDB 缓存"),
    "tmdb.cache.set_ttl": ("tmdb", "设置缓存 TTL"),
    "tmdb.cache.scheduler.update": ("tmdb", "更新缓存调度"),
}


def category_of(action: str) -> str:
    """由 action 解析业务分类：优先注册表，其次取 action 的第一段前缀。"""
    meta = AUDIT_ACTIONS.get(action)
    if meta:
        return meta[0]
    return (action or "").split(".", 1)[0] or "other"


def action_label(action: str) -> str:
    """action 的中文名，未注册时回退为 action 本身。"""
    meta = AUDIT_ACTIONS.get(action)
    if meta:
        return meta[1]
    return action or ""


def category_label(category: str) -> str:
    return CATEGORIES.get(category, category)


def source_label(source: str | None) -> str | None:
    if not source:
        return None
    return SOURCES.get(source, source)


def action_registry() -> dict[str, Any]:
    """供前端过滤/展示使用的注册表快照。"""
    return {
        "actions": [
            {"code": code, "label": label, "category": cat, "category_label": category_label(cat)}
            for code, (cat, label) in AUDIT_ACTIONS.items()
        ],
        "categories": dict(CATEGORIES),
        "sources": dict(SOURCES),
    }


def changed_field_labels(
    before: Mapping[str, Any], after: Mapping[str, Any], labels: Mapping[str, str]
) -> list[str]:
    """比较 before/after，返回发生变化字段的中文标签列表（按 labels 声明顺序）。

    仅考虑出现在 after 中的字段；值未变化的忽略。
    """
    changed: list[str] = []
    for key, label in labels.items():
        if key not in after:
            continue
        if before.get(key) != after.get(key):
            changed.append(label)
    return changed


# ==================== 内部写入 ====================
def _truncate_detail(detail: str | None) -> str | None:
    if not detail:
        return detail
    if len(detail) <= _DETAIL_LIMIT:
        return detail
    keep = _DETAIL_LIMIT - 64
    head = detail[: keep // 2]
    tail = detail[-(keep // 2):]
    omitted = len(detail) - len(head) - len(tail)
    return f"{head}\n……（省略 {omitted} 字）……\n{tail}"


def _actor_fields(actor: Any) -> tuple[str, int | None, str | None]:
    """解析操作方 → (actor_type, actor_user_id, actor_username)。"""
    if actor is None:
        return "user", None, None
    if isinstance(actor, SystemActor):
        return "system", None, actor.username
    # ORM User（鸭子类型）
    uid = getattr(actor, "id", None)
    uname = getattr(actor, "username", None)
    return "user", uid, uname


def _build_row(
    *,
    actor: Any,
    action: str,
    summary: str,
    target_type: str | None,
    target_id: Any,
    target_name: str | None,
    source: str | None,
    detail: str | None,
    success: bool,
    error_message: str | None,
    ip: str | None,
) -> AuditLog:
    actor_type, actor_user_id, actor_username = _actor_fields(actor)
    return AuditLog(
        actor_type=actor_type,
        actor_user_id=actor_user_id,
        actor_username=actor_username,
        source=source,
        category=category_of(action),
        action=action,
        target_type=target_type,
        target_id=(None if target_id is None else str(target_id)),
        target_name=target_name,
        summary=summary or action_label(action),
        detail=_truncate_detail(detail),
        ip=ip,
        success=bool(success),
        error_message=error_message,
    )


def audit_log(
    db: Session,
    *,
    actor: Any = None,
    action: str,
    summary: str,
    target_type: str | None = None,
    target_id: Any = None,
    target_name: str | None = None,
    source: str | None = None,
    detail: str | None = None,
    success: bool = True,
    error_message: str | None = None,
    ip: str | None = None,
) -> None:
    """在给定事务内写入一条审计（不提交，由调用方提交）。"""
    db.add(
        _build_row(
            actor=actor,
            action=action,
            summary=summary,
            target_type=target_type,
            target_id=target_id,
            target_name=target_name,
            source=source,
            detail=detail,
            success=success,
            error_message=error_message,
            ip=ip,
        )
    )


def audit_log_standalone(
    *,
    actor: Any = None,
    action: str,
    summary: str,
    target_type: str | None = None,
    target_id: Any = None,
    target_name: str | None = None,
    source: str | None = None,
    detail: str | None = None,
    success: bool = True,
    error_message: str | None = None,
    ip: str | None = None,
) -> None:
    """在独立 Session 中写入一条审计并提交（供请求上下文之外的运行时使用）。"""
    from app.db.session import SessionLocal

    try:
        with SessionLocal() as db:
            audit_log(
                db,
                actor=actor,
                action=action,
                summary=summary,
                target_type=target_type,
                target_id=target_id,
                target_name=target_name,
                source=source,
                detail=detail,
                success=success,
                error_message=error_message,
                ip=ip,
            )
            db.commit()
    except Exception as exc:  # 审计失败绝不影响主流程
        logger.warning("写入审计日志失败 action=%s err=%s", action, str(exc) or type(exc).__name__)


def actor_for_source(actor: Any, source: str | None) -> Any:
    """运行时兜底：未显式传 actor 时，按 source 选用对应系统操作方。"""
    if actor is not None:
        return actor
    return _SOURCE_ACTOR.get(source or "", AUTO_ACTOR)


class _UserActor:
    """轻量用户操作方：仅有 user_id/username（如流式 worker 中无 ORM 对象时）。"""

    def __init__(self, user_id: int | None, username: str | None) -> None:
        self.id = user_id
        self.username = username


def user_actor(user_id: int | None, username: str | None = None) -> _UserActor:
    return _UserActor(user_id, username)


# ==================== 兼容旧接口 ====================
def write_audit_log(
    db: Session,
    *,
    actor_user_id: int | None,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,  # v2 已不再持久化，保留形参兼容旧调用
    success: bool = True,
    detail: str | None = None,
) -> None:
    actor_username: str | None = None
    if actor_user_id is not None:
        try:
            from app.models.user import User

            user = db.get(User, actor_user_id)
            if user is not None:
                actor_username = getattr(user, "username", None)
        except Exception:
            actor_username = None

    label = action_label(action)
    summary = label
    if target_id:
        summary = f"{label}（{target_type or ''} #{target_id}）" if target_type else f"{label} #{target_id}"
    if not success:
        summary = f"{summary}（失败）"

    db.add(
        AuditLog(
            actor_type="user",
            actor_user_id=actor_user_id,
            actor_username=actor_username,
            source=None,
            category=category_of(action),
            action=action,
            target_type=target_type,
            target_id=(None if target_id is None else str(target_id)),
            target_name=None,
            summary=summary,
            detail=_truncate_detail(detail),
            ip=ip,
            success=bool(success),
            error_message=(None if success else (detail or None)),
        )
    )
