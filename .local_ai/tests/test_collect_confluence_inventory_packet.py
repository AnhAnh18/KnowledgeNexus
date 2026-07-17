from __future__ import annotations

import base64
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "tools"
    / "collect_confluence_inventory_packet.py"
)
SPEC = importlib.util.spec_from_file_location("m5b0_confluence_probe", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load probe module")
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)


BASE_URL = "https://wiki.private.example"
PAT = "pat-super-secret-123456"
EMAIL = "person.private@example.com"


def make_profile(*, pagination: probe.PaginationProfile | None = None):
    return probe.RequestProfile(
        deployment="data-center",
        confluence_version="9.2",
        api_family="confirmed REST family",
        auth_scheme="bearer_pat",
        root_request=probe.RequestTemplate(
            path_template="/rest/confirmed/content/{root_page_id}",
            query=(("expand", "version,ancestors,metadata.labels"),),
        ),
        inventory_request=probe.RequestTemplate(
            path_template=(
                "/rest/confirmed/content/{root_page_id}/descendant/page"
            ),
            query=(("limit", "{page_size}"),),
        ),
        pagination=pagination
        or probe.PaginationProfile(
            kind="json_next",
            next_pointer="/_links/next",
            mutable_query_parameters=("cursor",),
        ),
    )


def make_config(
    output_dir: Path,
    *,
    max_pages: int = 4,
    pagination: probe.PaginationProfile | None = None,
):
    return probe.ProbeConfig(
        profile=make_profile(pagination=pagination),
        space_key="KNOW",
        root_page_id="123",
        page_size=2,
        max_pages=max_pages,
        timeout_seconds=3.0,
        output_dir=output_dir,
    )


def root_payload() -> dict[str, object]:
    return {
        "id": 123,
        "type": "page",
        "title": "Private Root Title",
        "space": {"key": "KNOW", "name": "Private Space Name"},
        "ancestors": [],
        "version": {
            "number": 7,
            "when": "2026-07-14T12:13:14.123+07:00",
            "by": {"accountId": "account-private", "email": EMAIL},
        },
        "owner": {"id": 987654},
        "body": {
            "storage": {
                "representation": "storage",
                "value": "PRIVATE BODY TEXT",
            }
        },
        "_links": {
            "self": f"{BASE_URL}/rest/confirmed/content/123",
            "webui": "/display/KNOW/Private+Root+Title",
        },
    }


def descendants_page_1() -> dict[str, object]:
    return {
        "results": [
            {
                "id": 124,
                "title": "Private Child One",
                "parentId": 123,
                "ancestors": [
                    {"id": 123, "title": "Private Root Title"},
                ],
                "space": {"key": "KNOW"},
                "labels": [{"name": "private-label"}],
            },
            {
                "id": "125-string",
                "title": "Private Child Two",
                "parentId": 123,
                "ancestors": [{"id": 123}],
            },
        ],
        "limit": 2,
        "_links": {
            "next": (
                "/rest/confirmed/content/123/descendant/page"
                "?cursor=opaque-private-cursor&limit=2"
            )
        },
    }


def descendants_page_2() -> dict[str, object]:
    return {
        "results": [],
        "limit": 2,
        "_links": {"next": None},
    }


class FakeResponse:
    def __init__(
        self,
        payload: object,
        *,
        status: int = 200,
        content_type: str = "application/json; charset=utf-8",
        link: str | None = None,
    ) -> None:
        self.status = status
        self.headers = {"Content-Type": content_type}
        if link is not None:
            self.headers["Link"] = link
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, _limit: int) -> bytes:
        return self._body


class QueueOpener:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request, *, timeout: float):
        self.requests.append((request, timeout))
        if not self.responses:
            raise AssertionError("unexpected request")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def make_observation(
    sequence: int,
    url: str,
    decision: str,
    *,
    link: str | None = None,
) -> probe.RequestObservation:
    return probe.RequestObservation(
        sequence=sequence,
        url=url,
        status=200,
        content_type="application/json",
        link_header=link,
        pagination_decision=decision,
    )


def make_collection(*, three_pages: bool = False) -> probe.CollectionResult:
    root_url = f"{BASE_URL}/rest/confirmed/content/123?expand=version"
    first_url = (
        f"{BASE_URL}/rest/confirmed/content/123/descendant/page?limit=2"
    )
    second_url = (
        f"{BASE_URL}/rest/confirmed/content/123/descendant/page"
        "?cursor=opaque-private-cursor&limit=2"
    )
    pages = [
        probe.HttpResult(
            url=first_url,
            status=200,
            content_type="application/json",
            link_header=None,
            payload=descendants_page_1(),
        ),
        probe.HttpResult(
            url=second_url,
            status=200,
            content_type="application/json",
            link_header=None,
            payload=descendants_page_2(),
        ),
    ]
    observations = [
        make_observation(1, root_url, "root metadata captured; not paginated"),
        make_observation(2, first_url, "followed confirmed next page"),
        make_observation(3, second_url, "next absent or null"),
    ]
    if three_pages:
        pages[1] = probe.HttpResult(
            url=second_url,
            status=200,
            content_type="application/json",
            link_header=None,
            payload={
                "results": [{"id": 126, "title": "Private Third"}],
                "_links": {
                    "next": "/rest/confirmed/content/123/descendant/page?cursor=last"
                },
            },
        )
        last_url = (
            f"{BASE_URL}/rest/confirmed/content/123/descendant/page?cursor=last"
        )
        pages.append(
            probe.HttpResult(
                url=last_url,
                status=200,
                content_type="application/json",
                link_header=None,
                payload={"results": [], "_links": {"next": None}},
            )
        )
        observations[2] = make_observation(
            3, second_url, "followed confirmed next page"
        )
        observations.append(make_observation(4, last_url, "next absent or null"))
    return probe.CollectionResult(
        root=probe.HttpResult(
            url=root_url,
            status=200,
            content_type="application/json",
            link_header=None,
            payload=root_payload(),
        ),
        root_identity=123,
        descendant_pages=tuple(pages),
        observations=tuple(observations),
        pagination_mechanism="JSON next pointer /_links/next",
        next_shapes_observed=("root-relative URL",),
        terminal_condition="/_links/next absent or null",
        pagination_truncated=False,
        terminal_page_observed=True,
    )


