#!/home/dawid/ezviz-test/.venv/bin/python
"""HP5 CPD7 LAN -> ChaCha20 decode -> FFmpeg MPEG-TS -> shared HTTP stream.
Requires the cloned hp5-lan repository and the existing pyezvizapi environment.
Optional AAC audio with --audio. CAS uses the installed CLI; media comes directly from the LAN device.
"""
import argparse
import contextlib
import io
import logging
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import distribution
from pathlib import Path

LOG = logging.getLogger('hp5_proxy')

class _CasCaptured(BaseException):
    """Stop the CLI after CAS succeeds, before its old LAN path starts."""

def get_control_key(args):
    from pyezvizapi.cas import EzvizCAS, CasDeviceSession

    original = EzvizCAS.cas_get_encryption
    saved_argv = sys.argv
    saved_disable = logging.root.manager.disable
    captured = {}

    def intercept(self, *call_args, **call_kwargs):
        response = original(self, *call_args, **call_kwargs)
        session = (response if isinstance(response, CasDeviceSession)
                   else CasDeviceSession.from_response(response))
        captured['key'] = session.key.encode('ascii')
        raise _CasCaptured()

    entry = next(ep for ep in distribution('pyezvizapi').entry_points
                 if ep.group == 'console_scripts' and ep.name == 'pyezvizapi')
    sys.argv = [
        'pyezvizapi', '--token-file', args.token_file,
        'stream', 'local-sdk-dump', '--host', args.host,
        '--serial', args.cas_serial, '--cas-serial', args.cas_serial,
        '--fetch-cas', '--duration', '1s', '--format', 'mpegps',
        '--output', os.devnull,
    ]
    EzvizCAS.cas_get_encryption = intercept
    try:
        # Remote errors can contain session material: suppress CLI output.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            logging.disable(logging.CRITICAL)
            try:
                entry.load()()
            except _CasCaptured:
                pass
            except SystemExit:
                pass
    finally:
        EzvizCAS.cas_get_encryption = original
        sys.argv = saved_argv
        logging.disable(saved_disable)
    if 'key' not in captured:
        raise RuntimeError('CLI did not provide a CAS control key')
    return captured['key']


def load_cpd7(repo):
    module_root = Path(repo).resolve() / 'custom_components' / 'ezviz_hp7'
    if not (module_root / 'cpd7' / 'lan_client.py').is_file():
        raise FileNotFoundError('CPD7 repository missing')
    sys.path.insert(0, str(module_root))
    from cpd7.lan_client import Cpd7LanClient
    from cpd7.decoder import StreamDecoder
    # Upstream decoder DEBUG messages include partial key material.
    logging.getLogger('cpd7').setLevel(logging.CRITICAL)
    logging.getLogger('cpd7.lan_client').setLevel(logging.CRITICAL)
    logging.getLogger('cpd7.decoder').setLevel(logging.CRITICAL)
    return Cpd7LanClient, StreamDecoder


