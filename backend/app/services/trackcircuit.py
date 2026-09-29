"""轨道电路业务规则：状态判定、参数校验、停用管控与调整台账去重。

状态口径在列表与明细之间保持一致，统一由 ``derive_status`` 计算：
先看分路灵敏度（分路不良优先），再看发送/接收电平是否偏移，
已停用的区段始终保持「已停用」，不再参与参数调整等动作。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "trackcircuit"
REQUIRED_FIELDS = ["区段编号", "所属区间", "载频类型"]

GOOD = "调整良好"
OFFSET = "参数偏移"
POOR_SHUNT = "分路不良"
DISABLED = "已停用"
STATUS_ORDER = [GOOD, OFFSET, POOR_SHUNT, DISABLED]

# 发送/接收电平允许范围（单位 V），超出范围不允许保存
TX_RANGE = (40.0, 160.0)
RX_RANGE = (0.2, 5.0)

# 接收电平偏离目标窗口即视为参数偏移（区间轨道电路典型调整窗口）
RX_NOMINAL = (1.8, 2.4)
# 分路灵敏度低于该门限（Ω）判定为分路不良
SHUNT_MIN = 0.15


def _to_float(value: Any) -> float | None:
    """把「2.0」「2.0V」这类输入解析成数字；空值或无法解析时返回 None。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for suffix in ("V", "v", "Ω", "欧"):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    try:
        return float(text)
    except ValueError:
        return None


def derive_status(
    tx: float | None,
    rx: float | None,
    shunt: float | None,
    *,
    disabled: bool = False,
) -> str:
    """按统一口径推导电路状态，列表与单条明细都走这里，避免结论对不上。"""
    if disabled:
        return DISABLED
    if shunt is not None and shunt < SHUNT_MIN:
        return POOR_SHUNT
    if tx is not None and not (TX_RANGE[0] <= tx <= TX_RANGE[1]):
        return OFFSET
    if rx is not None and not (RX_NOMINAL[0] <= rx <= RX_NOMINAL[1]):
        return OFFSET
    return GOOD


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class TrackcircuitService:
    # ---- 读取 ----------------------------------------------------------
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("区段编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [self._present(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        if row is None:
            return None
        detail = self._present(row)
        detail["调整台账"] = [dict(item) for item in row.get("adjustments", [])]
        return detail

    # ---- 登记 ----------------------------------------------------------
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        # 登记时的电气特性按提交内容落库，未填的给标准值，状态由统一口径推导
        tx = _to_float(values.get("发送电平"))
        rx = _to_float(values.get("接收电平"))
        shunt = _to_float(values.get("分路灵敏度"))
        entry["发送电平"] = tx if tx is not None else 100.0
        entry["接收电平"] = rx if rx is not None else 2.0
        entry["分路灵敏度"] = shunt if shunt is not None else 0.25
        entry["调整状态"] = "未调整"
        entry["adjustments"] = []
        self._sync_status(entry, "登记")
        rows.append(entry)
        return self._present(entry), []

    # ---- 动作 ----------------------------------------------------------
    def run_action(
        self, entry_id: int, action: str, values: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"轨道电路 {entry_id} 不存在或已归档"
        if action not in ("记录偏移", "调整参数", "办理停用"):
            return None, f"动作「{action}」不属于轨道电路可执行范围"
        if entry["status"] == DISABLED:
            return None, "区段已停用，不再参与参数调整与记录偏移"

        if action == "记录偏移":
            # 偏移只改调整状态：参数被现场动过、需要重新调整；电路状态由实测参数重新判定
            entry["调整状态"] = "已偏移待调整"
            self._sync_status(entry, action)
            return self._present(entry), "已记录参数偏移，等待重新调整"

        if action == "办理停用":
            entry["status"] = DISABLED
            entry["电路状态"] = DISABLED
            entry["调整状态"] = "已停用"
            entry["pending"] = False
            entry["abnormal"] = False
            return self._present(entry), "区段已办理停用"

        # 调整参数：先校验电平范围，越界直接拒绝并指明是哪个电平
        values = values or {}
        tx = _to_float(values.get("发送电平"))
        rx = _to_float(values.get("接收电平"))
        if tx is None or rx is None:
            return None, "发送电平和接收电平都必须填写为数字后才能调整"
        invalid: list[str] = []
        if not (TX_RANGE[0] <= tx <= TX_RANGE[1]):
            invalid.append(f"发送电平 {tx:g}V 超出允许范围 {TX_RANGE[0]:g}V~{TX_RANGE[1]:g}V")
        if not (RX_RANGE[0] <= rx <= RX_RANGE[1]):
            invalid.append(f"接收电平 {rx:g}V 超出允许范围 {RX_RANGE[0]:g}V~{RX_RANGE[1]:g}V")
        if invalid:
            return None, "；".join(invalid)

        entry["发送电平"] = tx
        entry["接收电平"] = rx
        # 分路灵敏度不在本次调整范围内，沿用原值，刷新后仍保留
        entry["调整状态"] = "已调整"
        self._record_adjustment(entry, tx, rx)
        self._sync_status(entry, action)
        message = "调整参数已保存，电路状态已同步更新"
        if entry["status"] == OFFSET:
            message += "，但电平仍偏离标准窗口，区段判定为参数偏移"
        return self._present(entry), message

    # ---- 内部规则 ------------------------------------------------------
    def _record_adjustment(self, entry: dict[str, Any], tx: float, rx: float) -> None:
        """同一次调整（发送/接收电平都没变）重复提交只保留最近一条，不残留重复台账。"""
        ledger = entry.setdefault("adjustments", [])
        if ledger and ledger[-1]["发送电平"] == tx and ledger[-1]["接收电平"] == rx:
            ledger[-1]["时间"] = _now()
            ledger[-1]["重复提交"] = ledger[-1].get("重复提交", 0) + 1
            return
        ledger.append({"时间": _now(), "发送电平": tx, "接收电平": rx})

    def _sync_status(self, entry: dict[str, Any], reason: str) -> None:
        """按统一口径刷新状态，并同步列表/明细共用的字段。"""
        status = derive_status(
            _to_float(entry.get("发送电平")),
            _to_float(entry.get("接收电平")),
            _to_float(entry.get("分路灵敏度")),
            disabled=entry.get("status") == DISABLED,
        )
        entry["status"] = status
        entry["电路状态"] = status
        entry["pending"] = status in (OFFSET, POOR_SHUNT)
        entry["abnormal"] = status in (OFFSET, POOR_SHUNT)
        entry["状态来源"] = reason

    def _present(self, row: dict[str, Any]) -> dict[str, Any]:
        """对外视图：保证「电路状态」与内部状态始终一致，发送/接收电平各归各位。"""
        view = dict(row)
        view["电路状态"] = row.get("status", GOOD)
        view.pop("adjustments", None)
        return view
