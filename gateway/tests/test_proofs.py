"""TDD contract for gateway proof possession and command replay protection.

The LD-proof fixtures have realistic signed-document shapes, but their JWS
values are inert test data. ACA-Py's verified result is a trust boundary here;
these tests do not verify signatures or claim that mocked ACA-Py does so.
"""

import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch
from uuid import RFC_4122, UUID

from ha_didcomm import proofs
from ha_didcomm import acapy, config, credentials, rpc
import httpx


CONNECTION = "connection-1"
EXCHANGE = "proof-exchange-1"
FINGERPRINT = "z6MkiTBz1ymuepAQ4HEHYSF3VKrqs8v9wZcJ5aZ3cX1UjhWb"
SUBJECT = "did:key:" + FINGERPRINT
ISSUER = "did:key:z6MkrJVnaZkeFzdQyMZu7cHFh1GgJoTPqHwN1CpRYkGryhC4"
JWS = "eyJhbGciOiJFZERTQSIsImI2NCI6ZmFsc2UsImNyaXQiOlsiYjY0Il19.." + "A" * 86
MISSING = object()


def changed(document, path, value=MISSING):
    """Return a fixture variant without changing the original document."""
    result = deepcopy(document)
    target = result
    for key in path[:-1]:
        target = target[key]
    if value is MISSING:
        del target[path[-1]]
    else:
        target[path[-1]] = deepcopy(value)
    return result


class StoreFixture:
    def setUp(self):
        super().setUp()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store_path = str(Path(directory.name) / "credentials.sqlite3")
        for name, value in (
            ("CREDENTIAL_STORE_PATH", self.store_path),
            ("HOME_ID", "proof-test-home"),
            ("HOME_ISSUER_DID", ISSUER),
        ):
            self.enterContext(patch.object(config, name, value))
        self.request = rpc.Request("command-1", "turn_on", "light.guest_room")
        self.issued = self.credential()

    def credential(self, permissions=None, expires=None):
        return credentials.build_credential(
            SUBJECT, ISSUER, "guest",
            ["light.guest_*"] if permissions is None else permissions,
            expires_iso=expires,
        )

    def signed_credential(self):
        return {
            **deepcopy(self.issued),
            "proof": {
                "type": "Ed25519Signature2018",
                "created": "2026-09-13T00:00:00Z",
                "proofPurpose": "assertionMethod",
                "verificationMethod": ISSUER + "#" + ISSUER.removeprefix("did:key:"),
                "jws": JWS,
            },
        }

    def record(self, dif_request, *, verified="true", as_list=False):
        definition = dif_request["presentation_definition"]
        presentation = {
            "@context": ["https://www.w3.org/2018/credentials/v1"],
            "type": ["VerifiablePresentation"],
            "holder": SUBJECT,
            "verifiableCredential": [self.signed_credential()],
            "presentation_submission": {
                "id": "submission-1",
                "definition_id": definition["id"],
                "descriptor_map": [
                    {
                        "id": descriptor["id"],
                        "format": "ldp_vc",
                        "path": "$.verifiableCredential[0]",
                    }
                    for descriptor in definition.get("input_descriptors", [])
                ],
            },
            "proof": {
                "type": "Ed25519Signature2018",
                "created": "2026-09-13T00:00:00Z",
                "proofPurpose": "authentication",
                "verificationMethod": SUBJECT + "#" + FINGERPRINT,
                "challenge": dif_request["options"]["challenge"],
                "jws": JWS,
            },
        }
        return {
            "connection_id": CONNECTION,
            "pres_ex_id": EXCHANGE,
            "role": "verifier",
            "state": "done",
            "verified": verified,
            "by_format": {
                "pres_request": {"dif": deepcopy(dif_request)},
                "pres": {"dif": [presentation] if as_list else presentation},
            },
        }


