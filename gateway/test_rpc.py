import json
import unittest

import rpc


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


if __name__ == "__main__":
    unittest.main()
