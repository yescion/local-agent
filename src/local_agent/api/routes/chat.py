"""Chat API routes with SSE streaming."""



from __future__ import annotations



import asyncio

import json

from collections.abc import AsyncIterator



from fastapi import APIRouter, Depends, HTTPException, Request

from fastapi.responses import StreamingResponse



from local_agent.agent.exceptions import ChatTurnCancelled

from local_agent.agent.manager import AgentManager

from local_agent.api.deps import get_agent_manager

from local_agent.api.schemas import ChatRequest, ChatResponse

from local_agent.cli.context import get_session

from local_agent.storage.repositories.message_repo import ThreadRepository



router = APIRouter(prefix="/api/v1", tags=["chat"])





def _resolve_thread_id(manager: AgentManager, agent_id: str, thread_id: str | None) -> str:

    if thread_id:

        thread = manager.get_thread(thread_id)

        if not thread or thread.agent_id != agent_id:

            raise HTTPException(404, "Thread not found")

        return thread_id

    threads = manager.list_threads(agent_id)

    if threads:

        return threads[0].id

    return manager.create_thread(agent_id).id





@router.post("/agents/{agent_id}/chat", response_model=ChatResponse)

async def chat_sync(

    agent_id: str,

    body: ChatRequest,

    manager: AgentManager = Depends(get_agent_manager),

):

    if not manager.get_agent(agent_id):

        raise HTTPException(404, "Agent not found")

    if not body.message.strip() and not body.attachment_ids and not body.reference_ids:

        raise HTTPException(400, "消息、附件和文件引用不能同时为空")

    thread_id = _resolve_thread_id(manager, agent_id, body.thread_id)

    content = await manager.chat(

        agent_id,

        body.message,

        thread_id=thread_id,

        stream=False,

        attachment_ids=body.attachment_ids,

        reference_ids=body.reference_ids,

    )

    session = get_session()

    try:

        ThreadRepository(session).touch(thread_id)

    finally:

        session.close()

    return ChatResponse(content=content, thread_id=thread_id)





@router.post("/threads/{thread_id}/chat/cancel")

async def cancel_chat(

    thread_id: str,

    manager: AgentManager = Depends(get_agent_manager),

):

    if not manager.get_thread(thread_id):

        raise HTTPException(404, "Thread not found")

    if not manager.cancel_chat(thread_id):

        raise HTTPException(409, "当前会话没有进行中的对话")

    return {"ok": True, "thread_id": thread_id}





@router.post("/agents/{agent_id}/chat/stream")

async def chat_stream(

    agent_id: str,

    body: ChatRequest,

    request: Request,

    manager: AgentManager = Depends(get_agent_manager),

):

    if not manager.get_agent(agent_id):

        raise HTTPException(404, "Agent not found")

    if not body.message.strip() and not body.attachment_ids and not body.reference_ids:

        raise HTTPException(400, "消息、附件和文件引用不能同时为空")

    thread_id = _resolve_thread_id(manager, agent_id, body.thread_id)



    queue: asyncio.Queue[tuple[str, dict] | None] = asyncio.Queue()



    def on_event(event: str, data: dict) -> None:

        queue.put_nowait((event, data))



    async def run_chat() -> None:

        try:

            await manager.chat(

                agent_id,

                body.message,

                thread_id=thread_id,

                stream=True,

                on_stream_event=on_event,

                attachment_ids=body.attachment_ids,

                reference_ids=body.reference_ids,

            )

            session = get_session()

            try:

                ThreadRepository(session).touch(thread_id)

            except Exception:

                pass

            finally:

                session.close()

        except (ChatTurnCancelled, asyncio.CancelledError):

            pass

        except Exception as exc:

            queue.put_nowait(("error", {"message": str(exc)}))

        finally:

            queue.put_nowait(None)



    # Comment padding encourages proxies / buffers to flush each SSE frame promptly.

    _SSE_PAD = ": " + " " * 2048 + "\n\n"



    async def event_generator() -> AsyncIterator[str]:

        task = asyncio.create_task(run_chat())

        try:

            yield f"event: meta\ndata: {json.dumps({'thread_id': thread_id}, ensure_ascii=False)}\n\n{_SSE_PAD}"

            while True:

                if await request.is_disconnected():

                    manager.cancel_chat(thread_id)

                    break

                try:

                    item = await asyncio.wait_for(queue.get(), timeout=0.25)

                except asyncio.TimeoutError:

                    if task.done():

                        while not queue.empty():

                            pending = queue.get_nowait()

                            if pending is None:

                                break

                            event, data = pending

                            payload = json.dumps(data, ensure_ascii=False)

                            yield f"event: {event}\ndata: {payload}\n\n{_SSE_PAD}"

                        break

                    continue

                if item is None:

                    break

                event, data = item

                payload = json.dumps(data, ensure_ascii=False)

                yield f"event: {event}\ndata: {payload}\n\n{_SSE_PAD}"

                await asyncio.sleep(0)

        finally:

            if not task.done():

                manager.cancel_chat(thread_id)

            await asyncio.gather(task, return_exceptions=True)



    return StreamingResponse(

        event_generator(),

        media_type="text/event-stream",

        headers={

            "Cache-Control": "no-cache",

            "Connection": "keep-alive",

            "X-Accel-Buffering": "no",

        },

    )

