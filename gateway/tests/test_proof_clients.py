"""Exercise proof clients through HTTP, with real local grant/identity stores."""

import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import httpx
import pytest

from ha_didcomm import acapy, config, controller, credentials, proofs, rpc


ADMIN_URL = "https://acapy.example.test"
ADMIN_KEY = "test-only-admin-key"
CONNECTION = "home-connection"
EXCHANGE = "proof-exchange"
ISSUER = "did:key:home-issuer"
HOLDER = "did:key:z-saved-holder"
OTHER_HOLDER = "did:key:a-other-holder"
HOME = "test-home"
ENTITY = "light.guest_room"
RECORDS_PATH = "/present-proof-2.0/records"
CREDENTIALS_PATH = f"{RECORDS_PATH}/{EXCHANGE}/credentials"
PRESENTATION_PATH = f"{RECORDS_PATH}/{EXCHANGE}/send-presentation"
FIELD_PATHS = (
    "$.issuer", "$.credentialSubject.id", "$.issuanceDate",
    "$.credentialSubject.home",
)


def replace_at(value, path, replacement):
    """Create nested variants without changing shared fixture data."""
    if not path:
        return deepcopy(replacement)
    key, *rest = path
    if isinstance(value, list):
        return [
            replace_at(item, rest, replacement) if index == key else deepcopy(item)
            for index, item in enumerate(value)
        ]
    return {**deepcopy(value), key: replace_at(value.get(key), rest, replacement)}


