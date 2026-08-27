frappe.ui.form.on("Delivery Trip", {
	refresh(frm) {
		clearInterval(frm.__aika_gps_timer);
		frm.__aika_gps_timer = null;
		remove_live_vehicle_marker(frm);
		remove_fleet_traffic_layer(frm);
		if (frm.__aika_realtime_handler) frappe.realtime.off("qcmc_delivery_trip_gps", frm.__aika_realtime_handler);

		if (frm.is_new() || !frm.doc.vehicle) return;

		frm.add_custom_button(__("Center Live Vehicle"), async () => {
			const position = await refresh_live_vehicle(frm, true);
			if (!position?.available) {
				frappe.msgprint(position?.reason || __("No live GPS position is available."));
			}
		}, __("GPS"));
		frm.add_custom_button(__("Toggle Fleet Traffic"), async () => {
			if (frm.__fleet_traffic_visible) {
				remove_fleet_traffic_layer(frm);
			} else {
				await refresh_fleet_traffic(frm);
			}
		}, __("GPS"));
		frm.add_custom_button(__("Follow Vehicle"), () => {
			frm.__aika_follow_vehicle = !frm.__aika_follow_vehicle;
			frappe.show_alert({
				message: frm.__aika_follow_vehicle ? __("Following live Vehicle") : __("Vehicle follow disabled"),
				indicator: frm.__aika_follow_vehicle ? "green" : "gray"
			});
		}, __("GPS"));

		frm.__aika_realtime_handler = (message) => {
			if (message?.delivery_trip !== frm.doc.name) return;
			refresh_live_vehicle(frm, Boolean(frm.__aika_follow_vehicle));
		};
		frappe.realtime.on("qcmc_delivery_trip_gps", frm.__aika_realtime_handler);

		setTimeout(() => refresh_live_vehicle(frm, false), 800);
		setTimeout(() => refresh_fleet_traffic(frm), 1100);
		request_live_vehicle_update(frm);
		frm.__aika_gps_timer = setInterval(() => request_live_vehicle_update(frm), 15000);
		frm.__fleet_traffic_timer = setInterval(() => refresh_fleet_traffic(frm), 60000);
	},

	before_load(frm) {
		clearInterval(frm.__aika_gps_timer);
		clearInterval(frm.__fleet_traffic_timer);
		if (frm.__aika_realtime_handler) frappe.realtime.off("qcmc_delivery_trip_gps", frm.__aika_realtime_handler);
	}
});

async function request_live_vehicle_update(frm) {
	try {
		await frappe.call({
			method: "qcmc_logic.api.delivery_trip_route.request_live_vehicle_update",
			args: { delivery_trip: frm.doc.name }, quiet: true
		});
	} catch (e) {
		console.warn("Unable to queue live GPS update", e);
	}
}

function remove_live_vehicle_marker(frm) {
	if (frm.__aika_vehicle_marker) {
		try { frm.__aika_vehicle_marker.remove(); } catch (e) {}
		frm.__aika_vehicle_marker = null;
	}
}

function remove_fleet_traffic_layer(frm) {
	clearInterval(frm.__fleet_traffic_timer);
	if (frm.__fleet_traffic_layer) {
		try { frm.__fleet_traffic_layer.remove(); } catch (e) {}
		frm.__fleet_traffic_layer = null;
	}
	if (frm.__fleet_traffic_legend) {
		try { frm.__fleet_traffic_legend.remove(); } catch (e) {}
		frm.__fleet_traffic_legend = null;
	}
	frm.__fleet_traffic_visible = false;
}

function traffic_color(level) {
	return level === "heavy" ? "#dc2626" : level === "slow" ? "#f59e0b" : "#16a34a";
}

function route_lines_from_geojson(raw) {
	if (!(raw || "").trim()) return [];
	let geo;
	try { geo = JSON.parse(raw); } catch (e) { return []; }
	const lines = [];
	function visit(item) {
		if (!item) return;
		if (item.type === "FeatureCollection") return (item.features || []).forEach(visit);
		if (item.type === "Feature") return visit(item.geometry);
		if (item.type === "GeometryCollection") return (item.geometries || []).forEach(visit);
		if (item.type === "LineString") lines.push(item.coordinates || []);
		if (item.type === "MultiLineString") (item.coordinates || []).forEach(line => lines.push(line));
	}
	visit(geo);
	return lines.filter(line => line.length > 1);
}

function point_segment_distance_m(point, first, second) {
	const referenceLat = point[0] * Math.PI / 180;
	const scaleX = 111320 * Math.cos(referenceLat);
	const scaleY = 110540;
	const px = point[1] * scaleX, py = point[0] * scaleY;
	const ax = first[1] * scaleX, ay = first[0] * scaleY;
	const bx = second[1] * scaleX, by = second[0] * scaleY;
	const dx = bx - ax, dy = by - ay;
	const denominator = dx * dx + dy * dy;
	const ratio = denominator ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / denominator)) : 0;
	return Math.hypot(px - (ax + ratio * dx), py - (ay + ratio * dy));
}

