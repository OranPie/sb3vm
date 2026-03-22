from __future__ import annotations

from dataclasses import dataclass
from sb3vm.log import get_logger


_LOGGER = get_logger(__name__)


class Sb3VmError(Exception):
    pass


@dataclass(slots=True)
class DiagnosticLocation:
    target_name: str | None = None
    block_id: str | None = None
    reference: str | None = None


class ProjectValidationError(Sb3VmError):
    def __init__(
        self,
        message: str,
        *,
        target_name: str | None = None,
        block_id: str | None = None,
        reference: str | None = None,
    ) -> None:
        super().__init__(message)
        self.location = DiagnosticLocation(
            target_name=target_name,
            block_id=block_id,
            reference=reference,
        )

    def __str__(self) -> str:
        parts = [super().__str__()]
        if self.location.target_name:
            parts.append(f"target={self.location.target_name}")
        if self.location.block_id:
            parts.append(f"block={self.location.block_id}")
        if self.location.reference:
            parts.append(f"reference={self.location.reference}")
        return " | ".join(parts)

class UnsupportedOpcodeError(Sb3VmError):
    pass

