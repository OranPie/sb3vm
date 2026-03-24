from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from sb3vm.log import get_logger


_LOGGER = get_logger(__name__)


@dataclass
class Trigger:
    kind: str
    value: str | None = None
    threshold: Any = None


@dataclass
class Expr:
    kind: str
    value: Any = None
    args: list["Expr"] = field(default_factory=list)


@dataclass
class Stmt:
    kind: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProcedureDefinition:
    target_name: str
    proccode: str
    argument_ids: list[str] = field(default_factory=list)
    argument_names: list[str] = field(default_factory=list)
    argument_defaults: list[Any] = field(default_factory=list)
    warp: bool = False
    body: list[Stmt] = field(default_factory=list)
    block_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target_name,
            "proccode": self.proccode,
            "argument_ids": list(self.argument_ids),
            "argument_names": list(self.argument_names),
            "argument_defaults": list(self.argument_defaults),
            "warp": self.warp,
            "block_id": self.block_id,
        }


@dataclass
class UnsupportedDiagnostic:
    target_name: str
    trigger_kind: str
    trigger_value: str | None
    node_kind: str
    opcode: str
    reason: str
    block_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target_name,
            "trigger": self.trigger_kind,
            "value": self.trigger_value,
            "node_kind": self.node_kind,
            "opcode": self.opcode,
            "reason": self.reason,
            "block_id": self.block_id,
        }


@dataclass
class RuntimeDiagnostic:
    kind: str
    message: str
    target_name: str
    thread_id: int | None = None
    proccode: str | None = None
    depth: int | None = None
    instance_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "message": self.message,
            "target": self.target_name,
            "thread_id": self.thread_id,
            "proccode": self.proccode,
            "depth": self.depth,
            "instance_id": self.instance_id,
        }


@dataclass
class AskState:
    prompt: str


@dataclass
class Script:
    target_name: str
    trigger: Trigger
    body: list[Stmt]
    supported: bool = True
    unsupported_details: list[UnsupportedDiagnostic] = field(default_factory=list)

