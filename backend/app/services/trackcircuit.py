"""轨道电路业务规则：状态流转、参数校验与调整台账都收在这里。

口径约定：
- ``status``（电路状态）是唯一权威结论，列表与详情都从它派生，避免两边对不上；
- 分路灵敏度低于阈值即判「分路不良」，优先级高于电平判断；
- 「记录偏移」只置偏移标记，「调整参数」在校验通过后清偏移并同步刷新电路状态；
- 调整台账按区段编号归并，同一区段重复调整只保留最近一条。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "trackcircuit"
REQUIRED_FIELDS = ["区段编号", "所属区间", "载频类型"]

# 电路状态（权威结论）与调整状态（电平是否需要/已经调整）分开描述
STATUS_GOOD = "调整良好"
STATUS_OFFSET = "参数偏移"
STATUS_SHUNT_BAD = "分路不良"
STATUS_DISABLED = "已停用"
STATUS_ORDER = [STATUS_GOOD, STATUS_OFFSET, STATUS_SHUNT_BAD, STATUS_DISABLED]

# 分路灵敏度允许下限（Ω）：低于该值判定为分路不良，刷新后该值原样保留
SHUNT_SENSITIVITY_MIN = 0.15

# 发送/接收电平允许范围；越界时按电平名称给出说明
LEVEL_LIMITS = {
    "发送电平": (100.0, 140.0),  # V
    "接收电平": (240.0, 1000.0),  # mV
}
DEFAULT_LEVELS = {"发送电平": 120.0, "接收电平": 500.0}
DEFAULT_SHUNT_SENSITIVITY = 0.20  # Ω

ACTION_OFFSET = "记录偏移"
ACTION_ADJUST = "调整参数"
ACTION_DISABLE = "办理停用"
ACTION_RULES = {ACTION_OFFSET: STATUS_OFFSET, ACTION_ADJUST: STATUS_GOOD, ACTION_DISABLE: STATUS_DISABLED}
NEGATIVE_ACTIONS = [ACTION_OFFSET, ACTION_DISABLE]


def _to_float(value: Any) -> float | None:
    """把入参转成数值；空值或无法解析时返回 None，由调用方决定口径。"""
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class TrackcircuitService:
    def __init__(self) -> None:
        # 调整台账：区段编号 -> 最近一次调整记录；同一区段重复提交只保留最近一条
        self._adjust_ledger: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------ 读取
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = [self._snapshot(row) for row in store.rows(MODULE)]
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("区段编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        return self._snapshot(entry)

    def list_adjustments(self) -> list[dict[str, Any]]:
        """调整台账：每个区段只暴露最近一条调整记录。"""
        return [dict(record) for record in self._adjust_ledger.values()]

    def get_adjustment(self, section_code: str) -> dict[str, Any] | None:
        record = self._adjust_ledger.get(section_code)
        return dict(record) if record is not None else None

    # ------------------------------------------------------------------ 登记
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        # 登记时给一组合规的默认电气参数；分路灵敏度默认高于分路不良阈值
        entry["发送电平"] = DEFAULT_LEVELS["发送电平"]
        entry["接收电平"] = DEFAULT_LEVELS["接收电平"]
        entry["分路灵敏度"] = DEFAULT_SHUNT_SENSITIVITY
        entry["offset"] = False
        entry["status"] = STATUS_GOOD
        entry["pending"] = True
        entry["abnormal"] = False
        self._refresh(entry)
        rows.append(entry)
        return self._snapshot(entry), []

    # ------------------------------------------------------------------ 动作
    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"轨道电路 {entry_id} 不存在或已归档，无法读取区段数据"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于轨道电路可执行范围"
        values = values or {}

        # 已停用区段不再参与任何参数调整类动作
        if entry.get("status") == STATUS_DISABLED:
            return None, f"区段 {entry.get('区段编号')} 已停用，不再参与参数调整；如需调整请先办理启用"

        if action == ACTION_OFFSET:
            return self._mark_offset(entry)
        if action == ACTION_ADJUST:
            return self._adjust(entry, values)
        return self._disable(entry)

    def _mark_offset(self, entry: dict[str, Any]) -> tuple[dict[str, Any], str]:
        """记录偏移：置偏移标记，调整状态与电路状态同步落到「参数偏移」。"""
        entry["offset"] = True
        self._refresh(entry)
        return self._snapshot(entry), f"区段 {entry.get('区段编号')} 已记录参数偏移"

    def _disable(self, entry: dict[str, Any]) -> tuple[dict[str, Any], str]:
        """办理停用：电路状态与调整状态统一落到「已停用」，退出待处理。"""
        entry["offset"] = False
        entry["status"] = STATUS_DISABLED
        entry["调整状态"] = STATUS_DISABLED
        entry["电路状态"] = STATUS_DISABLED
        entry["pending"] = False
        entry["abnormal"] = True
        return self._snapshot(entry), f"区段 {entry.get('区段编号')} 已办理停用"

    def _adjust(self, entry: dict[str, Any], values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """调整参数：先校验电平范围，再按正确字段落库，并归并调整台账。"""
        section_code = str(entry.get("区段编号"))

        # 参数超出允许范围时拒绝保存，并指出是哪个电平越界
        new_levels: dict[str, float] = {}
        for level_name, (low, high) in LEVEL_LIMITS.items():
            raw = values.get(level_name, entry.get(level_name))
            number = _to_float(raw)
            if number is None:
                return None, f"{level_name}缺失或不是有效数值，无法保存调整参数"
            if not low <= number <= high:
                unit = "V" if level_name == "发送电平" else "mV"
                return None, f"{level_name}越界：实测 {number:g}{unit}，允许范围 {low:g}~{high:g}{unit}，本次调整未保存"
            new_levels[level_name] = number

        # 发送电平、接收电平按各自字段落库，避免错位互换
        entry["发送电平"] = new_levels["发送电平"]
        entry["接收电平"] = new_levels["接收电平"]
        # 分路灵敏度不随参数调整改动：未提交就保留原值，刷新后仍是原值
        if "分路灵敏度" in values:
            sensitivity = _to_float(values.get("分路灵敏度"))
            if sensitivity is not None:
                entry["分路灵敏度"] = sensitivity

        entry["offset"] = False
        self._refresh(entry)

        # 同一区段重复调整：按区段编号归并，只保留最近一条，台账里不留残留
        self._adjust_ledger[section_code] = {
            "区段编号": section_code,
            "发送电平": entry["发送电平"],
            "接收电平": entry["接收电平"],
            "分路灵敏度": entry["分路灵敏度"],
            "调整时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        message = f"区段 {section_code} 参数调整成功，电路状态已同步为「{entry['status']}」"
        return self._snapshot(entry), message

    # ------------------------------------------------------------------ 口径
    def _refresh(self, entry: dict[str, Any]) -> None:
        """根据偏移标记、电平范围与分路灵敏度统一推导状态。

        列表快照与单条详情都走这一份推导，保证两个口径的结论一致。
        """
        if entry.get("status") == STATUS_DISABLED:
            entry["调整状态"] = STATUS_DISABLED
            entry["电路状态"] = STATUS_DISABLED
            return

        sensitivity = _to_float(entry.get("分路灵敏度"))
        # 分路灵敏度过低时，即使电平良好也要判分路不良，不能再显示成调整良好
        if sensitivity is not None and sensitivity < SHUNT_SENSITIVITY_MIN:
            status = STATUS_SHUNT_BAD
        elif entry.get("offset"):
            status = STATUS_OFFSET
        elif self._level_out_of_range(entry):
            status = STATUS_OFFSET
        else:
            status = STATUS_GOOD

        entry["status"] = status
        entry["调整状态"] = STATUS_OFFSET if status == STATUS_OFFSET else STATUS_GOOD
        entry["电路状态"] = status
        entry["pending"] = status != STATUS_GOOD
        entry["abnormal"] = status in (STATUS_OFFSET, STATUS_SHUNT_BAD)

    def _level_out_of_range(self, entry: dict[str, Any]) -> bool:
        for level_name, (low, high) in LEVEL_LIMITS.items():
            number = _to_float(entry.get(level_name))
            if number is None or not low <= number <= high:
                return True
        return False

    def _snapshot(self, entry: dict[str, Any]) -> dict[str, Any]:
        """输出前先刷新派生字段，保证列表与单条详情结论一致。"""
        self._refresh(entry)
        return dict(entry)
