"""MCP server exposing the Czech ISDS Data Box system (datovka) as tools."""

from .server import main, mcp

__all__ = ["mcp", "main"]
