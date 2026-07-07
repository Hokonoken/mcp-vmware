# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Hokonoken

"""Shared FastMCP instance and role-filtered tool registration."""

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
    """Register an MCP tool only if the current role covers its group.

    A tool that is not covered stays a plain function: it does not appear in
    tools/list, the LLM never sees it.
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
