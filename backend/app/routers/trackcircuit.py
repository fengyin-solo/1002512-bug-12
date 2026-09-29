"""轨道电路接口：维护轨道电路，覆盖记录偏移、调整参数、办理停用等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.trackcircuit import DISABLED, OFFSET, POOR_SHUNT, GOOD, TrackcircuitService

router = APIRouter(prefix="/api/trackcircuit", tags=["轨道电路"])

service = TrackcircuitService()

LIST_FIELDS = ["区段编号", "所属区间", "载频类型", "发送电平", "接收电平", "调整状态", "分路灵敏度", "电路状态"]
STATUSES = [GOOD, OFFSET, POOR_SHUNT, DISABLED]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按区段编号检索"),
    status: str | None = Query(default=None, description="调整良好、参数偏移、分路不良、已停用"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按区段编号与状态过滤轨道电路列表；没有数据时返回空页，不报错。"""
    if page < 1 or size < 1:
        raise HTTPException(status_code=400, detail="分页参数必须是正整数")
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    if status and status not in STATUSES:
        raise HTTPException(status_code=400, detail=f"状态「{status}」不支持，可选：{'、'.join(STATUSES)}")
    try:
        items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    except Exception as exc:  # 读取失败要把原因带到前端，而不是返回一个空白页
        raise HTTPException(status_code=500, detail=f"轨道电路列表读取失败：{exc}") from exc
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出轨道电路清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "trackcircuit", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条轨道电路明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"轨道电路 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条轨道电路，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="轨道电路已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条轨道电路执行记录偏移、调整参数、办理停用；不允许的动作会被拦下并说明原因。"""
    values = dict(payload.values or {})
    action = str(values.pop("action", "") or "").strip()
    entry, message = service.run_action(entry_id, action, values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
