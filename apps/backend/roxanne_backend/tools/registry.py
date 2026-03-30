from __future__ import annotations

from typing import Any, Dict, Iterable, List

from roxanne_backend.tools.base import BaseTool


class ToolRegistry:
    def __init__(self, tools: Iterable[BaseTool]) -> None:
        self.tools = {tool.name: tool for tool in tools}

    def schemas(self) -> List[Dict[str, Any]]:
        return [tool.anthropic_schema() for tool in self.tools.values()]

    async def execute(self, name: str, payload: Dict[str, Any]) -> Any:
        tool = self.tools.get(name)
        if tool is None:
            raise KeyError(f"Unknown tool: {name}")
        return await tool.invoke(payload)

