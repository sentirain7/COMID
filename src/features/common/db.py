"""Common DB session helpers for feature services."""

import asyncio
from collections.abc import Callable
from typing import TypeVar

from database.connection import session_scope

T = TypeVar("T")


def run_in_session(fn: Callable) -> T:
    """Run callable with a managed DB session and return its result.

    WARNING: This is synchronous. In async endpoints, use
    ``run_in_session_async`` to avoid blocking the event loop.
    """
    with session_scope() as session:
        return fn(session)


async def run_in_session_async(fn: Callable) -> T:
    """Async-safe DB session helper — offloads sync work to threadpool.

    Prevents blocking the uvicorn event loop when called from
    ``async def`` endpoint handlers.
    """
    return await asyncio.to_thread(run_in_session, fn)


def run_in_session_commit(fn: Callable) -> T:
    """Run callable with managed DB session, flush, and let session_scope commit."""
    with session_scope() as session:
        result = fn(session)
        session.flush()
        return result


def with_optional_session(session, fn: Callable) -> T:
    """주입된 세션이 있으면 그대로, 없으면 관리 세션을 열어 실행.

    feature 서비스의 ``session=None`` 주입 패턴(테스트에서 in-memory 세션
    주입, 프로덕션에서는 자체 개설) 보일러플레이트를 단일화한다.
    """
    if session is not None:
        return fn(session)
    return run_in_session(fn)
