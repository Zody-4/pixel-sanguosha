"""Explicit design/test landing for already-confirmed decisions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DecisionTrace:
    decision_id: str
    matrix_id: str
    authority: str
    design_landing: str
    verification_landing: str
    implementation_stage: str
    status: str


# Stage 1 implements and exercises the scoped game behavior for these decisions.
DECISION_TRACES = (
    DecisionTrace(
        "P-01", "UX-START-01", "docs/project/决策与变更日志.md",
        "docs/product/技术架构与数据契约.md §3.5、§3.8",
        "docs/product/需求规则追踪矩阵.md EXIT-01",
        "阶段1", "自动场景通过；真人整局待用户验收",
    ),
    DecisionTrace(
        "R-01", "RULE-AXE-01", "docs/project/决策与变更日志.md",
        "docs/product/技术架构与数据契约.md §3.4",
        "docs/product/需求规则追踪矩阵.md RULE-AXE-01",
        "阶段1", "自动场景通过；真人整局待用户验收",
    ),
    DecisionTrace(
        "R-02", "RULE-FANJIAN-01", "docs/project/决策与变更日志.md",
        "docs/product/技术架构与数据契约.md §3.1、§3.2、§3.4",
        "docs/product/需求规则追踪矩阵.md RULE-FANJIAN-01",
        "阶段1", "自动场景通过；真人整局待用户验收",
    ),
)

DECISION_TRACE_BY_ID = {trace.decision_id: trace for trace in DECISION_TRACES}
