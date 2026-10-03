"""Local CONNECT forwarder that injects Proxy-Authorization.

The VM egress proxy password contains URL-breaking chars that botocore's
proxy handling chokes on. This forwarder listens on 127.0.0.1:8888 without
auth, and relays to the real egress proxy with a proper Proxy-Authorization
header. Point boto3/botocore at http://127.0.0.1:8888.

Usage: python3 proxy_forwarder.py  (runs forever)
"""
import asyncio
import base64
import os
import sys
from urllib.parse import urlparse, unquote

LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 8888
BUF = 65536


def get_upstream():
    raw = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY") or ""
    # strip scheme, split auth from host:port on the LAST @
    no_scheme = raw.split("://", 1)[-1]
    auth, _, hostport = no_scheme.rpartition("@")
    user, _, password = auth.partition(":")
    host, _, port = hostport.partition(":")
    creds = f"{unquote(user)}:{unquote(password)}"
    token = base64.b64encode(creds.encode()).decode()
    return host, int(port or 3128), token


async def relay(reader, writer):
    try:
        while True:
            data = await reader.read(BUF)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (asyncio.CancelledError, ConnectionResetError, BrokenPipeError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def handle(client_reader, client_writer, upstream_host, upstream_port, token):
    print(f'CONN from {client_writer.get_extra_info("peername")}', flush=True)
    try:
        # Read CONNECT request headers
        request = b""
        while b"\r\n\r\n" not in request:
            chunk = await client_reader.read(4096)
            if not chunk:
                client_writer.close()
                return
            request += chunk
        lines = request.decode("latin1").split("\r\n")
        target = lines[0].split(" ")[1]  # host:port

        upstream_reader, upstream_writer = await asyncio.open_connection(
            upstream_host, upstream_port
        )
        connect_req = (
            f"CONNECT {target} HTTP/1.1\r\n"
            f"Host: {target}\r\n"
            f"Proxy-Authorization: Basic {token}\r\n"
            f"Proxy-Connection: Keep-Alive\r\n\r\n"
        )
        upstream_writer.write(connect_req.encode("latin1"))
        await upstream_writer.drain()

        # Read CONNECT response
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = await upstream_reader.read(4096)
            if not chunk:
                client_writer.close()
                upstream_writer.close()
                return
            resp += chunk
        status = resp.decode("latin1").split("\r\n")[0]
        if " 200 " not in status:
            print(f"Upstream refused CONNECT to {target}: {status}", flush=True)
            client_writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            await client_writer.drain()
            client_writer.close()
            upstream_writer.close()
            return

        client_writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await client_writer.drain()

        await asyncio.gather(
            relay(client_reader, upstream_writer),
            relay(upstream_reader, client_writer),
        )
    except Exception as e:
        print(f"handler error: {e}", flush=True)
        try:
            client_writer.close()
        except Exception:
            pass


async def main():
    upstream_host, upstream_port, token = get_upstream()
    print(f"Forwarding 127.0.0.1:{LISTEN_PORT} -> {upstream_host}:{upstream_port}",
          flush=True)
    server = await asyncio.start_server(
        lambda r, w: handle(r, w, upstream_host, upstream_port, token),
        LISTEN_HOST, LISTEN_PORT,
    )
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
