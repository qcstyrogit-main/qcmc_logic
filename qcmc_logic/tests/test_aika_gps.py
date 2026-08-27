import json
from unittest import TestCase
from unittest.mock import Mock

from qcmc_logic.integrations.aika_gps import AikaError, AikaReadOnlyClient, parse_aika_response, validate_aika_url


class TestAikaGPS(TestCase):
	def test_host_allowlist(self):
		self.assertEqual(validate_aika_url("http://app.aika168.com:8088/openapiv3.asmx"), "http://app.aika168.com:8088/openapiv3.asmx")
		with self.assertRaises(AikaError):
			validate_aika_url("http://example.com/openapiv3.asmx")

	def test_embedded_credentials_are_rejected(self):
		with self.assertRaises(AikaError):
			validate_aika_url("http://user:password@app.aika168.com/openapiv3.asmx")

	def test_xml_wrapped_json_response(self):
		payload = {"lat": 14.5, "lng": 121.0, "speed": 20}
		response = f"<string>{json.dumps(payload)}</string>"
		self.assertEqual(parse_aika_response(response), payload)

	def test_client_has_no_command_method(self):
		client = AikaReadOnlyClient()
		self.addCleanup(client.client.close)
		self.assertFalse(hasattr(client, "send_command"))

	def test_login_uses_philippine_timezone(self):
		client = AikaReadOnlyClient()
		self.addCleanup(client.client.close)
		client._post = Mock(return_value={"deviceInfo": {"deviceID": 1, "deviceName": "Truck", "model": 2, "key2018": "secret"}})
		client.login("account", "password")
		payload = client._post.call_args.args[1]
		self.assertEqual(payload["GMT"], "8:00")

	def test_account_login_returns_device_list(self):
		client = AikaReadOnlyClient()
		self.addCleanup(client.client.close)
		client._post = Mock(side_effect=[
			{"state": "0", "userInfo": {"userID": 7, "key2018": "session"}},
			{"state": "0", "arr": [{"id": 12, "name": "TRD 189", "model": 2, "sn": "9175539049"}]},
		])
		devices = client.login_account("account", "password")
		self.assertEqual(devices[0].device_id, "12")
		self.assertEqual(devices[0].device_name, "TRD 189")
		self.assertEqual(devices[0].id_number, "9175539049")
		self.assertEqual(client._post.call_args.args[0], "GetDeviceList")
