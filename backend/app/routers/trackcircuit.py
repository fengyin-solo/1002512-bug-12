"""轨道电路接口：维护轨道电路，覆盖记录偏移、调整参数、办理停用等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.trackcircuit import TrackcircuitService

router = APIRouter(prefix="/api/trackcircuit", tags=["轨道电路"])

service = TrackcircuitService()

LIST_FIELDS = ["区段编号", "所属区间", "载频类型", "发送电平", "接收电平", "调整状态", "分路灵敏度", "电路状态"]
STATUSES = ["调整良好", "参数偏移", "分路不良", "已停用"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按区段编号检索"),
    status: str | None = Query(default=None, description="调整良好、参数偏移、分路不良、已停用"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按区段编号与状态过滤轨道电路列表；没有数据时返回空页，不报错。"""
    if page < 1:
        raise HTTPException(status_code=400, detail="页码必须从 1 开始")
    if size < 1 or size > 200:
        raise HTTPException(status_code=400, detail="每页条数需在 1~200 之间，请缩小分页范围")
    if status and status not in STATUSES:
        raise HTTPException(status_code=400, detail=f"状态「{status}」不支持，可选：{'、'.join(STATUSES)}")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条轨道电路，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="轨道电路已登记", entry=entry)


# 注意：/export、/adjustments 这类固定路径要放在 /{entry_id} 之前，
# 否则会被当成区段编号解析成 int，直接 422，读取失败还说不清原因。
@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出轨道电路清单：返回当前全量数据及调整台账。"""
    items, total = service.list_entries(page=1, size=10000)
    return {
        "module": "trackcircuit",
        "total": total,
        "items": items,
        "调整台账": service.list_adjustments(),
    }


@router.get("/adjustments")
def list_adjustments() -> dict[str, Any]:
    """调整台账：每个区段只保留最近一次调整记录。"""
    records = service.list_adjustments()
    return {"total": len(records), "items": records}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条轨道电路明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"轨道电路 {entry_id} 不存在或已归档，请确认区段编号后重试")
    return entry


@router.get("/{entry_id}/adjustment")
def get_entry_adjustment(entry_id: int) -> dict[str, Any]:
    """读取单条区段最近一次调整记录；没有调整过时明确说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"轨道电路 {entry_id} 不存在或已归档，读取调整记录失败")
    record = service.get_adjustment(str(entry.get("区段编号")))
    if record is None:
        return {"total": 0, "message": f"区段 {entry.get('区段编号')} 暂无调整记录", "item": None}
    return {"total": 1, "item": record}


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条轨道电路执行记录偏移、调整参数、办理停用。

    业务失败（越界、已停用等）以 ok=false 回传可读原因，HTTP 层不抛 500；
    调整参数时电平字段放在 values 里，由服务按字段名校验并落库。
    """
    action = str(payload.values.get("action") or "").strip()
    if not action:
        return ActionResult(ok=False, message="缺少动作名称（action），未执行任何操作")
    entry, message = service.run_action(entry_id, action, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
