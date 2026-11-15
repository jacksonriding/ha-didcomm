import json
import unittest

from ha_didcomm import rpc


class RpcTests(unittest.TestCase):
    def test_parses_home_assistant_request(self):
        request = rpc.parse_request(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "request-1",
                    "method": "homeassistant.call_service",
                    "params": {"action": "turn_on", "entity_id": "light.kitchen"},
                }
            )
        )
        self.assertEqual(request.entity_id, "light.kitchen")

    def test_rejects_legacy_and_unknown_method_requests(self):
        with self.assertRaisesRegex(rpc.RpcError, "Invalid Request"):
            rpc.parse_request('{"action":"turn_on","entity_id":"light.kitchen"}')
        with self.assertRaises(rpc.RpcError) as context:
            rpc.parse_request(
                '{"jsonrpc":"2.0","id":1,"method":"unknown","params":{}}'
            )
        self.assertEqual(context.exception.code, -32601)

    def test_formats_success_and_error_responses(self):
        self.assertTrue(json.loads(rpc.success(1))["result"]["executed"])
        response = json.loads(rpc.failure(rpc.RpcError(-32001, "Denied", 1)))
        self.assertEqual(response["error"]["code"], -32001)

    def test_rejects_actions_that_can_change_the_home_assistant_url(self):
        for action in (
            "../homeassistant/restart",
            "%2e%2e%2fhomeassistant%2frestart",
            "turn_on/extra",
            "turn_on?unexpected=1",
            "turn_on#fragment",
            "turn_on\\extra",
            "turn_on\n",
        ):
            with self.subTest(action=action):
                with self.assertRaises(rpc.RpcError) as context:
                    rpc.parse_request(json.dumps({
                        "jsonrpc": "2.0",
                        "id": "invalid-action",
                        "method": "homeassistant.call_service",
                        "params": {"action": action, "entity_id": "light.kitchen"},
                    }))
                self.assertEqual(context.exception.code, -32602)
                self.assertEqual(context.exception.request_id, "invalid-action")

    def test_rejects_malformed_entity_identifiers(self):
        for entity_id in (
            "../light.kitchen",
            "light/../homeassistant.kitchen",
            "light%2fother.kitchen",
            "light?query.kitchen",
            "light#fragment.kitchen",
            ".kitchen",
            "light.",
            "light.kitchen.extra",
            "light.kitchen\n",
        ):
            with self.subTest(entity_id=entity_id):
                with self.assertRaises(rpc.RpcError) as context:
                    rpc.parse_request(json.dumps({
                        "jsonrpc": "2.0",
                        "id": "invalid-entity",
                        "method": "homeassistant.call_service",
                        "params": {"action": "turn_on", "entity_id": entity_id},
                    }))
                self.assertEqual(context.exception.code, -32602)
                self.assertEqual(context.exception.request_id, "invalid-entity")

    def test_accepts_service_and_entity_names_with_digits_and_underscores(self):
        request = rpc.parse_request(json.dumps({
            "jsonrpc": "2.0",
            "id": "valid-identifiers",
            "method": "homeassistant.call_service",
            "params": {"action": "turn_on", "entity_id": "input_boolean.guest_2"},
        }))
        self.assertEqual(request.action, "turn_on")
        self.assertEqual(request.entity_id, "input_boolean.guest_2")


if __name__ == "__main__":
    unittest.main()
