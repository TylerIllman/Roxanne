from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict


class ToolExecutionError(Exception):
    pass


class BaseTool(ABC):
    name: str = ""
    description: str = ""
    input_schema: Dict[str, Any] = {}

    def anthropic_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }

    @abstractmethod
    async def invoke(self, payload: Dict[str, Any]) -> Any:
        raise NotImplementedError