class BuildRequestTests(StoreFixture, unittest.TestCase):
    def assert_uuid4(self, value):
        self.assertIsInstance(value, str)
        parsed = UUID(value)
        self.assertEqual(str(parsed), value)
        self.assertEqual(parsed.version, 4)
        self.assertEqual(parsed.variant, RFC_4122)

    def test_pp2_body_and_rpc_definition_binding(self):
        body = proofs.build_request(CONNECTION, self.request)
        self.assertEqual(body["connection_id"], CONNECTION)
        self.assertIs(body["auto_verify"], True)
        self.assertIs(body["auto_remove"], False)
        dif = body["presentation_request"]["dif"]
        self.assertEqual(
            dif["presentation_definition"]["id"], rpc.proof_request_id(self.request)
        )
        self.assertEqual(set(dif["options"]), {"challenge"})
        self.assert_uuid4(dif["options"]["challenge"])
        self.assert_uuid4(dif["presentation_definition"]["id"])

    def test_each_attempt_has_a_fresh_challenge_even_for_the_same_rpc(self):
        bodies = [proofs.build_request(CONNECTION, self.request) for _ in range(32)]
        challenges = {
            body["presentation_request"]["dif"]["options"]["challenge"]
            for body in bodies
        }
        self.assertEqual(len(challenges), 32)
        for challenge in challenges:
            self.assert_uuid4(challenge)

    def test_challenge_context_changes_with_home_issuer_and_command_under_fixed_nonce(self):
        def challenge(request):
            return proofs.build_request(CONNECTION, request)[
                "presentation_request"
            ]["dif"]["options"]["challenge"]

        nonce = self.enterContext(patch(
            "ha_didcomm.proofs.secrets.token_bytes", return_value=b"\x11" * 32
        ))
        challenges = [challenge(self.request)]
        self.assertEqual(challenge(self.request), challenges[0])
        with patch.object(config, "HOME_ID", "another-home"):
            challenges.append(challenge(self.request))
        with patch.object(config, "HOME_ISSUER_DID", SUBJECT):
            challenges.append(challenge(self.request))
        for request in (
            rpc.Request("command-1", "turn_off", "light.guest_room"),
            rpc.Request("command-1", "turn_on", "lock.front_door"),
            rpc.Request(7, "turn_on", "light.guest_room"),
            rpc.Request("7", "turn_on", "light.guest_room"),
        ):
            challenges.append(challenge(request))
        self.assertEqual(len(set(challenges)), len(challenges))
        self.assertEqual(nonce.call_count, len(challenges) + 1)
        for call in nonce.call_args_list:
            self.assertEqual(call.args, (32,))
        for value in challenges:
            self.assert_uuid4(value)

    def test_presentation_definition_id_is_deterministic_and_binds_typed_command(self):
        requests = (
            self.request,
            rpc.Request("command-1", "turn_off", "light.guest_room"),
            rpc.Request("command-1", "turn_on", "lock.front_door"),
            rpc.Request(7, "turn_on", "light.guest_room"),
            rpc.Request("7", "turn_on", "light.guest_room"),
        )
        identifiers = [rpc.proof_request_id(request) for request in requests]
        self.assertEqual(len(set(identifiers)), len(requests))
        for request, identifier in zip(requests, identifiers):
            self.assert_uuid4(identifier)
            self.assertEqual(rpc.proof_request_id(request), identifier)
            body = proofs.build_request(CONNECTION, request)
            self.assertEqual(body["presentation_request"]["dif"]["presentation_definition"]["id"], identifier)

    def test_filters_use_primitive_values_for_the_local_authorised_grant(self):
        credentials.remember_issued(CONNECTION, self.issued, "eligible")
        credentials.remember_issued(CONNECTION, self.credential(["lock.*"]), "wrong-entity")
        credentials.remember_issued("other", self.credential(), "wrong-connection")
        definition = proofs.build_request(CONNECTION, self.request)[
            "presentation_request"
        ]["dif"]["presentation_definition"]
        fields = [field for descriptor in definition["input_descriptors"]
                  for field in descriptor["constraints"]["fields"]]
        filters = {path: field["filter"] for field in fields for path in field["path"]}
        self.assertEqual(filters["$.issuer"], {"const": ISSUER})
        self.assertEqual(filters["$.credentialSubject.home"], {"const": config.HOME_ID})
        for path, expected in (
            ("$.credentialSubject.id", SUBJECT),
            ("$.issuanceDate", self.issued["issuanceDate"]),
        ):
            self.assertEqual(filters[path], {"enum": [expected]})
            self.assertTrue(all(isinstance(value, str) for value in filters[path]["enum"]))


