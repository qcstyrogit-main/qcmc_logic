(function () {
	if (!window.location.pathname.startsWith('/lms')) return;

	var nativeDescriptor = Object.getOwnPropertyDescriptor(Location.prototype, 'href');
	if (!nativeDescriptor || !nativeDescriptor.set) return;

	Object.defineProperty(Location.prototype, 'href', {
		set: function (url) {
			if (typeof url === 'string' && /^\/login(\?|$)/.test(url)) {
				url = url.replace(/^\/login/, '/lms-login');
			}
			nativeDescriptor.set.call(this, url);
		},
		get: nativeDescriptor.get,
		configurable: true,
	});
})();
