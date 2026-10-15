/* Local reverse proxy for a single Frappe site behind Tailscale Serve/Funnel.
 * The fixed site/host headers mirror Frappe's production nginx configuration.
 * Usage: node realtime_proxy.cjs erp.example.com https://erp-public.example 9001
 */
const http = require('node:http');

const [site, origin, listenPort = '9001', upstreamPort = '9000'] = process.argv.slice(2);
if (!site || !/^[\w.-]+$/.test(site) || !origin) throw Error('A site name and public origin are required');
const publicHost = new URL(origin).host;
const headers = request => ({...request.headers, host: publicHost, 'x-frappe-site-name': site});
const options = request => ({hostname: '127.0.0.1', port: Number(upstreamPort), path: request.url, method: request.method, headers: headers(request)});
const allowed = request => /^\/socket\.io(?:\/|\?|$)/.test(request.url);

const server = http.createServer((request, response) => {
    if (!allowed(request)) {response.writeHead(404); response.end(); return;}
    const upstream = http.request(options(request), incoming => {
        response.writeHead(incoming.statusCode, incoming.headers);
        incoming.on('error', () => response.destroy());
        incoming.pipe(response);
    });
    request.on('error', () => upstream.destroy());
    upstream.on('error', () => {
        if (!response.headersSent) response.writeHead(502);
        response.end();
    });
    response.on('close', () => upstream.destroy());
    request.pipe(upstream);
});

server.on('upgrade', (request, socket, head) => {
    if (!allowed(request)) {socket.end('HTTP/1.1 404 Not Found\r\n\r\n'); return;}
    const upstream = http.request(options(request));
    // The HTTP server releases upgraded sockets before the upstream handshake
    // completes, so handle disconnects during that interval as well.
    socket.on('error', () => upstream.destroy());
    socket.on('close', () => upstream.destroy());
    upstream.on('upgrade', (response, connection, upstreamHead) => {
        const lines = [`HTTP/1.1 ${response.statusCode} ${response.statusMessage}`];
        for (let i = 0; i < response.rawHeaders.length; i += 2) lines.push(`${response.rawHeaders[i]}: ${response.rawHeaders[i + 1]}`);
        socket.write(lines.join('\r\n') + '\r\n\r\n');
        if (head.length) connection.write(head);
        if (upstreamHead.length) socket.write(upstreamHead);
        socket.on('error', () => connection.destroy());
        connection.on('error', () => socket.destroy());
        socket.on('close', () => connection.destroy());
        connection.on('close', () => socket.destroy());
        socket.pipe(connection); connection.pipe(socket);
    });
    upstream.on('response', response => {
        response.resume(); socket.end('HTTP/1.1 502 Bad Gateway\r\n\r\n');
    });
    upstream.on('error', () => socket.destroy());
    upstream.end();
});

server.listen(Number(listenPort), '127.0.0.1', () => console.log(`Frappe realtime proxy listening on 127.0.0.1:${listenPort}`));
