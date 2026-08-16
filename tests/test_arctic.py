from __future__ import annotations

import asyncio
from collections.abc import Callable

import httpx
import pytest

from redscrape.arctic import ArcticShiftClient, IncompleteCoverageError
from redscrape.timewindow import TimeWindow


def post(post_id: str, created_utc: float, subreddit: str = "python") -> dict:
    return {
        "id": post_id,
        "created_utc": created_utc,
        "subreddit": subreddit,
        "title": f"post {post_id}",
    }


def client_for(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    retries: int = 3,
    page_size: int = 2,
    empty_confirmations: int = 1,
) -> ArcticShiftClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return ArcticShiftClient(
        http_client=http,
        retries=retries,
        page_size=page_size,
        empty_confirmations=empty_confirmations,
        sleep=lambda _delay: asyncio.sleep(0),
    )


def test_collects_multiple_ascending_pages_and_deduplicates_overlap() -> None:
    calls: list[httpx.Request] = []
    pages = [
        [post("a", 100), post("b", 101)],
        [post("b", 101), post("c", 102)],
        [],
        [],
        [],
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"data": pages[len(calls) - 1]})

    client = client_for(handler)
    result = asyncio.run(client.fetch_subreddit("python", TimeWindow(100, 200)))
    asyncio.run(client.close())

    assert [item["id"] for item in result.posts] == ["a", "b", "c"]
    assert result.complete is True
    assert result.pages == 3
    assert result.oldest == 100
    assert result.newest == 102
    assert calls[0].url.params["sort"] == "asc"
    assert calls[0].url.params["limit"] == "2"
    assert calls[0].url.params["after"] == "99"
    assert calls[1].url.params["after"] == "101"
    assert calls[0].url.params["before"] == "200"


def test_filters_rows_locally_to_half_open_interval() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={"data": [post("too-old", 99), post("at-start", 100), post("inside", 101), post("too-new", 200)]}
            if calls == 1 else {"data": []},
        )

    client = client_for(handler, page_size=10)
    result = asyncio.run(client.fetch_subreddit("python", TimeWindow(100, 200)))
    asyncio.run(client.close())

    assert [item["id"] for item in result.posts] == ["at-start", "inside"]


@pytest.mark.parametrize(
    "row",
    [
        {"created_utc": 100, "subreddit": "python"},
        {"id": "missing-time", "subreddit": "python"},
        {"id": "bad-time", "created_utc": "yesterday", "subreddit": "python"},
    ],
)
def test_malformed_row_fails_closed(row: dict) -> None:
    client = client_for(lambda _request: httpx.Response(200, json={"data": [row]}))

    with pytest.raises(IncompleteCoverageError, match="malformed") as caught:
        asyncio.run(client.fetch_subreddit("python", TimeWindow(100, 200)))
    asyncio.run(client.close())

    assert caught.value.result.complete is False


def test_non_json_or_malformed_payload_fails_closed() -> None:
    client = client_for(
        lambda _request: httpx.Response(
            200, content=b"not-json", headers={"content-type": "text/plain"}
        )
    )

    with pytest.raises(IncompleteCoverageError, match="JSON"):
        asyncio.run(client.fetch_subreddit("python", TimeWindow(100, 200)))
    asyncio.run(client.close())


def test_stalled_pagination_raises_with_partial_result() -> None:
    page = [post("a", 100), post("b", 101)]
    client = client_for(lambda _request: httpx.Response(200, json={"data": page}))

    with pytest.raises(IncompleteCoverageError, match="stalled") as caught:
        asyncio.run(client.fetch_subreddit("python", TimeWindow(100, 200)))
    asyncio.run(client.close())

    assert [item["id"] for item in caught.value.result.posts] == ["a", "b"]
    assert caught.value.result.pages == 2
    assert caught.value.result.complete is False


@pytest.mark.parametrize("status", [422, 429, 500, 502, 503, 504])
def test_retryable_status_eventually_succeeds(status: int) -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(status, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"data": []})

    client = client_for(handler)
    result = asyncio.run(client.fetch_subreddit("python", TimeWindow(100, 200)))
    asyncio.run(client.close())

    assert result.complete is True
    assert attempts == 2


def test_retry_exhaustion_is_an_explicit_partial_failure() -> None:
    client = client_for(
        lambda _request: httpx.Response(429, headers={"Retry-After": "0"}), retries=2
    )

    with pytest.raises(IncompleteCoverageError, match="retries") as caught:
        asyncio.run(client.fetch_subreddit("python", TimeWindow(100, 200)))
    asyncio.run(client.close())

    assert caught.value.result.complete is False
    assert caught.value.result.posts == ()


def test_transient_empty_and_short_pages_do_not_prematurely_end_collection() -> None:
    pages = [
        [post("a", 100), post("b", 101)],
        [],
        [post("c", 102)],
        [],
        [],
        [],
    ]
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        response = httpx.Response(200, json={"data": pages[calls]})
        calls += 1
        return response

    client = client_for(handler, empty_confirmations=3)
    result = asyncio.run(client.fetch_subreddit("python", TimeWindow(100, 200)))
    asyncio.run(client.close())

    assert [item["id"] for item in result.posts] == ["a", "b", "c"]
    assert calls == 6
    assert result.complete is True


def test_full_page_reaching_upper_bound_is_not_declared_complete() -> None:
    page = [post("inside", 199), post("at-before", 200)]
    client = client_for(lambda _request: httpx.Response(200, json={"data": page}))

    with pytest.raises(IncompleteCoverageError, match="final short"):
        asyncio.run(client.fetch_subreddit("python", TimeWindow(100, 200)))
    asyncio.run(client.close())


def test_non_ascending_page_fails_closed() -> None:
    page = [post("later", 101), post("earlier", 100)]
    client = client_for(lambda _request: httpx.Response(200, json={"data": page}))

    with pytest.raises(IncompleteCoverageError, match="ascending"):
        asyncio.run(client.fetch_subreddit("python", TimeWindow(100, 200)))
    asyncio.run(client.close())


def test_cross_subreddit_row_fails_closed() -> None:
    client = client_for(
        lambda _request: httpx.Response(
            200, json={"data": [post("wrong-sub", 100, "golang")]}
        )
    )

    with pytest.raises(IncompleteCoverageError, match="subreddit"):
        asyncio.run(client.fetch_subreddit("python", TimeWindow(100, 200)))
    asyncio.run(client.close())


def test_retry_after_http_date_is_honored() -> None:
    delays: list[float] = []
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(
                429, headers={"Retry-After": "Thu, 01 Jan 1970 00:00:05 GMT"}
            )
        return httpx.Response(200, json={"data": []})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    client = ArcticShiftClient(
        http_client=http,
        retries=2,
        page_size=2,
        empty_confirmations=1,
        sleep=record_sleep,
        now=lambda: 0.0,
    )
    asyncio.run(client.fetch_subreddit("python", TimeWindow(100, 200)))
    asyncio.run(client.close())

    assert delays == [5.0]


def test_page_persistence_failure_returns_accumulated_partial_result() -> None:
    client = client_for(
        lambda _request: httpx.Response(200, json={"data": [post("a", 100)]})
    )

    def fail_persistence(_posts) -> None:
        raise RuntimeError("disk full")

    with pytest.raises(IncompleteCoverageError, match="persist") as caught:
        asyncio.run(
            client.fetch_subreddit(
                "python", TimeWindow(100, 200), on_page=fail_persistence
            )
        )
    asyncio.run(client.close())

    assert [item["id"] for item in caught.value.result.posts] == ["a"]
    assert caught.value.result.complete is False