def valid_packet_files() -> dict[str, bytes]:
    return {
        "confluence_api_profile.md": b"# profile\n",
        "confluence_request_trace.md": b"# trace\n",
        "root_page_response.sanitized.json": b"{}\n",
        "descendants_page_1.sanitized.json": b"{}\n",
        "sanitization_report.md": b"# report\n",
    }


class SanitizerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.raw_root = root_payload()
        self.raw_page = descendants_page_1()
        self.sanitizer = probe.Sanitizer(
            base_url=BASE_URL,
            root_page_id=123,
            space_key="KNOW",
        )
        self.sanitizer.prime(self.raw_root)
        self.sanitizer.prime(self.raw_page)

    def test_structure_scalar_types_and_body_shape_are_preserved(self) -> None:
        sanitized = self.sanitizer.sanitize(self.raw_root)
        probe._validate_shape(self.raw_root, sanitized)
        self.assertIs(type(sanitized["id"]), int)
        self.assertIs(type(sanitized["version"]["number"]), int)
        self.assertIs(type(sanitized["owner"]["id"]), int)
        self.assertEqual(
            sanitized["body"]["storage"]["representation"],
            "storage",
        )
        self.assertEqual(
            sanitized["body"]["storage"]["value"],
            "<SANITIZED_BODY>",
        )

    def test_page_ids_are_stable_and_preserve_integer_and_string_types(self) -> None:
        sanitized_root = self.sanitizer.sanitize(self.raw_root)
        sanitized_page = self.sanitizer.sanitize(self.raw_page)
        root_id = sanitized_root["id"]
        self.assertEqual(root_id, sanitized_page["results"][0]["parentId"])
        self.assertEqual(
            root_id,
            sanitized_page["results"][0]["ancestors"][0]["id"],
        )
        self.assertIs(type(root_id), int)
        self.assertIs(type(sanitized_page["results"][0]["id"]), int)
        self.assertIs(type(sanitized_page["results"][1]["id"]), str)

    def test_same_page_identity_with_mixed_json_types_is_rejected(self) -> None:
        sanitizer = probe.Sanitizer(
            base_url=BASE_URL,
            root_page_id=123,
            space_key="KNOW",
        )
        with self.assertRaises(probe.PacketValidationError):
            sanitizer.prime({"id": "123"})

    def test_sensitive_values_are_removed(self) -> None:
        sanitized = json.dumps(
            {
                "root": self.sanitizer.sanitize(self.raw_root),
                "page": self.sanitizer.sanitize(self.raw_page),
            },
            ensure_ascii=False,
        )
        for forbidden in (
            "wiki.private.example",
            "Private Root Title",
            "Private Child One",
            "Private Space Name",
            "account-private",
            EMAIL,
            "PRIVATE BODY TEXT",
            "private-label",
        ):
            self.assertNotIn(forbidden, sanitized)

    def test_metadata_hints_do_not_claim_unexpanded_fields(self) -> None:
        observed, unavailable = probe.observe_metadata_fields(
            [
                {
                    "id": "123",
                    "_expandable": {
                        "ancestors": "",
                        "version": "",
                        "space": "",
                    },
                    "_links": {
                        "labels": "/rest/private-labels",
                        "title": "not page metadata",
                    },
                }
            ]
        )
        self.assertEqual(observed, ("page ID",))
        for field in (
            "title",
            "space / space key",
            "ancestors",
            "version",
            "labels",
        ):
            self.assertIn(field, unavailable)

        observed_with_data, _ = probe.observe_metadata_fields(
            [{"id": "123", "ancestors": [], "version": {"number": 1}}]
        )
        self.assertIn("ancestors", observed_with_data)
        self.assertIn("version", observed_with_data)

    def test_link_and_cursor_shape_is_retained(self) -> None:
        raw_link = (
            f'<{BASE_URL}/rest/confirmed/content/123?cursor=opaque-value&limit=2>; '
            'rel="next"'
        )
        sanitized = self.sanitizer.sanitize_link_header(raw_link)
        self.assertIn("https://<CONFLUENCE_HOST>/", sanitized)
        self.assertIn("cursor=<CURSOR_001>", sanitized)
        self.assertIn("limit=2", sanitized)
        self.assertIn('rel="next"', sanitized)
        self.assertNotIn("opaque-value", sanitized)
        self.assertNotIn("/123?", sanitized)

    def test_query_sanitizer_never_returns_partially_redacted_cql(self) -> None:
        sanitized = self.sanitizer.sanitize_url(
            "/rest/search?cql=space%3DKNOW+AND+title%3DPrivate+Root+Title"
        )
        self.assertIn("cql=", sanitized)
        self.assertNotIn("KNOW", sanitized)
        self.assertNotIn("Private", sanitized)
        self.assertNotIn("Title", sanitized)

    def test_unconfirmed_fields_query_value_is_not_preserved(self) -> None:
        sanitized = self.sanitizer.sanitize_url(
            f"/rest/search?fields={EMAIL}"
        )
        self.assertNotIn(EMAIL, sanitized)
        self.assertIn("fields=", sanitized)

    def test_confirmed_nonstandard_cursor_key_maps_consistently(self) -> None:
        raw = {
            "continuation": "opaque-private-value",
            "_links": {"next": "/rest/items?continuation=opaque-private-value"},
        }
        sanitizer = probe.Sanitizer(
            base_url=BASE_URL,
            root_page_id="1",
            space_key="K",
            safe_path_segments=("rest", "items"),
            cursor_keys=("continuation",),
        )
        sanitizer.prime(raw)
        sanitized = sanitizer.sanitize(raw)
        cursor = sanitized["continuation"]
        self.assertIn(cursor, sanitized["_links"]["next"])
        self.assertNotIn("opaque-private-value", json.dumps(sanitized))

    def test_webui_path_removes_space_key_and_title_slug(self) -> None:
        sanitized = self.sanitizer.sanitize(self.raw_root)
        webui = sanitized["_links"]["webui"]
        self.assertTrue(webui.startswith("/"))
        self.assertNotIn("KNOW", webui)
        self.assertNotIn("Private", webui)
        self.assertNotIn("Root", webui)
        self.assertNotIn("Title", webui)
        self.assertIn("SAN", webui)

    def test_sensitive_title_wins_over_safe_api_path_segment(self) -> None:
        raw = {
            "id": "1",
            "title": "api",
            "space": {"key": "K"},
            "_links": {"webui": "/display/K/api"},
        }
        sanitizer = probe.Sanitizer(
            base_url=BASE_URL,
            root_page_id="1",
            space_key="K",
            safe_path_segments=("display", "api"),
        )
        sanitizer.prime(raw)
        sanitized = sanitizer.sanitize(raw)
        self.assertNotIn("/api", sanitized["_links"]["webui"])
        self.assertNotEqual(sanitized["title"], "api")

    def test_link_header_drops_untrusted_parameters_and_tail(self) -> None:
        raw_link = (
            f'<{BASE_URL}/rest/confirmed/content/123?cursor=opaque>; '
            f'rel="next"; title="{EMAIL}", malformed={PAT}'
        )
        sanitized = self.sanitizer.sanitize_link_header(raw_link)
        self.assertIn('rel="next"', sanitized)
        self.assertNotIn(EMAIL, sanitized)
        self.assertNotIn(PAT, sanitized)

    def test_timestamp_format_is_preserved(self) -> None:
        sanitized = self.sanitizer.sanitize(self.raw_root)
        value = sanitized["version"]["when"]
        self.assertRegex(value, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}[+-]\d{2}:\d{2}$")
        self.assertNotEqual(value, self.raw_root["version"]["when"])


