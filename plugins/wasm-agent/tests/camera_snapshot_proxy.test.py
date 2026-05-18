#!/usr/bin/env python3
from __future__ import annotations

import base64
import io
import importlib.util
import os
import re
import socket
import struct
import subprocess
import tempfile
import textwrap
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = PLUGIN_ROOT / "server" / "static_server.py"

spec = importlib.util.spec_from_file_location("wasm_agent_static_server", SERVER_PATH)
assert spec and spec.loader
server_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server_mod)


RTSP_FRAME_JPEG_B64 = (
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcp"
    "LDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIy"
    "MjIyMjIyMjIyMjL/wAARCAACAAIDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIE"
    "AwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpT"
    "VFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ"
    "2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQ"
    "J3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWV"
    "pjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5e"
    "bn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD3qiiigD//2Q=="
)


class CameraStubHandler(BaseHTTPRequestHandler):
    requests: list[dict[str, str]] = []
    expected_authorization = "Basic " + base64.b64encode(b"admin:camera-pass").decode("ascii")

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        self.__class__.requests.append({
            "path": self.path,
            "authorization": self.headers.get("Authorization", ""),
        })
        if self.headers.get("Authorization", "") != self.__class__.expected_authorization:
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="camera"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = base64.b64decode(
            b"/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////"
            b"2wBDAf//////////////////////////////////////////////////////////////////////////////////////wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAX/xAAVEAEBAAAAAAAAAAAAAAAAAAAAAP/aAAwDAQACEAMQAAABn//EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAQUCcf/EABQRAQAAAAAAAAAAAAAAAAAAABD/2gAIAQMBAT8BP//EABQRAQAAAAAAAAAAAAAAAAAAABD/2gAIAQIBAT8BP//EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEABj8Cf//Z"
        )
        if self.path.startswith("/cgi-bin/mjpg/video.cgi"):
            boundary = b"wasm-agent-test"
            frame = (
                b"--" + boundary + b"\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n\r\n"
                + body + b"\r\n"
                b"--" + boundary + b"--\r\n"
            )
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=wasm-agent-test")
            self.send_header("Content-Length", str(len(frame)))
            self.end_headers()
            self.wfile.write(frame)
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class CameraStub:
    def __enter__(self) -> "CameraStub":
        CameraStubHandler.requests = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), CameraStubHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        return self

    def __exit__(self, *_: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class FakeCameraStreamServer:
    def __init__(self) -> None:
        self.camera_stream_sessions: dict[str, dict[str, object]] = {}
        self.camera_stream_sessions_lock = threading.Lock()


class FakeCameraStreamHandler:
    def __init__(self, server: FakeCameraStreamServer) -> None:
        self.server = server
        self.status = 0
        self.headers: list[tuple[str, str]] = []
        self.wfile = io.BytesIO()

    def send_response(self, status: int) -> None:
        self.status = status

    def send_header(self, key: str, value: str) -> None:
        self.headers.append((key, value))

    def end_headers(self) -> None:
        return


class LiveRtspFixture:
    session_id = "wasm-agent-test-session"

    def __enter__(self) -> "LiveRtspFixture":
        self.nals = self._generate_h264_nals()
        try:
            self.sps = next(nal for nal in self.nals if nal[0] & 0x1F == 7)
            self.pps = next(nal for nal in self.nals if nal[0] & 0x1F == 8)
        except StopIteration as exc:
            raise unittest.SkipTest("ffmpeg did not produce SPS/PPS for live RTSP fixture") from exc
        self.frame_nals = [nal for nal in self.nals if nal[0] & 0x1F not in {7, 8}]
        if not self.frame_nals:
            raise unittest.SkipTest("ffmpeg did not produce frame NALs for live RTSP fixture")
        self.stop_event = threading.Event()
        self.ready_event = threading.Event()
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind(("127.0.0.1", 0))
        self.server_socket.listen(5)
        self.port = int(self.server_socket.getsockname()[1])
        self.url = f"rtsp://127.0.0.1:{self.port}/live"
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()
        if not self.ready_event.wait(timeout=2):
            self.__exit__(None, None, None)
            raise unittest.SkipTest("live RTSP fixture did not start")
        return self

    def __exit__(self, *_: object) -> None:
        self.stop_event.set()
        try:
            self.server_socket.close()
        except OSError:
            pass
        try:
            with socket.create_connection(("127.0.0.1", self.port), timeout=0.2):
                pass
        except OSError:
            pass
        self.thread.join(timeout=2)

    @staticmethod
    def _generate_h264_nals() -> list[bytes]:
        command = [
            server_mod.camera_rtsp_ffmpeg_path(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=96x72:rate=1",
            "-frames:v",
            "1",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-tune",
            "zerolatency",
            "-x264-params",
            "keyint=1:min-keyint=1:scenecut=0",
            "-f",
            "h264",
            "pipe:1",
        ]
        try:
            proc = subprocess.run(command, check=True, capture_output=True, timeout=10)
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise unittest.SkipTest(f"ffmpeg could not build live RTSP fixture: {exc}") from exc
        return [part for part in re.split(b"\x00\x00\x00\x01|\x00\x00\x01", proc.stdout) if part]

    def _serve(self) -> None:
        self.ready_event.set()
        while not self.stop_event.is_set():
            try:
                conn, _addr = self.server_socket.accept()
            except OSError:
                return
            threading.Thread(target=self._handle_client, args=(conn,), daemon=True).start()

    def _send_response(
        self,
        conn: socket.socket,
        cseq: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes = b"",
    ) -> None:
        response_headers = dict(headers or {})
        if body and "Content-Length" not in response_headers:
            response_headers["Content-Length"] = str(len(body))
        lines = [f"RTSP/1.0 200 OK", f"CSeq: {cseq}"]
        lines.extend(f"{key}: {value}" for key, value in response_headers.items())
        try:
            conn.sendall("\r\n".join(lines + ["", ""]).encode("ascii") + body)
        except OSError:
            return

    @staticmethod
    def _rtp_packet(payload: bytes, seq: int, timestamp: int, *, marker: bool) -> bytes:
        header = struct.pack(
            "!BBHII",
            0x80,
            (0x80 if marker else 0x00) | 96,
            seq & 0xFFFF,
            timestamp & 0xFFFFFFFF,
            0x12345678,
        )
        return header + payload

    def _send_interleaved(self, conn: socket.socket, payload: bytes) -> None:
        conn.sendall(b"$" + bytes([0]) + struct.pack("!H", len(payload)) + payload)

    def _send_nal(self, conn: socket.socket, nal: bytes, seq: int, timestamp: int, *, marker: bool) -> int:
        max_payload = 1200
        if len(nal) <= max_payload:
            self._send_interleaved(conn, self._rtp_packet(nal, seq, timestamp, marker=marker))
            return seq + 1
        nal_header = nal[0]
        fu_indicator = (nal_header & 0x60) | 28
        nal_type = nal_header & 0x1F
        offset = 1
        while offset < len(nal):
            chunk = nal[offset : offset + max_payload - 2]
            start = offset == 1
            end = offset + len(chunk) >= len(nal)
            fu_header = (0x80 if start else 0x00) | (0x40 if end else 0x00) | nal_type
            self._send_interleaved(
                conn,
                self._rtp_packet(bytes([fu_indicator, fu_header]) + chunk, seq, timestamp, marker=marker and end),
            )
            seq += 1
            offset += len(chunk)
        return seq

    def _stream_frames(self, conn: socket.socket) -> None:
        seq = 1
        timestamp = 0
        try:
            while not self.stop_event.is_set():
                nals = [self.sps, self.pps, *self.frame_nals]
                for index, nal in enumerate(nals):
                    seq = self._send_nal(conn, nal, seq, timestamp, marker=index == len(nals) - 1)
                timestamp += 90000
                time.sleep(0.5)
        except OSError:
            return

    def _handle_client(self, conn: socket.socket) -> None:
        buffer = b""
        streaming = False
        with conn:
            while not self.stop_event.is_set():
                while b"\r\n\r\n" not in buffer:
                    try:
                        chunk = conn.recv(4096)
                    except OSError:
                        return
                    if not chunk:
                        return
                    buffer += chunk
                raw, buffer = buffer.split(b"\r\n\r\n", 1)
                text = raw.decode("utf-8", errors="replace")
                request_line = text.split("\r\n", 1)[0]
                method = request_line.split(" ", 1)[0]
                match = re.search(r"^CSeq:\s*(\S+)", text, re.IGNORECASE | re.MULTILINE)
                cseq = match.group(1) if match else "1"
                if method == "OPTIONS":
                    self._send_response(conn, cseq, headers={"Public": "OPTIONS, DESCRIBE, SETUP, PLAY, TEARDOWN"})
                elif method == "DESCRIBE":
                    sdp = (
                        "v=0\r\n"
                        "o=- 0 0 IN IP4 127.0.0.1\r\n"
                        "s=wasm-agent live rtsp fixture\r\n"
                        "c=IN IP4 127.0.0.1\r\n"
                        "t=0 0\r\n"
                        "a=control:*\r\n"
                        "m=video 0 RTP/AVP/TCP 96\r\n"
                        "a=rtpmap:96 H264/90000\r\n"
                        "a=fmtp:96 packetization-mode=1;"
                        f"sprop-parameter-sets={base64.b64encode(self.sps).decode('ascii')},"
                        f"{base64.b64encode(self.pps).decode('ascii')}\r\n"
                        "a=control:trackID=0\r\n"
                    )
                    self._send_response(
                        conn,
                        cseq,
                        headers={"Content-Type": "application/sdp", "Content-Base": f"{self.url}/"},
                        body=sdp.encode("ascii"),
                    )
                elif method == "SETUP":
                    self._send_response(
                        conn,
                        cseq,
                        headers={"Transport": "RTP/AVP/TCP;unicast;interleaved=0-1", "Session": self.session_id},
                    )
                elif method == "PLAY":
                    self._send_response(
                        conn,
                        cseq,
                        headers={
                            "Session": self.session_id,
                            "RTP-Info": f"url={self.url}/trackID=0;seq=1;rtptime=0",
                        },
                    )
                    if not streaming:
                        threading.Thread(target=self._stream_frames, args=(conn,), daemon=True).start()
                        streaming = True
                elif method == "TEARDOWN":
                    self._send_response(conn, cseq, headers={"Session": self.session_id})
                    return
                else:
                    self._send_response(conn, cseq)


class CameraSnapshotProxyTest(unittest.TestCase):
    def test_snapshot_proxy_returns_data_url_and_basic_auth(self) -> None:
        with CameraStub() as stub:
            result = server_mod.camera_snapshot_proxy({
                "url": f"{stub.base_url}/cgi-bin/snapshot.cgi?channel=1",
                "username": "admin",
                "password": "camera-pass",
            })

        self.assertTrue(result["ok"])
        self.assertEqual(result["image"]["content_type"], "image/jpeg")
        self.assertTrue(result["image"]["data_url"].startswith("data:image/jpeg;base64,"))
        self.assertEqual(CameraStubHandler.requests[-1]["path"], "/cgi-bin/snapshot.cgi?channel=1")
        self.assertEqual(
            CameraStubHandler.requests[-1]["authorization"],
            CameraStubHandler.expected_authorization,
        )

    def test_snapshot_proxy_rejects_non_http_urls(self) -> None:
        with self.assertRaises(server_mod.BrowserError) as ctx:
            server_mod.camera_snapshot_proxy({"url": "file:///etc/passwd"})
        self.assertEqual(ctx.exception.code, "camera_snapshot_bad_scheme")

    def test_camera_diagnostics_reports_reachable_http_port(self) -> None:
        with CameraStub() as stub:
            result = server_mod.camera_diagnostics({
                "url": f"{stub.base_url}/cgi-bin/snapshot.cgi?channel=1",
            })

        self.assertTrue(result["ok"])
        self.assertTrue(result["reachable"])
        self.assertTrue(any(check["ok"] and check["label"] == "source:http" for check in result["tcp"]))

    def test_camera_diagnostics_reports_unreachable_rtsp_port(self) -> None:
        result = server_mod.camera_diagnostics({
            "url": "rtsp://127.0.0.1:9/cam/realmonitor?channel=1&subtype=0",
        })

        self.assertTrue(result["ok"])
        self.assertFalse(result["reachable"])
        self.assertEqual(result["tcp"][0]["label"], "source:rtsp")
        self.assertEqual(result["tcp"][0]["host"], "127.0.0.1")
        self.assertEqual(result["tcp"][0]["port"], 9)
        self.assertEqual(result["route"][0]["target_ip"], "127.0.0.1")

    def test_camera_diagnostics_accepts_tunnel_host_port(self) -> None:
        result = server_mod.camera_diagnostics({
            "host": "127.0.0.1:9",
            "timeoutMs": 500,
        })

        self.assertTrue(result["ok"])
        self.assertEqual(result["tcp"][0]["label"], "host:rtsp")
        self.assertEqual(result["tcp"][0]["host"], "127.0.0.1")
        self.assertEqual(result["tcp"][0]["port"], 9)
        self.assertTrue(all(check["host"] != "127.0.0.1:9" for check in result["tcp"]))

    def test_camera_diagnostics_tolerates_malformed_tunnel_port(self) -> None:
        result = server_mod.camera_diagnostics({
            "host": "127.0.0.1:notaport",
            "timeoutMs": 500,
        })

        self.assertTrue(result["ok"])
        self.assertEqual(result["tcp"][0]["label"], "host:rtsp")
        self.assertEqual(result["tcp"][0]["host"], "127.0.0.1")
        self.assertEqual(result["tcp"][0]["port"], 554)

    def test_camera_private_route_advice_explains_private_lan_mismatch(self) -> None:
        advice = server_mod.camera_private_route_advice("192.168.1.78", "10.0.0.167")

        self.assertIn("different private LAN", advice)
        self.assertIn("RTSP tunnel host:port", advice)
        self.assertEqual(server_mod.camera_private_route_advice("192.168.1.78", "192.168.1.20"), "")

    def test_camera_diagnostics_requires_target(self) -> None:
        with self.assertRaises(server_mod.BrowserError) as ctx:
            server_mod.camera_diagnostics({"url": "file:///etc/passwd"})
        self.assertEqual(ctx.exception.code, "camera_diagnostics_missing_target")

    def test_stream_session_proxies_mjpeg_with_basic_auth(self) -> None:
        fake_server = FakeCameraStreamServer()
        with CameraStub() as stub:
            result = server_mod.create_camera_stream_session(fake_server, {
                "url": f"{stub.base_url}/cgi-bin/mjpg/video.cgi?channel=1&subtype=1",
                "username": "admin",
                "password": "camera-pass",
            })
            token = result["stream"]["url"].split("token=", 1)[1]
            handler = FakeCameraStreamHandler(fake_server)
            server_mod.serve_camera_stream_proxy(handler, token)

        self.assertTrue(result["ok"])
        self.assertEqual(handler.status, 200)
        self.assertIn(("Content-Type", "multipart/x-mixed-replace; boundary=wasm-agent-test"), handler.headers)
        self.assertIn(b"--wasm-agent-test", handler.wfile.getvalue())
        self.assertEqual(CameraStubHandler.requests[-1]["path"], "/cgi-bin/mjpg/video.cgi?channel=1&subtype=1")
        self.assertEqual(
            CameraStubHandler.requests[-1]["authorization"],
            CameraStubHandler.expected_authorization,
        )

    def test_rtsp_session_uses_true_realtime_stream_relay(self) -> None:
        fake_server = FakeCameraStreamServer()
        result = server_mod.create_camera_rtsp_stream_session(fake_server, {
            "url": "rtsp://admin:camera-pass@192.0.2.10:554/cam/realmonitor?channel=1&subtype=0",
        })
        token = result["stream"]["url"].split("token=", 1)[1]
        session = fake_server.camera_stream_sessions[token]
        command = server_mod.camera_rtsp_ffmpeg_command(
            "rtsp://admin:camera-pass@192.0.2.10:554/cam/realmonitor?channel=1&subtype=0",
            timeout_ms=20000,
            fps=5,
            quality=5,
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["stream"]["url"].startswith("/camera/rtsp-stream?token="))
        self.assertEqual(result["stream"]["mode"], "same-origin-rtsp-mjpeg-transcode")
        self.assertEqual(session["transport"], "rtsp-mjpeg")
        self.assertEqual(session["url"], "rtsp://192.0.2.10:554/cam/realmonitor?channel=1&subtype=0")
        self.assertEqual(session["username"], "admin")
        self.assertEqual(session["password"], "camera-pass")
        self.assertIn("-rtsp_transport", command)
        self.assertIn("tcp", command)
        self.assertIn("-timeout", command)
        self.assertNotIn("-rw_timeout", command)
        self.assertIn("-f", command)
        self.assertIn("mpjpeg", command)
        self.assertIn("wasm-agent-rtsp", command)

    def test_rtsp_stream_proxy_preflights_reachability_before_ffmpeg(self) -> None:
        fake_server = FakeCameraStreamServer()
        result = server_mod.create_camera_rtsp_stream_session(fake_server, {
            "url": "rtsp://admin:camera-pass@127.0.0.1:9/cam/realmonitor?channel=1&subtype=0",
        })
        token = result["stream"]["url"].split("token=", 1)[1]
        handler = FakeCameraStreamHandler(fake_server)

        with self.assertRaises(server_mod.BrowserError) as ctx:
            server_mod.serve_camera_rtsp_mjpeg_proxy(handler, token)

        self.assertEqual(ctx.exception.code, "camera_rtsp_unreachable")
        self.assertEqual(handler.status, 0)

    def test_rtsp_frame_proxy_requires_verified_nonblack_frame(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake_ffmpeg = Path(tmp) / "ffmpeg"
            fake_ffmpeg.write_text(textwrap.dedent(f"""\
                #!/usr/bin/env python3
                import base64
                import sys
                sys.stdout.buffer.write(base64.b64decode({RTSP_FRAME_JPEG_B64!r}))
            """))
            fake_ffmpeg.chmod(0o755)
            previous = os.environ.get("HERMES_WASM_AGENT_FFMPEG")
            previous_preflight = os.environ.get("HERMES_WASM_AGENT_SKIP_RTSP_PREFLIGHT")
            os.environ["HERMES_WASM_AGENT_FFMPEG"] = str(fake_ffmpeg)
            os.environ["HERMES_WASM_AGENT_SKIP_RTSP_PREFLIGHT"] = "1"
            try:
                result = server_mod.camera_rtsp_frame_proxy({
                    "url": "rtsp://admin:camera-pass@192.0.2.10:554/cam/realmonitor?channel=1&subtype=1",
                })
            finally:
                if previous is None:
                    os.environ.pop("HERMES_WASM_AGENT_FFMPEG", None)
                else:
                    os.environ["HERMES_WASM_AGENT_FFMPEG"] = previous
                if previous_preflight is None:
                    os.environ.pop("HERMES_WASM_AGENT_SKIP_RTSP_PREFLIGHT", None)
                else:
                    os.environ["HERMES_WASM_AGENT_SKIP_RTSP_PREFLIGHT"] = previous_preflight

        self.assertTrue(result["ok"])
        self.assertEqual(result["schema"], "hermes.wasm_agent.camera.rtsp_frame.v1")
        self.assertTrue(result["image"]["data_url"].startswith("data:image/jpeg;base64,"))
        self.assertFalse(result["diagnostic"]["probably_black"])
        self.assertEqual(result["diagnostic"]["source_query"], "channel=1&subtype=1")

    def test_rtsp_frame_proxy_falls_back_to_intelbras_main_subtype(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake_ffmpeg = Path(tmp) / "ffmpeg"
            arg_log = Path(tmp) / "args.log"
            fake_ffmpeg.write_text(textwrap.dedent(f"""\
                #!/usr/bin/env python3
                import base64
                import os
                import sys
                args = " ".join(sys.argv)
                with open(os.environ["WA_FFMPEG_ARG_LOG"], "a", encoding="utf-8") as handle:
                    handle.write(args + "\\n")
                if "subtype=1" in args:
                    sys.stderr.write("substream disabled\\n")
                    sys.exit(1)
                sys.stdout.buffer.write(base64.b64decode({RTSP_FRAME_JPEG_B64!r}))
            """))
            fake_ffmpeg.chmod(0o755)
            previous_ffmpeg = os.environ.get("HERMES_WASM_AGENT_FFMPEG")
            previous_log = os.environ.get("WA_FFMPEG_ARG_LOG")
            previous_preflight = os.environ.get("HERMES_WASM_AGENT_SKIP_RTSP_PREFLIGHT")
            os.environ["HERMES_WASM_AGENT_FFMPEG"] = str(fake_ffmpeg)
            os.environ["WA_FFMPEG_ARG_LOG"] = str(arg_log)
            os.environ["HERMES_WASM_AGENT_SKIP_RTSP_PREFLIGHT"] = "1"
            try:
                result = server_mod.camera_rtsp_frame_proxy({
                    "url": "rtsp://admin:camera-pass@192.0.2.10:554/cam/realmonitor?channel=1&subtype=1",
                })
            finally:
                if previous_ffmpeg is None:
                    os.environ.pop("HERMES_WASM_AGENT_FFMPEG", None)
                else:
                    os.environ["HERMES_WASM_AGENT_FFMPEG"] = previous_ffmpeg
                if previous_log is None:
                    os.environ.pop("WA_FFMPEG_ARG_LOG", None)
                else:
                    os.environ["WA_FFMPEG_ARG_LOG"] = previous_log
                if previous_preflight is None:
                    os.environ.pop("HERMES_WASM_AGENT_SKIP_RTSP_PREFLIGHT", None)
                else:
                    os.environ["HERMES_WASM_AGENT_SKIP_RTSP_PREFLIGHT"] = previous_preflight
            calls = arg_log.read_text(encoding="utf-8")

        self.assertTrue(result["ok"])
        self.assertEqual(result["diagnostic"]["source_query"], "channel=1&subtype=0")
        self.assertEqual(
            [attempt["status"] for attempt in result["diagnostic"]["attempts"]],
            ["no_frame", "ok"],
        )
        self.assertIn("subtype=1", calls)
        self.assertIn("subtype=0", calls)

    def test_rtsp_frame_proxy_reports_unreachable_rtsp_port_before_ffmpeg(self) -> None:
        with self.assertRaises(server_mod.BrowserError) as ctx:
            server_mod.camera_rtsp_frame_proxy({
                "url": "rtsp://127.0.0.1:9/cam/realmonitor?channel=1&subtype=0",
                "timeoutMs": 1000,
            })

        self.assertEqual(ctx.exception.code, "camera_rtsp_unreachable")
        self.assertIn("127.0.0.1:9", ctx.exception.message)

    def test_rtsp_preflight_includes_private_route_advice(self) -> None:
        original = server_mod.camera_route_hint
        server_mod.camera_route_hint = lambda host, port: {
            "host": host,
            "port": port,
            "advice": "The DVR target is on a different private LAN. Use an RTSP tunnel host:port reachable from wasm-agent.",
            "private_lan_mismatch": True,
        }
        try:
            with self.assertRaises(server_mod.BrowserError) as ctx:
                server_mod.camera_rtsp_frame_proxy({
                    "url": "rtsp://127.0.0.1:9/cam/realmonitor?channel=1&subtype=0",
                    "timeoutMs": 1000,
                })
        finally:
            server_mod.camera_route_hint = original

        self.assertEqual(ctx.exception.code, "camera_rtsp_unreachable")
        self.assertIn("different private LAN", ctx.exception.message)
        self.assertIn("RTSP tunnel host:port", ctx.exception.message)

    def test_rtsp_frame_proxy_decodes_live_loopback_rtsp_source(self) -> None:
        with LiveRtspFixture() as rtsp:
            result = server_mod.camera_rtsp_frame_proxy({
                "url": rtsp.url,
                "timeoutMs": 9000,
                "quality": 3,
            })

        self.assertTrue(result["ok"])
        self.assertEqual(result["schema"], "hermes.wasm_agent.camera.rtsp_frame.v1")
        self.assertEqual(result["image"]["content_type"], "image/jpeg")
        self.assertGreater(result["image"]["bytes"], 1000)
        self.assertFalse(result["diagnostic"]["probably_black"])
        self.assertEqual(result["diagnostic"]["attempts"][-1]["status"], "ok")


if __name__ == "__main__":
    unittest.main()
