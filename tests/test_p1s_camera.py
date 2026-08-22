import struct
import tempfile
import unittest
from pathlib import Path

from inventory.p1s_camera import (
    CameraFrame,
    CameraValidationError,
    authentication_record,
    capture_one_frame,
    jpeg_dimensions,
    write_validated_frame,
)


JPEG = bytes.fromhex("FFD8FFC0000B0802D0050001011100FFD9")


class FakeStream:
    def __init__(self, incoming: bytes):
        self.incoming = bytearray(incoming)
        self.sent = []
        self.closed = False

    def settimeout(self, _timeout):
        pass

    def recv(self, size):
        chunk = bytes(self.incoming[: min(size, 3)])
        del self.incoming[: len(chunk)]
        return chunk

    def sendall(self, value):
        self.sent.append(value)

    def version(self):
        return "TLSv1.2"

    def cipher(self):
        return ("SYNTHETIC-CIPHER", "TLSv1.2", 256)

    def close(self):
        self.closed = True


class FakeContext:
    def __init__(self, secure):
        self.secure = secure

    def wrap_socket(self, raw, server_hostname):
        self.raw = raw
        self.host = server_hostname
        return self.secure


class P1SCameraTests(unittest.TestCase):
    def test_auth_record_is_fixed_size_and_contains_only_fake_secret(self):
        record = authentication_record("FAKECODE")
        self.assertEqual(len(record), 80)
        self.assertEqual(struct.unpack("<IIII", record[:16]), (0x40, 0x3000, 0, 0))
        self.assertEqual(record[16:48].rstrip(b"\0"), b"bblp")
        self.assertEqual(record[48:].rstrip(b"\0"), b"FAKECODE")

    def test_fragmented_frame_is_reassembled_once(self):
        header = struct.pack("<IIII", len(JPEG), 0, 1, 0)
        secure = FakeStream(header + JPEG)
        raw = FakeStream(b"")
        frame = capture_one_frame(
            "192.0.2.10",
            "FAKECODE",
            connection_factory=lambda *_args, **_kwargs: raw,
            tls_context_factory=lambda: FakeContext(secure),
        )
        self.assertEqual((frame.width, frame.height), (1280, 720))
        self.assertEqual(len(secure.sent), 1)
        self.assertTrue(secure.closed)

    def test_invalid_jpeg_is_rejected(self):
        with self.assertRaises(CameraValidationError):
            jpeg_dimensions(b"not-a-jpeg")

    def test_frame_write_is_atomic(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "frame.jpg"
            write_validated_frame(path, CameraFrame(JPEG, 1280, 720, "TLSv1.2", "TEST"))
            self.assertEqual(path.read_bytes(), JPEG)
            self.assertFalse(path.with_suffix(".jpg.tmp").exists())


if __name__ == "__main__":
    unittest.main()