class RequestAndPaginationTests(unittest.TestCase):
    def test_template_values_are_encoded_once(self) -> None:
        template = probe.RequestTemplate(
            path_template="/root/{root_page_id}/children",
            query=(("root", "{root_page_id}"), ("space", "{space_key}")),
        )
        rendered = probe.render_request_template(
            template,
            root_page_id="a/b",
            space_key="A B",
            page_size=2,
        )
        self.assertEqual(
            rendered,
            "/root/a%2Fb/children?root=a%2Fb&space=A+B",
        )
        self.assertNotIn("%252F", rendered)

    def test_http_client_uses_get_only_and_does_not_retry(self) -> None:
        opener = QueueOpener([FakeResponse({"id": 1})])
        client = probe.ReadOnlyHttpClient(
            base_url=BASE_URL,
            authorization_value=f"Bearer {PAT}",
            timeout_seconds=4.0,
            opener=opener,
        )
        result = client.get_json(f"{BASE_URL}/rest/confirmed/content/1")
        self.assertEqual(result.payload, {"id": 1})
        self.assertEqual(len(opener.requests), 1)
        request, timeout = opener.requests[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertIsNone(request.data)
        self.assertEqual(request.get_header("Authorization"), f"Bearer {PAT}")
        self.assertEqual(timeout, 4.0)

    def test_http_client_scrubs_unavoidable_body_immediately(self) -> None:
        opener = QueueOpener([FakeResponse(root_payload())])
        client = probe.ReadOnlyHttpClient(
            base_url=BASE_URL,
            authorization_value="Bearer hidden",
            timeout_seconds=4.0,
            opener=opener,
        )
        result = client.get_json(f"{BASE_URL}/rest/confirmed/content/123")
        storage = result.payload["body"]["storage"]
        self.assertEqual(storage["representation"], "storage")
        self.assertEqual(storage["value"], "<SANITIZED_BODY>")
        self.assertNotIn("PRIVATE BODY TEXT", json.dumps(result.payload))

    def test_http_client_does_not_preserve_unrecognized_representation(self) -> None:
        payload = {
            "body": {
                "storage": {
                    "representation": "accountPrivate123",
                    "value": "private",
                }
            }
        }
        opener = QueueOpener([FakeResponse(payload)])
        client = probe.ReadOnlyHttpClient(
            base_url=BASE_URL,
            authorization_value="Bearer hidden",
            timeout_seconds=4.0,
            opener=opener,
        )
        result = client.get_json(f"{BASE_URL}/rest/confirmed/content/123")
        storage = result.payload["body"]["storage"]
        self.assertEqual(storage["representation"], "<SANITIZED_BODY>")

    def test_redirect_handler_refuses_redirect_request(self) -> None:
        handler = probe.NoRedirectHandler()
        self.assertIsNone(
            handler.redirect_request(
                mock.sentinel.request,
                mock.sentinel.response,
                302,
                "Found",
                {},
                "https://other.example/target",
            )
        )

    def test_http_error_message_does_not_expose_body_url_or_token(self) -> None:
        error = HTTPError(
            f"{BASE_URL}/private/123",
            401,
            "Unauthorized",
            {"Content-Type": "application/json"},
            io.BytesIO(b'{"message":"private server detail"}'),
        )
        opener = QueueOpener([error])
        client = probe.ReadOnlyHttpClient(
            base_url=BASE_URL,
            authorization_value=f"Bearer {PAT}",
            timeout_seconds=4.0,
            opener=opener,
        )
        with self.assertRaises(probe.HttpProbeError) as context:
            client.get_json(f"{BASE_URL}/private/123")
        message = context.exception.safe_message
        self.assertIn("401", message)
        self.assertNotIn("private server detail", message)
        self.assertNotIn("wiki.private.example", message)
        self.assertNotIn(PAT, message)
        self.assertEqual(len(opener.requests), 1)

    def test_json_next_rejects_cross_origin(self) -> None:
        client = probe.ReadOnlyHttpClient(
            base_url=BASE_URL,
            authorization_value="Bearer hidden",
            timeout_seconds=1.0,
            opener=QueueOpener([]),
        )
        response = probe.HttpResult(
            url=f"{BASE_URL}/rest/items?limit=2",
            status=200,
            content_type="application/json",
            link_header=None,
            payload={"_links": {"next": "https://attacker.example/items?page=2"}},
        )
        with self.assertRaises(probe.PaginationError):
            probe.determine_next_page(
                profile=probe.PaginationProfile(
                    kind="json_next", next_pointer="/_links/next"
                ),
                response=response,
                client=client,
            )

    def test_pagination_scope_rejects_same_origin_path_escape(self) -> None:
        profile = probe.PaginationProfile(
            kind="json_next",
            next_pointer="/_links/next",
            mutable_query_parameters=("cursor",),
        )
        with self.assertRaises(probe.PaginationError):
            probe._validate_pagination_scope(
                initial_url=f"{BASE_URL}/rest/root/123/children?limit=2",
                next_url=f"{BASE_URL}/rest/search?limit=2&cursor=next",
                profile=profile,
            )

    def test_pagination_scope_rejects_changed_selector_query(self) -> None:
        profile = probe.PaginationProfile(
            kind="json_next",
            next_pointer="/_links/next",
            mutable_query_parameters=("cursor",),
        )
        with self.assertRaises(probe.PaginationError):
            probe._validate_pagination_scope(
                initial_url=f"{BASE_URL}/rest/search?space=KNOW&limit=2",
                next_url=(
                    f"{BASE_URL}/rest/search?space=OTHER&limit=2&cursor=next"
                ),
                profile=profile,
            )

    def test_pagination_scope_accepts_reordered_immutable_query_pairs(self) -> None:
        profile = probe.PaginationProfile(
            kind="json_next",
            next_pointer="/_links/next",
            mutable_query_parameters=("start",),
        )
        probe._validate_pagination_scope(
            initial_url=(
                f"{BASE_URL}/rest/search?space=KNOW&type=page&limit=2"
            ),
            next_url=(
                f"{BASE_URL}/rest/search?limit=2&start=2&type=page&space=KNOW"
            ),
            profile=profile,
        )

    def test_pagination_scope_rejects_reordered_type_change(self) -> None:
        profile = probe.PaginationProfile(
            kind="json_next",
            next_pointer="/_links/next",
            mutable_query_parameters=("start",),
        )
        with self.assertRaises(probe.PaginationError):
            probe._validate_pagination_scope(
                initial_url=(
                    f"{BASE_URL}/rest/search?space=KNOW&type=page&limit=2&start=0"
                ),
                next_url=(
                    f"{BASE_URL}/rest/search?limit=2&start=2&type=blogpost&space=KNOW"
                ),
                profile=profile,
            )

    def test_link_header_parser_handles_multiple_relations(self) -> None:
        header = (
            '<https://example.invalid/previous>; rel="prev", '
            '</rest/items?cursor=next-value>; title="quoted, comma"; '
            'type="application/json"; rel="next"'
        )
        self.assertEqual(
            probe.extract_link_next(header),
            "/rest/items?cursor=next-value",
        )

    def test_link_header_ignores_rel_text_inside_quoted_parameter(self) -> None:
        header = '</rest/items?cursor=trap>; title="x; rel=next"'
        self.assertIsNone(probe.extract_link_next(header))
        sanitizer = probe.Sanitizer(
            base_url=BASE_URL,
            root_page_id=123,
            space_key="KNOW",
        )
        sanitized = sanitizer.sanitize_link_header(header)
        self.assertIn('rel="NOT_PRESENT"', sanitized)
        self.assertNotIn('rel="next"', sanitized)

    def test_start_limit_advances_only_confirmed_parameters(self) -> None:
        profile = probe.PaginationProfile(
            kind="start_limit",
            start_query_parameter="start",
            limit_query_parameter="limit",
            response_start_pointer="/start",
            response_limit_pointer="/limit",
            response_size_pointer="/size",
            response_total_pointer="/total",
            terminal_rule="start_plus_size_gte_total",
        )
        client = probe.ReadOnlyHttpClient(
            base_url=BASE_URL,
            authorization_value="Bearer hidden",
            timeout_seconds=1.0,
            opener=QueueOpener([]),
        )
        response = probe.HttpResult(
            url=f"{BASE_URL}/rest/items?start=0&limit=2&expand=version",
            status=200,
            content_type="application/json",
            link_header=None,
            payload={"start": 0, "limit": 2, "size": 2, "total": 5},
        )
        decision = probe.determine_next_page(
            profile=profile,
            response=response,
            client=client,
        )
        query = parse_qs(urlsplit(decision.next_url).query)
        self.assertEqual(query["start"], ["2"])
        self.assertEqual(query["limit"], ["2"])
        self.assertEqual(query["expand"], ["version"])

    def test_start_limit_rejects_non_advancing_response(self) -> None:
        profile = probe.PaginationProfile(
            kind="start_limit",
            start_query_parameter="start",
            limit_query_parameter="limit",
            response_start_pointer="/start",
            response_limit_pointer="/limit",
            response_size_pointer="/size",
            response_total_pointer="/total",
            terminal_rule="start_plus_size_gte_total",
        )
        client = probe.ReadOnlyHttpClient(
            base_url=BASE_URL,
            authorization_value="Bearer hidden",
            timeout_seconds=1.0,
            opener=QueueOpener([]),
        )
        response = probe.HttpResult(
            url=f"{BASE_URL}/rest/items?start=0&limit=2",
            status=200,
            content_type="application/json",
            link_header=None,
            payload={"start": 0, "limit": 2, "size": 0, "total": 5},
        )
        with self.assertRaises(probe.PaginationError):
            probe.determine_next_page(
                profile=profile,
                response=response,
                client=client,
            )

    def test_start_limit_rejects_response_window_mismatch(self) -> None:
        profile = probe.PaginationProfile(
            kind="start_limit",
            start_query_parameter="start",
            limit_query_parameter="limit",
            response_start_pointer="/start",
            response_limit_pointer="/limit",
            response_size_pointer="/size",
            response_total_pointer="/total",
            terminal_rule="start_plus_size_gte_total",
        )
        client = probe.ReadOnlyHttpClient(
            base_url=BASE_URL,
            authorization_value="Bearer hidden",
            timeout_seconds=1.0,
            opener=QueueOpener([]),
        )
        response = probe.HttpResult(
            url=f"{BASE_URL}/rest/items?start=0&limit=2",
            status=200,
            content_type="application/json",
            link_header=None,
            payload={"start": 100, "limit": 50, "size": 2, "total": 200},
        )
        with self.assertRaises(probe.PaginationError):
            probe.determine_next_page(
                profile=profile,
                response=response,
                client=client,
            )

    def test_cursor_value_uses_only_confirmed_query_parameter(self) -> None:
        profile = probe.PaginationProfile(
            kind="cursor_value",
            next_pointer="/nextCursor",
            cursor_query_parameter="cursor",
            mutable_query_parameters=("cursor",),
        )
        client = probe.ReadOnlyHttpClient(
            base_url=BASE_URL,
            authorization_value="Bearer hidden",
            timeout_seconds=1.0,
            opener=QueueOpener([]),
        )
        response = probe.HttpResult(
            url=f"{BASE_URL}/rest/items?limit=2&scope=root",
            status=200,
            content_type="application/json",
            link_header=None,
            payload={"nextCursor": "opaque/cursor+value"},
        )
        decision = probe.determine_next_page(
            profile=profile,
            response=response,
            client=client,
        )
        query = parse_qs(urlsplit(decision.next_url).query)
        self.assertEqual(query["cursor"], ["opaque/cursor+value"])
        self.assertEqual(query["limit"], ["2"])
        self.assertEqual(query["scope"], ["root"])
        self.assertEqual(
            probe._describe_next_shape(profile, decision),
            "opaque cursor value applied to a confirmed query parameter",
        )

    def test_collection_follows_actual_next_and_captures_numeric_root(self) -> None:
        opener = QueueOpener(
            [
                FakeResponse(root_payload()),
                FakeResponse(descendants_page_1()),
                FakeResponse(descendants_page_2()),
            ]
        )
        client = probe.ReadOnlyHttpClient(
            base_url=BASE_URL,
            authorization_value="Bearer hidden",
            timeout_seconds=3.0,
            opener=opener,
        )
        with tempfile.TemporaryDirectory() as temporary:
            result = probe.collect_packet_data(
                config=make_config(Path(temporary) / "packet"),
                client=client,
            )
        self.assertEqual(result.root_identity, 123)
        self.assertEqual(len(result.descendant_pages), 2)
        self.assertTrue(result.terminal_page_observed)
        self.assertFalse(result.pagination_truncated)
        self.assertEqual(len(opener.requests), 3)
        self.assertTrue(
            opener.requests[-1][0].full_url.endswith(
                "?cursor=opaque-private-cursor&limit=2"
            )
        )

    def test_collection_marks_cap_as_truncated(self) -> None:
        opener = QueueOpener(
            [FakeResponse(root_payload()), FakeResponse(descendants_page_1())]
        )
        client = probe.ReadOnlyHttpClient(
            base_url=BASE_URL,
            authorization_value="Bearer hidden",
            timeout_seconds=3.0,
            opener=opener,
        )
        with tempfile.TemporaryDirectory() as temporary:
            result = probe.collect_packet_data(
                config=make_config(Path(temporary) / "packet", max_pages=1),
                client=client,
            )
        self.assertTrue(result.pagination_truncated)
        self.assertFalse(result.terminal_page_observed)
        self.assertEqual(len(opener.requests), 2)

    def test_collection_rejects_repeated_next_url(self) -> None:
        repeated_page = descendants_page_1()
        repeated_page["_links"]["next"] = (
            "/rest/confirmed/content/123/descendant/page?limit=2"
        )
        opener = QueueOpener([FakeResponse(root_payload()), FakeResponse(repeated_page)])
        client = probe.ReadOnlyHttpClient(
            base_url=BASE_URL,
            authorization_value="Bearer hidden",
            timeout_seconds=3.0,
            opener=opener,
        )
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(probe.PaginationError):
                probe.collect_packet_data(
                    config=make_config(Path(temporary) / "packet", max_pages=2),
                    client=client,
                )
        self.assertEqual(len(opener.requests), 2)

    def test_root_identity_and_space_must_belong_to_same_object(self) -> None:
        payload = {
            "results": [
                {"id": 123, "space": {"key": "OTHER"}},
                {"id": 999, "space": {"key": "KNOW"}},
            ]
        }
        with self.assertRaises(probe.ResponseError):
            probe._validate_root_identity_and_space(
                payload=payload,
                root_page_id="123",
                space_key="KNOW",
            )

    def test_root_identity_without_space_is_accepted_as_unavailable(self) -> None:
        self.assertEqual(
            probe._validate_root_identity_and_space(
                payload={"id": 123, "title": "Private Root Title"},
                root_page_id="123",
                space_key="KNOW",
            ),
            123,
        )

    def test_inventory_rejects_explicit_page_from_another_space(self) -> None:
        with self.assertRaises(probe.ResponseError):
            probe._validate_inventory_space(
                {"results": [{"id": 124, "space": {"key": "OTHER"}}]},
                "KNOW",
            )


class ProfileTests(unittest.TestCase):
    @staticmethod
    def valid_profile_payload() -> dict[str, object]:
        return {
            "schema_version": 1,
            "deployment": "data-center",
            "confluence_version": "9.2",
            "api_family": "confirmed REST family",
            "auth_scheme": "bearer_pat",
            "root_request": {
                "path_template": "/rest/content/{root_page_id}",
                "query": [["expand", "version,ancestors"]],
            },
            "inventory_request": {
                "path_template": "/rest/content/{root_page_id}/descendant/page",
                "query": [["limit", "{page_size}"]],
            },
            "pagination": {
                "kind": "json_next",
                "next_pointer": "/_links/next",
                "mutable_query_parameters": ["cursor"],
            },
        }

    def write_profile(self, directory: str, payload: object) -> Path:
        path = Path(directory) / "profile.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_valid_profile_loads_without_credentials_or_network(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self.write_profile(temporary, self.valid_profile_payload())
            profile = probe.load_request_profile(path)
        self.assertEqual(profile.deployment, "data-center")
        self.assertEqual(profile.pagination.kind, "json_next")

    def test_profile_rejects_explicit_body_request(self) -> None:
        payload = self.valid_profile_payload()
        payload["root_request"]["query"] = [["expand", "body"]]
        with tempfile.TemporaryDirectory() as temporary:
            path = self.write_profile(temporary, payload)
            with self.assertRaises(probe.InputError):
                probe.load_request_profile(path)

    def test_profile_rejects_prohibited_resource_families(self) -> None:
        forbidden_values = (
            "children.attachment",
            "comments",
            "restrictions.read",
            "permissions",
            "per%6Dissions",
            "acl",
            "renderedHtml",
            "viewpage.action",
            "%62ody.storage",
            "att%61chment",
            "comm%65nts",
            "%61ttachments",
            "contentbody",
        )
        for forbidden in forbidden_values:
            with self.subTest(forbidden=forbidden):
                payload = self.valid_profile_payload()
                payload["root_request"]["query"] = [["expand", forbidden]]
                with tempfile.TemporaryDirectory() as temporary:
                    path = self.write_profile(temporary, payload)
                    with self.assertRaises(probe.InputError):
                        probe.load_request_profile(path)

    def test_profile_rejects_permission_resource_paths(self) -> None:
        for forbidden_path in (
            "/rest/content/{root_page_id}/permissions",
            "/rest/content/{root_page_id}/per%6Dissions",
        ):
            with self.subTest(forbidden_path=forbidden_path):
                payload = self.valid_profile_payload()
                payload["root_request"]["path_template"] = forbidden_path
                with tempfile.TemporaryDirectory() as temporary:
                    path = self.write_profile(temporary, payload)
                    with self.assertRaises(probe.InputError):
                        probe.load_request_profile(path)

    def test_start_limit_profile_requires_initial_start_and_limit_query(self) -> None:
        payload = self.valid_profile_payload()
        payload["pagination"] = {
            "kind": "start_limit",
            "start_query_parameter": "start",
            "limit_query_parameter": "limit",
            "response_start_pointer": "/start",
            "response_limit_pointer": "/limit",
            "response_size_pointer": "/size",
            "response_total_pointer": "/total",
            "terminal_rule": "start_plus_size_gte_total",
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = self.write_profile(temporary, payload)
            with self.assertRaises(probe.InputError):
                probe.load_request_profile(path)

        payload["inventory_request"]["query"] = [
            ["start", "0"],
            ["limit", "{page_size}"],
        ]
        with tempfile.TemporaryDirectory() as temporary:
            path = self.write_profile(temporary, payload)
            profile = probe.load_request_profile(path)
        self.assertEqual(profile.pagination.kind, "start_limit")

    def test_cursor_value_profile_is_explicit_and_scope_safe(self) -> None:
        payload = self.valid_profile_payload()
        payload["pagination"] = {
            "kind": "cursor_value",
            "next_pointer": "/meta/nextCursor",
            "cursor_query_parameter": "cursor",
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = self.write_profile(temporary, payload)
            profile = probe.load_request_profile(path)
        self.assertEqual(profile.pagination.kind, "cursor_value")
        self.assertEqual(profile.pagination.mutable_query_parameters, ("cursor",))

        payload["pagination"]["cursor_query_parameter"] = "spaceKey"
        with tempfile.TemporaryDirectory() as temporary:
            path = self.write_profile(temporary, payload)
            with self.assertRaises(probe.InputError):
                probe.load_request_profile(path)

    def test_profile_rejects_mutable_scope_and_page_size_parameters(self) -> None:
        for parameter in ("type", "parent", "ancestor", "status", "limit"):
            with self.subTest(parameter=parameter):
                payload = self.valid_profile_payload()
                payload["pagination"]["mutable_query_parameters"] = [parameter]
                with tempfile.TemporaryDirectory() as temporary:
                    path = self.write_profile(temporary, payload)
                    with self.assertRaises(probe.InputError):
                        probe.load_request_profile(path)

    def test_cql_ancestor_profile_is_explicitly_root_scoped(self) -> None:
        payload = self.valid_profile_payload()
        payload["inventory_request"] = {
            "path_template": "/rest/api/search",
            "query": [
                [
                    "cql",
                    'space="{space_key}" and ancestor={root_page_id} and type=page',
                ],
                [
                    "expand",
                    "content.ancestors,content.space,content.version,"
                    "content.metadata.labels",
                ],
                ["limit", "{page_size}"],
                ["start", "0"],
            ],
        }
        payload["pagination"] = {
            "kind": "start_limit",
            "start_query_parameter": "start",
            "limit_query_parameter": "limit",
            "response_start_pointer": "/start",
            "response_limit_pointer": "/limit",
            "response_size_pointer": "/size",
            "response_total_pointer": "/totalSize",
            "terminal_rule": "start_plus_size_gte_total",
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = self.write_profile(temporary, payload)
            profile = probe.load_request_profile(path)
        self.assertEqual(profile.inventory_request.path_template, "/rest/api/search")
        self.assertEqual(profile.pagination.kind, "start_limit")
        self.assertEqual(profile.pagination.response_total_pointer, "/totalSize")

    def test_profile_rejects_unresolved_template_marker(self) -> None:
        payload = self.valid_profile_payload()
        payload["api_family"] = "REPLACE_WITH_VALUE"
        with tempfile.TemporaryDirectory() as temporary:
            path = self.write_profile(temporary, payload)
            with self.assertRaises(probe.InputError):
                probe.load_request_profile(path)

    def test_validate_profile_only_makes_no_network_request(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self.write_profile(temporary, self.valid_profile_payload())
            output = io.StringIO()
            with mock.patch.object(
                probe.ReadOnlyHttpClient,
                "get_json",
                side_effect=AssertionError("network path reached"),
            ), redirect_stdout(output):
                exit_code = probe.main(
                    ["--request-profile", str(path), "--validate-profile-only"]
                )
        self.assertEqual(exit_code, probe.EXIT_OK)
        self.assertIn("no network request", output.getvalue())

    def test_verify_packet_only_scans_existing_files_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            profile_path = self.write_profile(
                temporary,
                self.valid_profile_payload(),
            )
            packet_dir = Path(temporary) / "packet"
            packet_dir.mkdir()
            for name, content in valid_packet_files().items():
                (packet_dir / name).write_bytes(content)
            output = io.StringIO()
            with (
                mock.patch.object(probe, "_read_base_url", return_value=BASE_URL),
                mock.patch.object(probe, "_read_pat", return_value=PAT),
                mock.patch.object(
                    probe,
                    "_known_scan_identities",
                    return_value=(EMAIL,),
                ),
                mock.patch.object(
                    probe.ReadOnlyHttpClient,
                    "get_json",
                    side_effect=AssertionError("network path reached"),
                ),
                redirect_stdout(output),
            ):
                exit_code = probe.main(
                    [
                        "--request-profile",
                        str(profile_path),
                        "--verify-packet-only",
                        "--output-dir",
                        str(packet_dir),
                    ]
                )
        self.assertEqual(exit_code, probe.EXIT_OK)
        self.assertIn("no network request", output.getvalue())

    def test_unknown_secret_cli_option_is_not_echoed(self) -> None:
        secret = "secret-cli-value"
        with self.assertRaises(probe.InputError) as context:
            probe.build_parser().parse_args(
                ["--request-profile", "profile.json", "--token", secret]
            )
        self.assertNotIn(secret, context.exception.safe_message)


class PacketAndWriterTests(unittest.TestCase):
    def test_rendered_packet_has_expected_files_and_no_sensitive_trace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = make_config(Path(temporary) / "packet")
            files = probe.render_packet(
                config=config,
                base_url=BASE_URL,
                token=PAT,
                known_identities=(EMAIL,),
                collection=make_collection(),
            )
        self.assertEqual(
            set(files),
            {
                "confluence_api_profile.md",
                "confluence_request_trace.md",
                "root_page_response.sanitized.json",
                "descendants_page_1.sanitized.json",
                "descendants_page_2.sanitized.json",
                "sanitization_report.md",
            },
        )
        joined = b"\n".join(files.values()).decode("utf-8")
        for forbidden in ("wiki.private.example", PAT, EMAIL, "Authorization:", "Cookie:"):
            self.assertNotIn(forbidden, joined)
        trace = files["confluence_request_trace.md"].decode("utf-8")
        self.assertEqual(trace.count("- Method: `GET`"), 3)

    def test_distinct_terminal_page_gets_last_page_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            files = probe.render_packet(
                config=make_config(Path(temporary) / "packet"),
                base_url=BASE_URL,
                token=PAT,
                known_identities=(EMAIL,),
                collection=make_collection(three_pages=True),
            )
        self.assertIn("descendants_last_page.sanitized.json", files)

    def test_short_titles_and_labels_do_not_false_positive_on_report_prose(self) -> None:
        collection = make_collection()
        collection.root.payload["title"] = "Root"
        first = collection.descendant_pages[0].payload["results"][0]
        first["title"] = "Page"
        first["labels"][0]["name"] = "labels"
        with tempfile.TemporaryDirectory() as temporary:
            files = probe.render_packet(
                config=make_config(Path(temporary) / "packet"),
                base_url=BASE_URL,
                token=PAT,
                known_identities=(EMAIL,),
                collection=collection,
            )
        self.assertIn("confluence_api_profile.md", files)

    def test_scanner_detects_sensitive_categories_without_echoing_values(self) -> None:
        cases = {
            "hostname": "wiki.private.example",
            "encoded hostname": "wiki%2Eprivate%2Eexample",
            "token": PAT,
            "base64 token": base64.b64encode(PAT.encode("utf-8")).decode("ascii"),
            "basic credential material": base64.b64encode(
                f"{EMAIL}:{PAT}".encode("utf-8")
            ).decode("ascii"),
            "authorization": f"Authorization: Bearer {PAT}",
            "cookie": "Cookie: session=abcdef",
            "set-cookie": "Set-Cookie: session=abcdef",
            "known identity": EMAIL,
        }
        for label, leak in cases.items():
            with self.subTest(label=label):
                files = valid_packet_files()
                files["confluence_request_trace.md"] = f"# trace\n{leak}\n".encode()
                with self.assertRaises(probe.PacketValidationError) as context:
                    probe.validate_rendered_packet(
                        files=files,
                        base_url=BASE_URL,
                        token=PAT,
                        known_identities=(EMAIL,),
                    )
                self.assertNotIn(PAT, context.exception.safe_message)
                self.assertNotIn(EMAIL, context.exception.safe_message)
                self.assertNotIn("wiki.private.example", context.exception.safe_message)

    def test_writer_produces_only_requested_regular_files(self) -> None:
        files = valid_packet_files()
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "packet"
            probe.write_packet(output_dir=output_dir, files=files)
            self.assertEqual(
                {path.name for path in output_dir.iterdir()},
                set(files),
            )
            self.assertTrue(all(path.is_file() for path in output_dir.iterdir()))
            json.loads(
                (output_dir / "root_page_response.sanitized.json").read_text(
                    encoding="utf-8"
                )
            )

    def test_low_level_writer_never_overwrites_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "packet.json"
            target.write_bytes(b"other writer")
            with self.assertRaises(probe.OutputError):
                probe._write_new_file(target, b"new data")
            self.assertEqual(target.read_bytes(), b"other writer")

    def test_writer_does_not_race_delete_published_file_after_failure(self) -> None:
        files = valid_packet_files()
        real_writer = probe._write_new_file
        calls = 0

        def fail_second(target: Path, content: bytes):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise probe.OutputError("simulated safe failure")
            return real_writer(target, content)

        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "packet"
            with mock.patch.object(probe, "_write_new_file", side_effect=fail_second):
                with self.assertRaises(probe.OutputError):
                    probe.write_packet(output_dir=output_dir, files=files)
            published = output_dir / "confluence_api_profile.md"
            self.assertEqual(published.read_bytes(), files[published.name])

    def test_writer_rollback_preserves_another_writers_replacement(self) -> None:
        files = valid_packet_files()
        real_writer = probe._write_new_file
        first_target: Path | None = None
        calls = 0

        def replace_then_fail(target: Path, content: bytes):
            nonlocal calls, first_target
            calls += 1
            if calls == 1:
                first_target = target
                return real_writer(target, content)
            assert first_target is not None
            first_target.unlink()
            first_target.write_bytes(b"replacement from another writer")
            raise probe.OutputError("simulated safe failure")

        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "packet"
            with mock.patch.object(
                probe,
                "_write_new_file",
                side_effect=replace_then_fail,
            ):
                with self.assertRaises(probe.OutputError):
                    probe.write_packet(output_dir=output_dir, files=files)
            assert first_target is not None
            self.assertEqual(
                first_target.read_bytes(),
                b"replacement from another writer",
            )

    def test_strict_json_rejects_nan(self) -> None:
        with self.assertRaises(probe.PacketValidationError):
            probe.render_json({"value": float("nan")})

    def test_safe_main_error_does_not_echo_secret_cli_value(self) -> None:
        secret = "secret-cli-value"
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            exit_code = probe.main(
                ["--request-profile", "profile.json", "--password", secret]
            )
        self.assertEqual(exit_code, probe.EXIT_INPUT)
        self.assertNotIn(secret, stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
