"""SQLite-backed LangGraph chat memory."""
import os
from contextlib import asynccontextmanager
from pathlib import Path
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

CHECKPOINT_DB = os.getenv("CHECKPOINT_DB", "checkpoints.sqlite")

@asynccontextmanager
async def open_checkpointer():
    path = Path(CHECKPOINT_DB)
    path.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
        yield saver