class PresentedCredentialTests(StoreFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.dif = proofs.build_request(CONNECTION, self.request)[
            "presentation_request"
        ]["dif"]
        self.valid = self.record(self.dif)

    def validate(self, record):
        return proofs.valid_presented_credential(
            record, CONNECTION, EXCHANGE, self.dif
        )

    def test_accepts_dict_and_single_item_list_with_exact_verified_values(self):
        for verified in ("true", True):
            for as_list in (False, True):
                with self.subTest(verified=verified, as_list=as_list):
                    record = self.record(self.dif, verified=verified, as_list=as_list)
                    before = deepcopy(record)
                    self.assertEqual(self.validate(record), self.signed_credential())
                    self.assertEqual(record, before)

    def test_holder_is_optional_when_signer_matches_credential_subject(self):
        record = changed(self.valid, ("by_format", "pres", "dif", "holder"))
        self.assertEqual(self.validate(record), self.signed_credential())

    def test_rejects_false_and_truthy_non_boolean_verification_results(self):
        for value in (False, "false", None, 0, 1, "True", "TRUE", " true ", {}, []):
            with self.subTest(verified=value):
                self.assertIsNone(self.validate(changed(self.valid, ("verified",), value)))
        self.assertIsNone(self.validate(changed(self.valid, ("verified",))))

    def test_rejects_wrong_or_missing_exchange_metadata(self):
        for key, wrong in (
            ("connection_id", "other-connection"),
            ("pres_ex_id", "other-exchange"),
            ("role", "prover"),
            ("state", "presentation-received"),
        ):
            for value in (wrong, None, [], MISSING):
                with self.subTest(key=key, value=value):
                    self.assertIsNone(self.validate(changed(self.valid, (key,), value)))

    def test_rejects_unsigned_and_tampered_presentation_metadata(self):
        prefix = ("by_format", "pres", "dif", "proof")
        for value in (MISSING, None, {}, [], "not-a-proof"):
            with self.subTest(proof=value):
                self.assertIsNone(self.validate(changed(self.valid, prefix, value)))
        for field, wrong in (
            ("type", "Ed25519Signature2020"),
            ("proofPurpose", "assertionMethod"),
            ("challenge", "replayed-challenge"),
        ):
            for value in (wrong, MISSING, None, []):
                with self.subTest(field=field, value=value):
                    self.assertIsNone(
                        self.validate(changed(self.valid, (*prefix, field), value))
                    )

    def test_rejects_wrong_signer_or_fragment_even_if_acapy_says_verified(self):
        path = ("by_format", "pres", "dif", "proof", "verificationMethod")
        for value in (
            ISSUER + "#" + ISSUER.removeprefix("did:key:"),
            SUBJECT, SUBJECT + "#wrong-key", SUBJECT + "#" + FINGERPRINT + "extra",
            None, {}, [], MISSING,
        ):
            with self.subTest(verification_method=value):
                self.assertIsNone(self.validate(changed(self.valid, path, value)))

    def test_rejects_present_but_mismatched_or_malformed_holder(self):
        for holder in (ISSUER, "", None, {}, [SUBJECT]):
            with self.subTest(holder=holder):
                self.assertIsNone(self.validate(changed(
                    self.valid, ("by_format", "pres", "dif", "holder"), holder
                )))

    def test_rejects_non_key_or_malformed_credential_subject(self):
        path = ("by_format", "pres", "dif", "verifiableCredential", 0)
        for subject in (None, [], {}, "subject", {"id": None}, {"id": ISSUER}):
            with self.subTest(subject=subject):
                self.assertIsNone(self.validate(changed(
                    self.valid, (*path, "credentialSubject"), subject
                )))
        record = changed(self.valid, (*path, "credentialSubject", "id"), "did:web:guest")
        record = changed(record, ("by_format", "pres", "dif", "holder"), "did:web:guest")
        record = changed(record, (
            "by_format", "pres", "dif", "proof", "verificationMethod"
        ), "did:web:guest#guest")
        self.assertIsNone(self.validate(record))

    def test_rejects_request_mismatch_including_definition_and_extra_fields(self):
        variants = [
            changed(self.dif, ("options", "challenge"), "another-challenge"),
            changed(self.dif, ("presentation_definition", "id"), "another-rpc"),
            {**self.dif, "unexpected": True},
            None, {}, [],
        ]
        for dif in variants:
            with self.subTest(dif=dif):
                record = changed(self.valid, ("by_format", "pres_request", "dif"), dif)
                self.assertIsNone(self.validate(record))

    def test_requires_submission_definition_id_to_match_requested_definition(self):
        path = ("by_format", "pres", "dif", "presentation_submission")
        for value in (MISSING, None, {}, [], "submission"):
            with self.subTest(submission=value):
                self.assertIsNone(self.validate(changed(self.valid, path, value)))
        for value in (MISSING, None, "another-command", [], 1):
            with self.subTest(definition_id=value):
                self.assertIsNone(self.validate(changed(
                    self.valid, (*path, "definition_id"), value
                )))

    def test_rejects_malformed_record_envelopes_without_raising(self):
        for record in (None, False, 1, "record", [], [{}], {}):
            with self.subTest(record=record):
                self.assertIsNone(self.validate(record))
        for path in (
            ("by_format",), ("by_format", "pres_request"),
            ("by_format", "pres_request", "dif"), ("by_format", "pres"),
            ("by_format", "pres", "dif"),
        ):
            for value in (MISSING, None, {}, [], "malformed", 1):
                with self.subTest(path=path, value=value):
                    self.assertIsNone(self.validate(changed(self.valid, path, value)))

    def test_requires_exactly_one_presentation_and_one_dictionary_credential(self):
        vp = self.valid["by_format"]["pres"]["dif"]
        for value in ([], [vp, vp], [None], [1], [[vp]]):
            with self.subTest(presentations=value):
                self.assertIsNone(self.validate(changed(
                    self.valid, ("by_format", "pres", "dif"), value
                )))
        vc = self.signed_credential()
        for value in (MISSING, None, [], [vc, vc], [None], ["vc"], [[]], vc):
            with self.subTest(credentials=value):
                self.assertIsNone(self.validate(changed(
                    self.valid, ("by_format", "pres", "dif", "verifiableCredential"), value
                )))


class RequestProofTests(StoreFixture, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.send = self.enterContext(patch.object(acapy, "send_proof_request", new_callable=AsyncMock))
        self.get = self.enterContext(patch.object(acapy, "get_proof_record", new_callable=AsyncMock))
        self.delete = self.enterContext(patch.object(acapy, "delete_proof_record", new_callable=AsyncMock))
        self.send.return_value = {"pres_ex_id": EXCHANGE}
        self.delete.return_value = None

    def sent_record(self):
        body = self.send.call_args.args[0]
        return self.record(body["presentation_request"]["dif"])

    async def bounded_request(self):
        # A failing implementation must not make this unit suite wait 30 seconds.
        return await asyncio.wait_for(proofs.request_proof(CONNECTION, self.request), 2)

    async def test_default_timeout_is_thirty_seconds(self):
        self.assertEqual(proofs.PROOF_TIMEOUT, 30)

    async def test_sends_bound_request_polls_and_deletes_successful_exchange(self):
        def fetched(_exchange):
            record = self.sent_record()
            if self.get.await_count == 1:
                return {**record, "state": "request-sent", "verified": None}
            return record

        self.get.side_effect = fetched
        self.assertEqual(await self.bounded_request(), self.signed_credential())
        self.send.assert_awaited_once()
        body = self.send.call_args.args[0]
        self.assertEqual(body["connection_id"], CONNECTION)
        self.assertIs(body["auto_verify"], True)
        self.assertIs(body["auto_remove"], False)
        self.assertEqual(body["presentation_request"]["dif"]["presentation_definition"]["id"],
                         rpc.proof_request_id(self.request))
        self.assertGreaterEqual(self.get.await_count, 2)
        for call in self.get.await_args_list:
            self.assertEqual(call.args, (EXCHANGE,))
        self.delete.assert_awaited_once_with(EXCHANGE)

    async def test_rejected_completed_proof_fails_closed_and_is_deleted(self):
        variants = (
            (("verified",), "false"),
            (("connection_id",), "other"),
            (("by_format", "pres", "dif", "proof"), MISSING),
            (("by_format", "pres", "dif", "proof", "challenge"), "wrong"),
            (("by_format", "pres", "dif", "presentation_submission", "definition_id"), "wrong"),
            (("by_format", "pres_request", "dif", "presentation_definition", "id"), "wrong"),
        )
        for path, value in variants:
            with self.subTest(path=path):
                self.delete.reset_mock()
                self.get.side_effect = lambda _id: changed(self.sent_record(), path, value)
                self.assertIsNone(await self.bounded_request())
                self.delete.assert_awaited_once_with(EXCHANGE)

    async def test_malformed_send_response_never_polls_an_untrusted_id(self):
        for response in (None, [], "record", {}, {"pres_ex_id": None},
                         {"pres_ex_id": ""}, {"pres_ex_id": []}, {"pres_ex_id": 1}):
            with self.subTest(response=response):
                self.send.return_value = response
                self.get.reset_mock()
                self.delete.reset_mock()
                self.assertIsNone(await self.bounded_request())
                self.get.assert_not_awaited()
                self.delete.assert_not_awaited()

    async def test_malformed_poll_records_fail_closed_and_are_deleted(self):
        for record in (None, [], "record", {"state": "done"}):
            with self.subTest(record=record):
                self.get.return_value = record
                self.delete.reset_mock()
                with patch.object(proofs, "PROOF_TIMEOUT", 0.01):
                    self.assertIsNone(await self.bounded_request())
                self.delete.assert_awaited_once_with(EXCHANGE)

    async def test_pending_exchange_times_out_and_is_deleted(self):
        self.get.side_effect = lambda _id: {
            **self.sent_record(), "state": "request-sent", "verified": None
        }
        with patch.object(proofs, "PROOF_TIMEOUT", 0.01):
            self.assertIsNone(await self.bounded_request())
        self.get.assert_awaited()
        self.delete.assert_awaited_once_with(EXCHANGE)

    async def test_send_failure_fails_closed_without_deleting_unknown_exchange(self):
        self.send.side_effect = httpx.ConnectError("ACA-Py unavailable")
        self.assertIsNone(await self.bounded_request())
        self.get.assert_not_awaited()
        self.delete.assert_not_awaited()

    async def test_poll_failure_fails_closed_and_deletes_known_exchange(self):
        self.get.side_effect = httpx.ConnectError("ACA-Py unavailable")
        self.assertIsNone(await self.bounded_request())
        self.delete.assert_awaited_once_with(EXCHANGE)

    async def test_cleanup_failure_does_not_escape_or_authorise_rejected_proof(self):
        self.get.side_effect = lambda _id: {**self.sent_record(), "verified": False}
        self.delete.side_effect = httpx.ConnectError("ACA-Py unavailable")
        self.assertIsNone(await self.bounded_request())
        self.delete.assert_awaited_once_with(EXCHANGE)


# Each invocation imports proofs in a new interpreter. Freezing both standard
# wall-clock APIs before import avoids depending on a private schema or clock
# helper while exercising the actual SQLite store and its 24-hour retention.
RESERVATION_WORKER = """
import datetime
import json
import sys
import time
from unittest.mock import patch
from ha_didcomm import config

store_path, clock, operations = json.loads(sys.argv[1])
config.CREDENTIAL_STORE_PATH = store_path
RealDateTime = datetime.datetime

class FrozenDateTime(RealDateTime):
    @classmethod
    def now(cls, tz=None):
        return cls.fromtimestamp(clock, tz)

    @classmethod
    def utcnow(cls):
        return cls.fromtimestamp(clock, datetime.timezone.utc).replace(tzinfo=None)

with patch.object(time, 'time', return_value=clock), patch.object(datetime, 'datetime', FrozenDateTime):
    from ha_didcomm import proofs, rpc
    results = []
    for operation, connection_id, request_id in operations:
        request = rpc.Request(request_id, 'turn_on', 'light.guest_room')
        if operation == 'claim':
            results.append(proofs.claim_command(connection_id, request))
        else:
            proofs.finish_command(connection_id, request)
            results.append(None)
    print(json.dumps(results))
"""


class CommandReservationTests(StoreFixture, unittest.TestCase):
    def worker(self, clock, operations):
        source = str(Path(__file__).resolve().parents[1] / "src")
        environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
                       "PYTHONPATH": os.pathsep.join(filter(None, (source, os.environ.get("PYTHONPATH"))))}
        result = subprocess.run(
            [sys.executable, "-B", "-c", RESERVATION_WORKER,
             json.dumps([self.store_path, clock, operations])],
            env=environment, capture_output=True, text=True, timeout=10, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_duplicate_rpc_is_rejected_across_calls_and_changed_payloads(self):
        self.assertIs(proofs.claim_command(CONNECTION, self.request), True)
        self.assertIs(proofs.claim_command(CONNECTION, self.request), False)
        changed_payload = rpc.Request(self.request.request_id, "turn_off", "lock.front_door")
        self.assertIs(proofs.claim_command(CONNECTION, changed_payload), False)

    def test_integer_and_string_rpc_ids_are_distinct_and_connection_scoped(self):
        for connection_id, request_id in ((CONNECTION, 7), (CONNECTION, "7"), ("other", 7)):
            request = rpc.Request(request_id, "turn_on", "light.guest_room")
            with self.subTest(connection=connection_id, request_id=request_id):
                self.assertIs(proofs.claim_command(connection_id, request), True)
                self.assertIs(proofs.claim_command(connection_id, request), False)

    def test_maximum_32_pending_and_finishing_frees_capacity_but_keeps_replay_guard(self):
        requests = [rpc.Request(index, "turn_on", "light.guest_room") for index in range(33)]
        for request in requests[:32]:
            self.assertIs(proofs.claim_command(CONNECTION, request), True)
        self.assertIs(proofs.claim_command(CONNECTION, requests[32]), False)
        proofs.finish_command(CONNECTION, requests[0])
        proofs.finish_command(CONNECTION, requests[0])
        self.assertIs(proofs.claim_command(CONNECTION, requests[0]), False)
        self.assertIs(proofs.claim_command(CONNECTION, requests[32]), True)

    def test_finish_only_releases_the_matching_connection_and_typed_id(self):
        for index in range(32):
            self.assertIs(proofs.claim_command(CONNECTION, rpc.Request(index, "turn_on", "light.guest_room")), True)
        extra = rpc.Request(32, "turn_on", "light.guest_room")
        proofs.finish_command("other", rpc.Request(0, "turn_on", "light.guest_room"))
        proofs.finish_command(CONNECTION, rpc.Request("0", "turn_on", "light.guest_room"))
        self.assertIs(proofs.claim_command(CONNECTION, extra), False)

    def test_reservations_survive_fresh_processes_in_sqlite(self):
        now = time.time()
        self.assertEqual(self.worker(now, [("claim", CONNECTION, 7)]), [True])
        self.assertEqual(self.worker(now + 1, [("claim", CONNECTION, 7), ("claim", CONNECTION, "7")]), [False, True])
        with open(self.store_path, "rb") as database:
            self.assertEqual(database.read(16), b"SQLite format 3\x00")

    def test_finished_rpc_is_retained_for_24_hours_then_can_be_claimed(self):
        now = time.time()
        self.assertEqual(self.worker(now, [("claim", CONNECTION, "retained"), ("finish", CONNECTION, "retained")]), [True, None])
        self.assertEqual(self.worker(now + 24 * 3600 - 1, [("claim", CONNECTION, "retained")]), [False])
        self.assertEqual(self.worker(now + 24 * 3600 + 1, [("claim", CONNECTION, "retained")]), [True])

    def test_expired_pending_reservations_no_longer_consume_capacity(self):
        now = time.time()
        self.assertEqual(self.worker(now, [("claim", CONNECTION, index) for index in range(32)]), [True] * 32)
        self.assertEqual(self.worker(now + 24 * 3600 + 1, [("claim", CONNECTION, "new")]), [True])


class PresentedAuthorisationTests(StoreFixture, unittest.TestCase):
    def authorised(self, credential, entity="light.guest_room", connection=CONNECTION):
        return credentials.is_presented_authorised(connection, entity, credential)

    def test_exact_locally_issued_credential_matches_excluding_top_level_proof(self):
        issued = self.credential()
        credentials.remember_issued(CONNECTION, issued, "issued-1")
        presented = {**issued, "proof": self.signed_credential()["proof"]}
        before = deepcopy(presented)
        self.assertIs(self.authorised(presented), True)
        self.assertEqual(presented, before)
        # A stored signed credential may carry a different top-level proof too.
        credentials.remember_issued("signed-connection", {**issued, "proof": {"jws": "stored"}}, "issued-2")
        self.assertIs(self.authorised(presented, connection="signed-connection"), True)

    def test_unissued_credential_and_other_connections_are_denied(self):
        vc = self.signed_credential()
        self.assertIs(self.authorised(vc), False)
        credentials.remember_issued(CONNECTION, vc, "issued-1")
        self.assertIs(self.authorised(vc, connection="other"), False)

    def test_narrow_presented_grant_cannot_unlock_a_broader_stored_grant(self):
        narrow = self.credential(["light.guest_room"])
        broad = self.credential(["light.*", "lock.*"])
        credentials.remember_issued(CONNECTION, narrow, "narrow")
        credentials.remember_issued(CONNECTION, broad, "broad")
        self.assertIs(self.authorised(narrow), True)
        self.assertIs(self.authorised(broad, entity="lock.front_door"), True)
        self.assertIs(self.authorised(narrow, entity="lock.front_door"), False)

    def test_all_non_proof_fields_must_match_local_issuance_exactly(self):
        issued = self.credential()
        credentials.remember_issued(CONNECTION, issued, "issued-1")
        for path, value in (
            (("issuer",), SUBJECT),
            (("issuanceDate",), "2020-01-01T00:00:00Z"),
            (("expirationDate",), "2099-01-01T00:00:00Z"),
            (("type",), ["VerifiableCredential"]),
            (("@context",), ["https://www.w3.org/2018/credentials/v1"]),
            (("credentialSubject", "id"), ISSUER),
            (("credentialSubject", "home"), "other-home"),
            (("credentialSubject", "role"), "admin"),
            (("credentialSubject", "permissions"), ["*"]),
            (("credentialSubject", "proof"), {"unexpected": True}),
            (("extra",), True),
        ):
            with self.subTest(path=path):
                self.assertIs(self.authorised(changed(issued, path, value)), False)

    def test_revoked_presented_grant_cannot_fall_back_to_another_active_grant(self):
        revoked = self.credential(["light.guest_room"])
        credentials.remember_issued(CONNECTION, revoked, "revoked")
        credentials.remember_issued(CONNECTION, self.credential(["light.*"]), "active")
        self.assertTrue(credentials.revoke_credential("revoked"))
        self.assertIs(self.authorised(revoked), False)

    def test_expired_or_invalid_expiry_cannot_fall_back_to_active_grant(self):
        credentials.remember_issued(CONNECTION, self.credential(["light.*"]), "active")
        for index, expiry in enumerate(("2000-01-01T00:00:00Z", "not-a-date", "2099-01-01T00:00:00")):
            with self.subTest(expiry=expiry):
                vc = self.credential(expires=expiry)
                credentials.remember_issued(CONNECTION, vc, f"expired-{index}")
                self.assertIs(self.authorised(vc), False)

    def test_malformed_presented_credentials_fail_closed(self):
        credentials.remember_issued(CONNECTION, self.credential(["*"]), "active")
        for vc in (None, False, 1, "vc", [], {}, {"credentialSubject": []}):
            with self.subTest(vc=vc):
                self.assertIs(self.authorised(vc), False)


if __name__ == "__main__":
    unittest.main()
