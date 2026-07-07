"""Instance FastMCP partagee et enregistrement des outils filtre par role."""

from collections.abc import Callable
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .roles import group_allowed

mcp = FastMCP("vmware_mcp")


def tool(
    name: str,
    title: str,
    *,
    group: str,
    read: bool = False,
    destructive: bool = False,
    idempotent: bool = False,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Enregistre un outil MCP seulement si le role courant couvre son groupe.

    Un outil non couvert reste une simple fonction : il n'apparait pas dans
    tools/list, le LLM ne le voit jamais.
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        if not group_allowed(group):
            return fn
        annotations = ToolAnnotations(
            title=title,
            readOnlyHint=read,
            destructiveHint=destructive,
            idempotentHint=idempotent,
            openWorldHint=True,
        )
        return mcp.tool(name=name, annotations=annotations)(fn)

    return decorator