def run_session(args, key, emit, stopping, duration=0, classes=None):
    """One media session; always reap FFmpeg and close the camera socket."""
    Client, Decoder = classes or load_cpd7(args.repo)
    lan = Client(host=args.host, related_device=args.related_device, aes_key=key,
                 channel=1, stream_quality=args.quality, encrypt_stream=True,
                 recv_timeout=5.0)
    proc = None
    readers = []
    errors = deque(maxlen=8)
    reader_failed = threading.Event()
    metrics = {'raw_bytes': 0, 'ps_bytes': 0, 'ts_bytes': 0}
    stage = 'CPD7 handshake'
    try:
        lan.start()
        LOG.info('CPD7 handshake completed with %s:9020.', args.host)
        decoder = Decoder(lan.ecdh_priv)
        command = [
            args.ffmpeg, '-hide_banner', '-loglevel', 'warning', '-nostdin',
            '-fflags', '+genpts', '-probesize', '2000000',
            '-analyzeduration', '2000000', '-f', 'mpeg', '-i', 'pipe:0',
            '-map', '0:v:0', '-c:v', 'copy',
        ]
        if args.audio:
            command += ['-map', '0:a:0?', '-c:a', 'aac', '-b:a', '96k']
        else:
            command += ['-an']
        command += ['-f', 'mpegts', '-mpegts_flags', '+resend_headers',
                    '-muxdelay', '0', 'pipe:1']
        proc = subprocess.Popen(command, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        def drain_output():
            try:
                while True:
                    data = proc.stdout.read(188 * 128)
                    if not data:
                        return
                    emit(data)
                    metrics['ts_bytes'] += len(data)
            except Exception:
                reader_failed.set()

        def drain_errors():
            for line in iter(proc.stderr.readline, b''):
                errors.append(line.decode('utf-8', errors='replace').strip())

        for fn in (drain_output, drain_errors):
            thread = threading.Thread(target=fn, daemon=True)
            thread.start()
            readers.append(thread)

        start = time.monotonic()
        key_reported = False
        stage = 'CPD7 media / decode / remux'
        while not stopping():
            if duration and time.monotonic() - start >= duration:
                break
            if reader_failed.is_set() or proc.poll() is not None:
                raise RuntimeError('FFmpeg or output consumer stopped')
            raw = lan.read_chunk()
            if not raw:
                raise TimeoutError('Camera read timed out or closed')
            metrics['raw_bytes'] += len(raw)
            decoder.feed(raw)
            if decoder.keys_derived and not key_reported:
                LOG.info('ECDH media key derived (value hidden).')
                key_reported = True
            ps = decoder.take()
            if ps:
                if not metrics['ps_bytes']:
                    LOG.info('First decrypted MPEG-PS output received.')
                proc.stdin.write(ps)
                proc.stdin.flush()
                metrics['ps_bytes'] += len(ps)
            if not metrics['ps_bytes'] and time.monotonic() - start > 25:
                raise TimeoutError('No decoded output after 25 seconds')
    except Exception as exc:
        # Upstream exceptions can contain session XML: never log their text.
        LOG.error('Session failed at %s (%s).', stage, type(exc).__name__)
        raise
    finally:
        lan.close()
        if proc is not None:
            try:
                proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
            for thread in readers:
                thread.join(timeout=2)
            proc.stdout.close()
            proc.stderr.close()
            if proc.returncode:
                for line in errors:
                    LOG.warning('FFmpeg: %s', line)
        LOG.info('Session totals: raw=%d, decrypted_PS=%d, MPEG_TS=%d bytes.',
                 metrics['raw_bytes'], metrics['ps_bytes'], metrics['ts_bytes'])
    if metrics['ts_bytes'] == 0:
        raise RuntimeError('No MPEG-TS output produced')
    return metrics


class Broadcast:
    """Disconnect slow consumers instead of dropping pieces of a TS stream."""
    def __init__(self):
        self.lock = threading.Lock()
        self.clients = set()
        self.changed = threading.Event()
        self.stop = threading.Event()

    def subscribe(self):
        sink = queue.Queue(maxsize=64)
        with self.lock:
            self.clients.add(sink)
            self.changed.set()
        return sink

    def unsubscribe(self, sink):
        with self.lock:
            self.clients.discard(sink)

    def idle(self):
        with self.lock:
            return not self.clients

    @staticmethod
    def finish(sink):
        while True:
            try:
                sink.get_nowait()
            except queue.Empty:
                break
        sink.put_nowait(None)

    def emit(self, data):
        with self.lock:
            for sink in tuple(self.clients):
                try:
                    sink.put_nowait(data)
                except queue.Full:
                    self.clients.discard(sink)
                    self.finish(sink)

    def finish_all(self):
        with self.lock:
            for sink in self.clients:
                self.finish(sink)
            self.clients.clear()


def serve(args, key):
    hub = Broadcast()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != args.path:
                self.send_error(404)
                return
            sink = hub.subscribe()
            try:
                self.connection.settimeout(10)
                self.send_response(200)
                self.send_header('Content-Type', 'video/mp2t')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Connection', 'close')
                self.end_headers()
                while not hub.stop.is_set():
                    try:
                        data = sink.get(timeout=40)
                    except queue.Empty:
                        break
                    if data is None:
                        break
                    self.wfile.write(data)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                hub.unsubscribe(sink)
                self.close_connection = True

        def log_message(self, *_):
            pass

    def producer():
        while not hub.stop.is_set():
            if hub.idle():
                hub.changed.wait(timeout=1)
                hub.changed.clear()
                continue
            try:
                run_session(args, key, hub.emit,
                            lambda: hub.stop.is_set() or hub.idle())
            except Exception:
                pass  # run_session already logs a non-secret failure summary.
            finally:
                # Force consumers to reconnect after a camera session ends.
                hub.finish_all()
            hub.stop.wait(timeout=3)

    server = ThreadingHTTPServer((args.listen_host, args.listen_port), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=producer, daemon=True)
    thread.start()
    LOG.info('HTTP proxy: http://%s:%d%s (one shared LAN session; audio=%s).',
             args.listen_host, args.listen_port, args.path, args.audio)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        hub.stop.set()
        hub.changed.set()
        hub.finish_all()
        server.server_close()
        thread.join(timeout=15)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', default='/home/dawid/ezviz-test/hp5-lan')
    parser.add_argument('--token-file', default='/home/dawid/ezviz-test/ezviz_token.json')
    parser.add_argument('--host', default='192.168.1.203')
    parser.add_argument('--cas-serial', default='SCREEN_SERIAL')
    parser.add_argument('--related-device', default='CAMERA_SERIAL')
    parser.add_argument('--quality', choices=['main', 'sub'], default='main')
    parser.add_argument('--audio', action='store_true',
                        help='Include the first available audio track, encoded as AAC')
    parser.add_argument('--ffmpeg', default='ffmpeg')
    parser.add_argument('--listen-host', default='127.0.0.1')
    parser.add_argument('--listen-port', type=int, default=8559)
    parser.add_argument('--path', default='/hp5.ts')
    parser.add_argument('--capture', help='Save one local MPEG-TS sample instead of serving HTTP')
    parser.add_argument('--duration', type=float, default=30, help='Capture duration only, seconds')
    args = parser.parse_args()
    if args.duration <= 0:
        parser.error('--duration must be positive')
    if not args.path.startswith('/'):
        parser.error('--path must start with /')
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    stage = 'CPD7 imports'
    try:
        load_cpd7(args.repo)
        stage = 'CAS setup through installed CLI'
        key = get_control_key(args)
        if len(key) != 16:
            raise ValueError('CAS control key must be 16 ASCII bytes')
        LOG.info('CAS control key obtained (value hidden).')
        stage = 'local media'
        if args.capture:
            # Keep a previous successful capture if this run produces no data.
            target = Path(args.capture)
            staged = target.with_name(target.name + '.part')
            try:
                with staged.open('wb') as output:
                    run_session(args, key, output.write, lambda: False, args.duration)
                os.replace(staged, target)
                LOG.info('Capture saved: %s', target)
            finally:
                staged.unlink(missing_ok=True)
        else:
            serve(args, key)
        return 0
    except KeyboardInterrupt:
        LOG.info('Stopped.')
        return 130
    except Exception as exc:
        LOG.error('Failed at %s (%s); secret-bearing details suppressed.', stage, type(exc).__name__)
        if isinstance(exc, ModuleNotFoundError):
            LOG.error('Missing Python module: %s', exc.name)
        return 1


if __name__ == '__main__':
    sys.exit(main())