function route_segments(raw) {
	const segments = [];
	for (const line of route_lines_from_geojson(raw)) {
		for (let index = 1; index < line.length; index++) {
			// GeoJSON coordinates are longitude, latitude.
			segments.push({ first: [line[index - 1][1], line[index - 1][0]], second: [line[index][1], line[index][0]], speeds: [] });
		}
	}
	return segments;
}

async function refresh_fleet_traffic(frm) {
	if (!window.L || !frm.__trip_map_instance) return null;
	let response;
	try {
		response = await frappe.call({
			method: "qcmc_logic.api.delivery_trip_route.get_fleet_traffic_observations",
			args: { delivery_trip: frm.doc.name, minutes: 30 },
			quiet: true
		});
	} catch (e) {
		console.warn("Unable to refresh fleet traffic", e);
		return null;
	}
	const data = response.message;
	if (!data?.available) return data;
	const segments = route_segments(frm.doc.custom_route_geojson);
	if (!segments.length) return { available: false, reason: __("Optimize the route first to display traffic on it.") };

	if (frm.__fleet_traffic_layer) frm.__fleet_traffic_layer.remove();
	const layer = L.layerGroup().addTo(frm.__trip_map_instance);
	frm.__fleet_traffic_layer = layer;
	frm.__fleet_traffic_visible = true;
	for (const point of data.observations || []) {
		let nearest = null;
		let nearestDistance = Infinity;
		for (const segment of segments) {
			const distance = point_segment_distance_m([point.latitude, point.longitude], segment.first, segment.second);
			if (distance < nearestDistance) { nearestDistance = distance; nearest = segment; }
		}
		// Only observations inside the route corridor affect the route color.
		if (nearest && nearestDistance <= 250) nearest.speeds.push(Number(point.speed_kph || 0));
	}
	let paintedSegments = 0;
	for (const segment of segments) {
		if (!segment.speeds.length) continue;
		const average = segment.speeds.reduce((sum, speed) => sum + speed, 0) / segment.speeds.length;
		const level = average < 10 ? "heavy" : average < 25 ? "slow" : "moving";
		L.polyline([segment.first, segment.second], {
			color: traffic_color(level), weight: 9, opacity: 0.9, lineCap: "round"
		}).bindPopup(`<strong>${__("Traffic on planned route")}</strong><br>${average.toFixed(1)} km/h<br><small>${segment.speeds.length} ${__("fleet observation(s)")}</small>`).addTo(layer);
		paintedSegments++;
	}
	if (!frm.__fleet_traffic_legend) {
		const legend = L.control({ position: "bottomright" });
		legend.onAdd = () => {
			const div = L.DomUtil.create("div");
			div.style.cssText = "background:white;padding:8px 10px;border-radius:6px;box-shadow:0 1px 5px #999;font-size:12px;line-height:20px";
			div.innerHTML = `<strong>${__("Traffic on This Route")}</strong><br><span style="color:#16a34a">●</span> 25+ km/h &nbsp; <span style="color:#f59e0b">●</span> 10–24 &nbsp; <span style="color:#dc2626">●</span> &lt;10<br><small>${__("Only observations within 250 m of the route")}</small>`;
			return div;
		};
		legend.addTo(frm.__trip_map_instance);
		frm.__fleet_traffic_legend = legend;
	}
	return { ...data, painted_segments: paintedSegments };
}

function live_vehicle_icon(stale) {
	return L.divIcon({
		className: "",
		html: `<div style="width:24px;height:24px;background:${stale ? "#f59e0b" : "#1677ff"};border:4px solid white;border-radius:50%;box-shadow:0 1px 7px rgba(0,0,0,.55)"></div>`,
		iconSize: [24, 24],
		iconAnchor: [12, 12]
	});
}

async function refresh_live_vehicle(frm, center) {
	let response;
	try {
		response = await frappe.call({
			method: "qcmc_logic.api.delivery_trip_route.get_live_vehicle_position",
			args: { delivery_trip: frm.doc.name },
			quiet: true
		});
	} catch (e) {
		console.warn("Unable to refresh live vehicle position", e);
		return null;
	}

	const position = response.message;
	if (!position?.available || !window.L || !frm.__trip_map_instance) return position;
	const latlng = [position.latitude, position.longitude];
	const plate = frappe.utils.escape_html(position.license_plate || position.vehicle || "Vehicle");
	const updated = position.position_time ? frappe.datetime.str_to_user(position.position_time) : __("Unknown");
	const popup = `<strong>🚚 ${plate}</strong><br>${Number(position.speed_kph || 0).toFixed(1)} km/h<br>${__("Updated")}: ${updated}${position.stale ? `<br><span style="color:#d97706">${__("Position may be stale")}</span>` : ""}`;

	if (!frm.__aika_vehicle_marker) {
		frm.__aika_vehicle_marker = L.marker(latlng, { icon: live_vehicle_icon(position.stale), zIndexOffset: 1000 })
			.addTo(frm.__trip_map_instance);
	} else {
		frm.__aika_vehicle_marker.setLatLng(latlng).setIcon(live_vehicle_icon(position.stale));
	}
	frm.__aika_vehicle_marker.bindPopup(popup);
	if (center) frm.__trip_map_instance.setView(latlng, Math.max(frm.__trip_map_instance.getZoom(), 15));
	return position;
}
