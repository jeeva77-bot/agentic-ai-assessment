"""Per-user knowledge-base management and observability tools."""
import asyncio
import time

from langchain.tools import ToolRuntime
from langchain_core.tools import ToolException, tool
from opentelemetry import metrics

from app.context import Ctx
from app.errors import to_tool_exception
from app.kb import files
from app.kb.pipeline import ingest_file
from app.kb.store import KnowledgeBase
from app.telemetry import log

_meter = metrics.get_meter("agent")
KBSTATS_CALLS = _meter.create_counter("kbstats.calls", unit="1")
OUTLINE_CALLS = _meter.create_counter("outline.calls", unit="1")


def _unknown(name: str, docs: list[dict]) -> ToolException:
    names = ", ".join(f"'{d['filename']}'" for d in docs) or "(none)"
    return ToolException(f"ERROR[UNKNOWN_DOCUMENT]: No document matches '{name}'. Your documents: {names}. Next step: use an exact name from the knowledge-base list.")


def build_custom_tools(kb: KnowledgeBase) -> list:
    @tool
    async def kb_stats(runtime: ToolRuntime[Ctx], top_keywords: int = 5) -> str:
        """Show counts and common keywords in the user's knowledge base.

        Args:
            top_keywords: Number of keywords to show (1 to 20).
        """
        started, status = time.perf_counter(), "ok"
        try:
            if not 1 <= top_keywords <= 20:
                raise ToolException("ERROR[INVALID_INPUT]: top_keywords must be between 1 and 20. Next step: choose a value from 1 to 20.")
            user_id = runtime.context.user_id or runtime.context.session_id
            stats = await asyncio.to_thread(kb.stats, user_id)
            if not stats["documents"]:
                return "The knowledge base is empty."
            keys = ", ".join(stats["keywords"][:top_keywords])
            return f"{stats['documents']} documents, {stats['sections']} sections, {stats['chunks']} chunks. Top keywords: {keys}."
        except Exception as exc:
            status = "error"
            if isinstance(exc, ToolException):
                raise
            raise to_tool_exception(exc) from exc
        finally:
            KBSTATS_CALLS.add(1, {"status": status})
            log.info("kb_stats_done", tool="kb_stats", status=status, duration_ms=int((time.perf_counter()-started)*1000))

    @tool
    async def document_outline(doc_name: str, runtime: ToolRuntime[Ctx]) -> str:
        """Show the section structure of a document. Use when asked how a document is organised or where a topic appears.

        Args:
            doc_name: Exact or recognisable document filename from the knowledge-base list.
        """
        started, status, count = time.perf_counter(), "ok", 0
        try:
            user_id = runtime.context.user_id or runtime.context.session_id
            docs = await asyncio.to_thread(kb.documents, user_id)
            exact = await asyncio.to_thread(kb.resolve_doc_name, user_id, doc_name)
            if not exact:
                raise _unknown(doc_name, docs)
            doc = next(d for d in docs if d["filename"] == exact)
            sections = await asyncio.to_thread(kb.outline, user_id, doc["doc_id"])
            count = len(sections)
            lines = [f"Outline of '{exact}' ({count} sections):"]
            for i, section in enumerate(sections, 1):
                page_start, page_end = section.get("page_start"), section.get("page_end")
                page = ""
                if page_start is not None:
                    page = f" (p.{page_start}-{page_end})" if page_end != page_start else f" (p.{page_start})"
                lines.append(f"{i}. [L{section.get('level', 1)}] {section['heading']}{page}: {section.get('summary', '')}")
            return "\n".join(lines)
        except Exception as exc:
            status = "error"
            if isinstance(exc, ToolException):
                raise
            raise to_tool_exception(exc) from exc
        finally:
            OUTLINE_CALLS.add(1, {"status": status})
            log.info("document_outline_done", tool="document_outline", status=status,
                     duration_ms=int((time.perf_counter()-started)*1000), sections=count)

    @tool
    async def delete_document(doc_name: str, runtime: ToolRuntime[Ctx]) -> str:
        """Delete one of the user's indexed documents.

        Args:
            doc_name: Document filename from the knowledge-base list.
        """
        user_id = runtime.context.user_id or runtime.context.session_id
        docs = await asyncio.to_thread(kb.documents, user_id)
        exact = await asyncio.to_thread(kb.resolve_doc_name, user_id, doc_name)
        if not exact:
            raise _unknown(doc_name, docs)
        doc = next(d for d in docs if d["filename"] == exact)
        await asyncio.to_thread(kb.delete_document, user_id, doc["doc_id"])
        left = await asyncio.to_thread(kb.documents, user_id)
        return f"Deleted '{exact}'. {len(left)} documents left."

    @tool
    async def update_document(doc_name: str, source: str, runtime: ToolRuntime[Ctx]) -> str:
        """Replace an indexed document with a newly uploaded file. Ingest first; preserve the old version if ingestion fails.

        Args:
            doc_name: Existing document filename to replace.
            source: file_id from the new upload.
        """
        user_id = runtime.context.user_id or runtime.context.session_id
        docs = await asyncio.to_thread(kb.documents, user_id)
        exact = await asyncio.to_thread(kb.resolve_doc_name, user_id, doc_name)
        if not exact:
            raise _unknown(doc_name, docs)
        old = next(d for d in docs if d["filename"] == exact)
        try:
            path, _uploaded_name = files.resolve(runtime.context.session_id, source.strip())
            result, existing = await ingest_file(kb, user_id, path, exact, runtime.config)
        except Exception as exc:
            raise to_tool_exception(exc) from exc
        if existing:
            return f"'{exact}' is already up to date."
        await asyncio.to_thread(kb.delete_document, user_id, old["doc_id"])
        return f"Updated '{exact}': {len(result.sections)} sections, {result.n_chunks} chunks."

    tools = [kb_stats, document_outline, delete_document, update_document]
    for item in tools:
        item.handle_tool_error = True
    return tools
