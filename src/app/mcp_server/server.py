"""Authenticated MCP tools for private per-user notes and tasks."""
import json
import os
import sys

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from app.mcp_server.taskstore import TaskError, TaskStore
from app.users import UserStore

mcp = FastMCP("tasks", host="0.0.0.0", port=int(os.getenv("MCP_PORT", "9000")))
store = TaskStore()


def current_user_id(ctx: Context) -> str:
    try:
        request = ctx.request_context.request
        header = request.headers.get("authorization", "")
        scheme, token = header.split(" ", 1)
        if scheme.lower() != "bearer" or not token.strip():
            raise ValueError("bad authorization header")
        user = UserStore().user_for_token(token.strip())
    except Exception:
        user = None
    if not user:
        raise ToolError("ERROR[UNAUTHENTICATED]: A valid bearer token is required. Next step: log in and retry.")
    return user["user_id"]


def _call(method, *args):
    try:
        return json.dumps(method(*args), default=str)
    except TaskError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
def add_note(ctx: Context, title: str, body: str) -> str:
    """Save a note for the signed-in user.

    Args:
        title: Short title for the note.
        body: Note content.
    """
    return _call(store.add_note, current_user_id(ctx), title, body)


@mcp.tool()
def list_notes(ctx: Context) -> str:
    """List the signed-in user's saved notes."""
    return _call(store.list_notes, current_user_id(ctx))


@mcp.tool()
def delete_note(ctx: Context, note_id: int) -> str:
    """Delete one of the signed-in user's notes.

    Args:
        note_id: The note id returned by list_notes.
    """
    return _call(store.delete_note, current_user_id(ctx), note_id)


@mcp.tool()
def add_task(ctx: Context, title: str, details: str = "") -> str:
    """Create a task for the signed-in user.

    Args:
        title: Task title.
        details: Optional task details.
    """
    return _call(store.add_task, current_user_id(ctx), title, details)


@mcp.tool()
def list_tasks(ctx: Context, status: str = "") -> str:
    """List tasks, optionally filtered by todo, in_progress, or done.

    Args:
        status: Optional task status filter; leave empty to list all.
    """
    return _call(store.list_tasks, current_user_id(ctx), status)


@mcp.tool()
def set_task_status(ctx: Context, task_id: int, status: str) -> str:
    """Move a task to its next allowed status.

    Args:
        task_id: Task id returned by list_tasks.
        status: todo, in_progress, or done.
    """
    return _call(store.set_task_status, current_user_id(ctx), task_id, status)


@mcp.tool()
def delete_task(ctx: Context, task_id: int) -> str:
    """Delete one of the signed-in user's tasks.

    Args:
        task_id: Task id returned by list_tasks.
    """
    return _call(store.delete_task, current_user_id(ctx), task_id)


@mcp.tool()
def task_summary(ctx: Context) -> str:
    """Summarise the signed-in user's tasks by status."""
    return _call(store.summary, current_user_id(ctx))


if __name__ == "__main__":
    mcp.run(transport="streamable-http" if "--http" in sys.argv else "stdio")
