from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from qcmc_logic.api.delivery_trip_route import _get_stop_points_without_save


class DeliveryStop(dict):
	def __init__(self, **values):
		super().__init__(values)
		self.meta = SimpleNamespace(has_field=lambda fieldname: True)

	def __setattr__(self, name, value):
		if name == "meta":
			return super().__setattr__(name, value)
		self[name] = value


class TestDeliveryTripRoute(TestCase):
	def test_stop_resolution_does_not_save_trip(self):
		row = DeliveryStop(address_name="ADDR-001", customer="CUST-001")
		trip = SimpleNamespace(delivery_stops=[row], save=Mock())
		route_module = SimpleNamespace(
			_get_or_create_coords_from_address=Mock(return_value=(14.5, 121.0)),
		)

		points, rows = _get_stop_points_without_save(trip, route_module)

		self.assertEqual(points, [(14.5, 121.0)])
		self.assertEqual(rows, [row])
		self.assertEqual(row["custom_latitude"], 14.5)
		self.assertEqual(row["custom_longitude"], 121.0)
		trip.save.assert_not_called()