@pytest.fixture
def grant(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CREDENTIAL_STORE_PATH", str(tmp_path / "grants.sqlite3"))
    monkeypatch.setattr(config, "HOME_ID", HOME)
    monkeypatch.setattr(config, "HOME_ISSUER_DID", ISSUER)
    monkeypatch.setattr(config, "ACAPY_ADMIN_URL", ADMIN_URL)
    monkeypatch.setattr(config, "ACAPY_ADMIN_API_KEY", ADMIN_KEY)
    monkeypatch.setattr(controller, "ADMIN_URL", ADMIN_URL)
    monkeypatch.setattr(controller, "ADMIN_API_KEY", ADMIN_KEY)
    monkeypatch.setattr(controller, "RESPONSE_STORE_PATH", str(tmp_path / "holder.sqlite3"))
    monkeypatch.delenv("CONTROLLER_HOLDER_DID", raising=False)
    controller._set_setting("holder_did", HOLDER)
    vc = {
        **credentials.build_credential(
            subject_did=HOLDER, issuer_did=ISSUER, role="guest",
            permissions=["light.guest_*"], expires_iso=None,
        ),
        "issuanceDate": "2026-09-01T00:00:00Z",
    }
    old = {**vc, "issuanceDate": "2026-08-01T00:00:00Z"}
    credentials.remember_issued(CONNECTION, old, "old-issuance")
    assert credentials.revoke_credential("old-issuance")
    credentials.remember_issued(CONNECTION, vc, "current-issuance")
    command = rpc.Request("outstanding-command", "turn_on", ENTITY)
    body = proofs.build_request(CONNECTION, command)
    definition = body["presentation_request"]["dif"]["presentation_definition"]
    candidate = {**vc, "record_id": "wallet-current"}
    return SimpleNamespace(
        vc=vc, old={**old, "record_id": "wallet-old"}, candidate=candidate,
        command=command, body=body, definition=definition,
    )


@pytest.fixture
def mock_http(monkeypatch):
    # Keep HTTPX request encoding/status exceptions real; replace only I/O.
    real_client = httpx.AsyncClient

    def install(handler):
        monkeypatch.setattr(
            httpx, "AsyncClient",
            lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
        )

    return install


def assert_request(request, method, path, params=None, key=ADMIN_KEY):
    assert request.method == method
    assert str(request.url).split("?", 1)[0] == ADMIN_URL + path
    assert dict(request.url.params) == (params or {})
    assert request.headers["Content-Type"] == "application/json"
    assert request.headers.get("X-API-Key") == (key or None)


def exchange_record(grant):
    return {
        "pres_ex_id": EXCHANGE, "connection_id": CONNECTION,
        "state": "request-received", "role": "prover",
        "by_format": {"pres_request": {"dif": grant.body["presentation_request"]["dif"]}},
    }


def controller_api(mock_http, grant, records, candidates=None, fail_at=None, status=503):
    calls = []

    def handler(request):
        calls.append(request)
        path = request.url.path
        if path == RECORDS_PATH:
            assert_request(request, "GET", path, {
                "connection_id": CONNECTION, "role": "prover", "state": "request-received",
            })
            payload = {"results": records}
        elif path == "/wallet/did":
            assert_request(request, "GET", path)
            # Saved identity must win over both wallet order and lexical order.
            payload = {"results": [{"did": OTHER_HOLDER}, {"did": HOLDER}]}
        elif path == CREDENTIALS_PATH:
            assert_request(request, "GET", path, {"count": "1000"})
            payload = candidates
        elif path == PRESENTATION_PATH:
            assert_request(request, "POST", path)
            descriptor_id = grant.definition["input_descriptors"][0]["id"]
            assert json.loads(request.content) == {"dif": {
                "issuer_id": HOLDER, "record_ids": {descriptor_id: ["wallet-current"]},
            }}
            payload = {"pres_ex_id": EXCHANGE, "state": "presentation-sent"}
        else:
            pytest.fail(f"Unexpected controller request: {request.method} {path}")
        return httpx.Response(
            status if path == fail_at else 200,
            content=json.dumps(payload), headers={"Content-Type": "application/json"},
        )

    mock_http(handler)
    return calls


def respond(grant):
    return asyncio.run(controller._respond_to_command_proof(CONNECTION, grant.command))


def select(grant, candidates, definition=None, signer=HOLDER, entity=ENTITY):
    return controller._select_proof_credential(
        candidates, grant.definition if definition is None else definition, signer, entity,
    )


def test_controller_polls_again_and_sends_only_matching_wallet_record(grant, mock_http):
    record = exchange_record(grant)
    unrelated = replace_at(record, (
        "by_format", "pres_request", "dif", "presentation_definition", "id",
    ), "unsolicited-command")
    candidates = [
        grant.old,
        {**grant.candidate, "issuer": "did:key:wrong-issuer", "record_id": "wrong-issuer"},
        replace_at(grant.candidate, ("credentialSubject", "id"), OTHER_HOLDER),
        grant.candidate,
        {**grant.candidate, "record_id": "second-match"},
    ]
    # Separate invocations represent the caller's polling loop; no webhook is needed.
    first = controller_api(mock_http, grant, [unrelated], candidates)
    assert respond(grant) is None
    assert [request.url.path for request in first] == [RECORDS_PATH]
    second = controller_api(mock_http, grant, [unrelated, record], candidates)
    assert respond(grant) is None
    assert [request.url.path for request in second] == [
        RECORDS_PATH, "/wallet/did", CREDENTIALS_PATH, PRESENTATION_PATH,
    ]
    assert controller._get_setting("holder_did") == HOLDER


@pytest.mark.parametrize(("path", "value"), [
    (("connection_id",), "other-connection"),
    (("connection_id",), None),
    (("role",), "verifier"),
    (("role",), None),
    (("state",), "done"),
    (("state",), "presentation-sent"),
    (("state",), None),
    (("pres_ex_id",), ""),
    (("pres_ex_id",), None),
    (("pres_ex_id",), 7),
    (("by_format",), None),
    (("by_format", "pres_request"), {}),
    (("by_format", "pres_request", "dif", "presentation_definition", "id"), "unsolicited"),
])
def test_controller_ignores_unbound_or_malformed_exchange(grant, mock_http, path, value):
    record = replace_at(exchange_record(grant), path, value)
    calls = controller_api(mock_http, grant, [None, "record", {}, record], [grant.candidate])
    assert respond(grant) is None
    assert [request.url.path for request in calls] == [RECORDS_PATH]


@pytest.mark.parametrize("records", [None, {}, "records", 7])
def test_controller_rejects_invalid_record_collection(grant, mock_http, records):
    calls = controller_api(mock_http, grant, records)
    with pytest.raises(ValueError, match="presentation records"):
        respond(grant)
    assert len(calls) == 1


@pytest.mark.parametrize("kind", ["empty", "old", "wrong-issuer", "wrapped", "null"])
def test_controller_does_not_present_without_matching_credential(grant, mock_http, kind):
    candidates = {
        "empty": [], "old": [grant.old],
        "wrong-issuer": [{**grant.candidate, "issuer": "did:key:wrong-issuer"}],
        "wrapped": {"results": [grant.candidate]}, "null": None,
    }[kind]
    calls = controller_api(mock_http, grant, [exchange_record(grant)], candidates)
    assert respond(grant) is None
    assert [request.url.path for request in calls] == [
        RECORDS_PATH, "/wallet/did", CREDENTIALS_PATH,
    ]


@pytest.mark.parametrize("path", [RECORDS_PATH, "/wallet/did", CREDENTIALS_PATH, PRESENTATION_PATH])
@pytest.mark.parametrize("status", [401, 404, 503])
def test_controller_propagates_http_errors_and_stops(grant, mock_http, path, status):
    calls = controller_api(
        mock_http, grant, [exchange_record(grant)], [grant.candidate], path, status,
    )
    with pytest.raises(httpx.HTTPStatusError) as caught:
        respond(grant)
    assert caught.value.response.status_code == status
    assert caught.value.request is calls[-1]
    expected = [RECORDS_PATH, "/wallet/did", CREDENTIALS_PATH, PRESENTATION_PATH]
    assert [request.url.path for request in calls] == expected[:expected.index(path) + 1]


def test_selector_uses_real_four_field_definition_and_skips_old_overlapping_grants(grant):
    descriptor = grant.definition["input_descriptors"][0]
    assert descriptor["id"] == "home-access:" + credentials.credential_fingerprint(grant.vc)
    fields = descriptor["constraints"]["fields"]
    assert [field["path"] for field in fields] == [[path] for path in FIELD_PATHS]
    assert fields[0]["filter"] == {"const": ISSUER}
    assert fields[1]["filter"] == {"enum": [HOLDER]}
    assert fields[2]["filter"] == {"enum": [grant.vc["issuanceDate"]]}
    assert fields[3]["filter"] == {"const": HOME}
    candidates = [
        grant.old, {**grant.candidate, "issuer": OTHER_HOLDER}, grant.candidate,
        {**grant.candidate, "record_id": "also-matches"},
    ]
    before = deepcopy((candidates, grant.definition))
    assert select(grant, candidates) == "wallet-current"
    assert (candidates, grant.definition) == before


@pytest.mark.parametrize(("path", "value"), [
    (("issuer",), "did:key:wrong-issuer"),
    (("credentialSubject", "id"), OTHER_HOLDER),
    (("issuanceDate",), "2020-01-01T00:00:00Z"),
    (("credentialSubject", "home"), "other-home"),
])
def test_selector_enforces_each_constraint_independently(grant, path, value):
    candidate = replace_at(grant.candidate, path, value)
    assert select(grant, [candidate]) is None
    assert select(grant, [candidate, grant.candidate]) == "wallet-current"
    field_index = {
        ("issuer",): 0, ("credentialSubject", "id"): 1,
        ("issuanceDate",): 2, ("credentialSubject", "home"): 3,
    }[path]
    definition = replace_at(grant.definition, (
        "input_descriptors", 0, "constraints", "fields", field_index, "filter",
    ), {"const": value})
    # A matching fingerprint must not bypass the four field constraints.
    assert select(grant, [grant.candidate], definition) is None


@pytest.mark.parametrize(("permissions", "entity", "expected"), [
    (["light.guest_room"], ENTITY, "wallet-current"),
    (["light.*"], ENTITY, "wallet-current"),
    (["light.guest_?oom"], ENTITY, "wallet-current"),
    (["light.guest_[rs]oom"], ENTITY, "wallet-current"),
    ([None, 7, "switch.*", "light.*"], ENTITY, "wallet-current"),
    (["light.guest_[!r]oom"], ENTITY, None),
    (["light.guest_*"], "lock.front_door", None),
    (["light.guest_room"], "light.guest_room_extra", None),
    (["switch.*"], ENTITY, None),
    ([], ENTITY, None),
    ("light.*", ENTITY, None),
    (None, ENTITY, None),
    ({"light.*": True}, ENTITY, None),
    ([None, 7, {}], ENTITY, None),
])
def test_selector_applies_fnmatch_permissions(grant, permissions, entity, expected):
    vc = replace_at(grant.vc, ("credentialSubject", "permissions"), permissions)
    credentials.remember_issued(CONNECTION, vc, "permission-issuance")
    body = proofs.build_request(CONNECTION, grant.command)
    definition = body["presentation_request"]["dif"]["presentation_definition"]
    candidate = {**vc, "record_id": "wallet-current"}
    assert select(grant, [candidate], definition, entity=entity) == expected


def test_selector_requires_local_signer_even_when_definition_allows_other_subject(grant):
    foreign_vc = replace_at(grant.vc, ("credentialSubject", "id"), OTHER_HOLDER)
    credentials.remember_issued(CONNECTION, foreign_vc, "foreign-holder-issuance")
    body = proofs.build_request(CONNECTION, grant.command)
    definition = body["presentation_request"]["dif"]["presentation_definition"]
    descriptor = definition["input_descriptors"][0]
    assert set(descriptor["constraints"]["fields"][1]["filter"]["enum"]) == {
        HOLDER, OTHER_HOLDER,
    }
    assert credentials.credential_fingerprint(foreign_vc) in descriptor["id"].split(":", 1)[1].split(",")
    foreign = {**foreign_vc, "record_id": "wallet-foreign"}
    assert select(grant, [foreign], definition) is None
    assert select(grant, [grant.candidate], definition, signer=OTHER_HOLDER) is None
    assert select(grant, [foreign, grant.candidate], definition) == "wallet-current"


@pytest.mark.parametrize("signed", [False, True])
def test_same_second_revoked_broad_grant_cannot_replace_active_narrow_grant(grant, mock_http, signed):
    broad = replace_at(grant.vc, ("credentialSubject", "permissions"), ["light.*", "lock.*"])
    narrow = replace_at(grant.vc, ("credentialSubject", "permissions"), [ENTITY])
    assert credentials.revoke_credential("current-issuance")
    credentials.remember_issued(CONNECTION, broad, "same-second-broad")
    assert credentials.revoke_credential("same-second-broad")
    credentials.remember_issued(CONNECTION, narrow, "same-second-narrow")
    body = proofs.build_request(CONNECTION, grant.command)
    definition = body["presentation_request"]["dif"]["presentation_definition"]
    descriptor = definition["input_descriptors"][0]
    assert descriptor["id"] == "home-access:" + credentials.credential_fingerprint(narrow)
    assert credentials.credential_fingerprint(broad) not in descriptor["id"]
    for vc in (broad, narrow):
        values = [vc["issuer"], vc["credentialSubject"]["id"], vc["issuanceDate"],
                  vc["credentialSubject"]["home"]]
        for field, value in zip(descriptor["constraints"]["fields"], values, strict=True):
            constraint = field["filter"]
            assert value in constraint.get("enum", [constraint.get("const")])
    signature = {"proof": {"type": "Ed25519Signature2018", "jws": "test-signature"}} if signed else {}
    candidates = [
        {**broad, **signature, "record_id": "wallet-revoked-broad"},
        {**narrow, **signature, "record_id": "wallet-current"},
    ]
    before = deepcopy((candidates, definition))
    assert select(grant, candidates[:1], definition) is None
    assert select(grant, candidates, definition) == "wallet-current"
    assert (candidates, definition) == before
    scenario = SimpleNamespace(**{**vars(grant), "body": body, "definition": definition})
    calls = controller_api(mock_http, scenario, [exchange_record(scenario)], candidates)
    assert respond(scenario) is None
    assert [request.url.path for request in calls] == [
        RECORDS_PATH, "/wallet/did", CREDENTIALS_PATH, PRESENTATION_PATH,
    ]


def test_descriptor_contains_sorted_exact_eligible_fingerprints_and_is_used_on_send(grant, mock_http):
    second = replace_at(grant.vc, ("credentialSubject", "permissions"), ["light.*"])
    credentials.remember_issued(CONNECTION, second, "second-active-issuance")
    body = proofs.build_request(CONNECTION, grant.command)
    definition = body["presentation_request"]["dif"]["presentation_definition"]
    expected = sorted([
        credentials.credential_fingerprint(grant.vc), credentials.credential_fingerprint(second),
    ])
    assert len(set(expected)) == 2
    assert definition["input_descriptors"][0]["id"] == "home-access:" + ",".join(expected)
    scenario = SimpleNamespace(**{**vars(grant), "body": body, "definition": definition})
    calls = controller_api(mock_http, scenario, [exchange_record(scenario)], [grant.candidate])
    assert respond(scenario) is None
    assert calls[-1].url.path == PRESENTATION_PATH


def test_selector_ignores_added_proof_and_wallet_id_but_binds_other_credential_fields(grant):
    signed = {**grant.vc, "proof": {"jws": "signature-a"}}
    assert credentials.credential_fingerprint(signed) == credentials.credential_fingerprint(grant.vc)
    assert select(grant, [{**signed, "record_id": "different-wallet-id"}]) == "different-wallet-id"
    changed_proof = {**signed, "proof": {"jws": "signature-b"}, "record_id": "another-wallet-id"}
    assert select(grant, [changed_proof]) == "another-wallet-id"
    changed_role = replace_at(grant.candidate, ("credentialSubject", "role"), "resident")
    assert select(grant, [changed_role]) is None
    assert select(grant, [{**grant.candidate, "extra": "unsigned-data"}]) is None


@pytest.mark.parametrize("field_index", range(4))
@pytest.mark.parametrize("filter_kind", ["const", "enum"])
def test_selector_supports_const_and_enum_for_each_fixed_path(grant, field_index, filter_kind):
    value = [ISSUER, HOLDER, grant.vc["issuanceDate"], HOME][field_index]
    filter_value = value if filter_kind == "const" else ["nonmatch", value]
    definition = replace_at(grant.definition, (
        "input_descriptors", 0, "constraints", "fields", field_index, "filter",
    ), {filter_kind: filter_value})
    assert select(grant, [grant.candidate], definition) == "wallet-current"


@pytest.mark.parametrize("candidates", [None, {}, "credentials", 7, [None], [7], [[]], [{}]])
def test_selector_denies_malformed_candidate_collections(grant, candidates):
    assert select(grant, candidates) is None


@pytest.mark.parametrize(("path", "value"), [
    (("record_id",), None), (("record_id",), 7), (("record_id",), []),
    (("credentialSubject",), None), (("credentialSubject",), []),
    (("credentialSubject",), "holder"), (("credentialSubject",), {}),
    (("issuer",), None), (("issuer",), {}),
    (("issuanceDate",), None), (("issuanceDate",), []),
    (("credentialSubject", "home"), None),
])
def test_selector_skips_malformed_candidate_and_finds_later_match(grant, path, value):
    bad = replace_at(grant.candidate, path, value)
    assert select(grant, [bad]) is None
    assert select(grant, [bad, grant.candidate]) == "wallet-current"


@pytest.mark.parametrize("variant", [
    "missing-descriptors", "no-descriptors", "extra-descriptor", "wrong-descriptor",
    "missing-fields", "three-fields", "five-fields", "reordered-fields",
    "wrong-path", "alternative-path", "missing-filter", "null-filter", "empty-enum",
    "null-enum", "wrong-const",
])
def test_selector_denies_invalid_or_unsatisfied_definitions(grant, variant):
    descriptor = grant.definition["input_descriptors"][0]
    fields = descriptor["constraints"]["fields"]
    field_variants = {
        "missing-fields": None, "three-fields": fields[:3],
        "five-fields": [*fields, fields[0]],
        "reordered-fields": [fields[1], fields[0], *fields[2:]],
        "wrong-path": [{**fields[0], "path": ["$.credentialSubject.issuer"]}, *fields[1:]],
        "alternative-path": [{**fields[0], "path": ["$.issuer", "$.issuer.id"]}, *fields[1:]],
        "missing-filter": [{"path": ["$.issuer"]}, *fields[1:]],
        "null-filter": [{**fields[0], "filter": None}, *fields[1:]],
        "empty-enum": [{**fields[0], "filter": {"enum": []}}, *fields[1:]],
        "null-enum": [{**fields[0], "filter": {"enum": None}}, *fields[1:]],
        "wrong-const": [{**fields[0], "filter": {"const": OTHER_HOLDER}}, *fields[1:]],
    }
    if variant == "missing-descriptors":
        definition = {}
    elif variant in ("no-descriptors", "extra-descriptor", "wrong-descriptor"):
        descriptors = {
            "no-descriptors": [], "extra-descriptor": [descriptor, descriptor],
            "wrong-descriptor": [{**descriptor, "id": "other-access"}],
        }[variant]
        definition = {**grant.definition, "input_descriptors": descriptors}
    else:
        definition = replace_at(grant.definition, (
            "input_descriptors", 0, "constraints", "fields",
        ), field_variants[variant])
    assert select(grant, [grant.candidate], definition) is None


async def invoke_acapy(operation, body):
    if operation == "send":
        return await acapy.send_proof_request(body)
    if operation == "get":
        return await acapy.get_proof_record(EXCHANGE)
    return await acapy.delete_proof_record(EXCHANGE)


def acapy_api(mock_http, operation, body, status, payload=None, key=ADMIN_KEY, error=None):
    calls = []
    method, path = {
        "send": ("POST", "/present-proof-2.0/send-request"),
        "get": ("GET", f"{RECORDS_PATH}/{EXCHANGE}"),
        "delete": ("DELETE", f"{RECORDS_PATH}/{EXCHANGE}"),
    }[operation]

    def handler(request):
        calls.append(request)
        assert_request(request, method, path, key=key)
        if operation == "send":
            assert json.loads(request.content) == body
        else:
            assert request.content == b""
        if error:
            raise error
        # Deletion must work without a JSON response, including an absent record.
        if operation == "delete":
            return httpx.Response(status)
        return httpx.Response(status, json=payload)

    mock_http(handler)
    return calls


@pytest.mark.parametrize("operation", ["send", "get", "delete"])
@pytest.mark.parametrize("key", [ADMIN_KEY, ""])
def test_acapy_proof_routes_headers_and_response(grant, mock_http, monkeypatch, operation, key):
    monkeypatch.setattr(config, "ACAPY_ADMIN_API_KEY", key)
    payload = {"pres_ex_id": EXCHANGE, "by_format": {"pres_request": {"dif": {"id": "kept"}}}}
    before = deepcopy(grant.body)
    calls = acapy_api(mock_http, operation, grant.body, 200, payload, key)
    result = asyncio.run(invoke_acapy(operation, grant.body))
    assert result == (None if operation == "delete" else payload)
    assert len(calls) == 1
    assert grant.body == before


@pytest.mark.parametrize("operation", ["send", "get", "delete"])
@pytest.mark.parametrize("status", [400, 401, 403, 409, 500, 503])
def test_acapy_proof_http_errors_propagate(grant, mock_http, operation, status):
    calls = acapy_api(mock_http, operation, grant.body, status, {"error": "rejected"})
    with pytest.raises(httpx.HTTPStatusError) as caught:
        asyncio.run(invoke_acapy(operation, grant.body))
    assert caught.value.response.status_code == status
    assert len(calls) == 1
    assert caught.value.request is calls[0]


@pytest.mark.parametrize("operation", ["send", "get"])
def test_acapy_404_propagates_except_during_cleanup(grant, mock_http, operation):
    acapy_api(mock_http, operation, grant.body, 404, {"error": "not found"})
    with pytest.raises(httpx.HTTPStatusError) as caught:
        asyncio.run(invoke_acapy(operation, grant.body))
    assert caught.value.response.status_code == 404


@pytest.mark.parametrize("status", [200, 204, 404])
def test_acapy_cleanup_accepts_empty_success_and_already_removed_record(grant, mock_http, status):
    calls = acapy_api(mock_http, "delete", grant.body, status)
    assert asyncio.run(acapy.delete_proof_record(EXCHANGE)) is None
    assert len(calls) == 1


@pytest.mark.parametrize("operation", ["send", "get", "delete"])
@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ReadTimeout])
def test_acapy_transport_errors_propagate_unchanged(grant, mock_http, operation, error_type):
    error = error_type("simulated transport failure")
    calls = acapy_api(mock_http, operation, grant.body, 200, error=error)
    with pytest.raises(error_type) as caught:
        asyncio.run(invoke_acapy(operation, grant.body))
    assert caught.value is error
    assert len(calls) == 1
