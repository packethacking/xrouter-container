#!/usr/bin/env python3
"""Entrypoint for the XNet (linuxsnet) container.

1. Renders /xnet/AUTOEXEC.NET.tmpl (or the file named by XNET_TEMPLATE)
   into a fresh working directory, substituting ${VAR} from the
   environment (string.Template, unknown names are left as they are).
2. Runs linuxsnet there on a pseudo terminal (XNet wants a tty).
   On a fresh start XNet boots as NOCALL with alias ######, and that
   first identity stays in its node table (and in its RIFs) after "my
   call". So unless XNET_TWO_PASS=0, a first pass runs only the "my ..."
   lines, saves them with prgexit, and the real run starts from that
   saved state.
3. Copies everything the console prints to stdout, so docker logs has it.
4. Serves the console on TCP port XNET_CONSOLE_PORT (default 8023) as a
   raw byte bridge. One client at a time; a new client replaces the old.
   Bytes from the client go to the console unchanged.

If linuxsnet exits, this script exits non-zero.
"""

import os
import pty
import select
import shutil
import signal
import socket
import string
import sys
import time

BINARY = os.environ.get("XNET_BINARY", "/xnet/linuxsnet")
TEMPLATE = os.environ.get("XNET_TEMPLATE", "/xnet/AUTOEXEC.NET.tmpl")
WORKDIR = os.environ.get("XNET_WORKDIR", "/run/xnet")
PORT = int(os.environ.get("XNET_CONSOLE_PORT", "8023"))


def log(msg):
    sys.stdout.write("[xnet-console] %s\n" % msg)
    sys.stdout.flush()


def write_autoexec(text):
    # XNet is a DOS-era program; give it CR LF lines.
    text = text.replace("\r\n", "\n").replace("\n", "\r\n")
    with open(os.path.join(WORKDIR, "AUTOEXEC.NET"), "w", encoding="ascii", newline="") as f:
        f.write(text)


def spawn():
    pid, master = pty.fork()
    if pid == 0:
        os.chdir(WORKDIR)
        os.environ["TERM"] = "dumb"
        try:
            os.execv(BINARY, [BINARY])
        except Exception as e:  # noqa: BLE001
            sys.stderr.write("exec %s failed: %s\n" % (BINARY, e))
            os._exit(127)
    return pid, master


def first_pass(text):
    """Boot once with only the "my ..." lines and save that state."""
    call = os.environ.get("XNET_CALL", "")
    mine = [l for l in text.splitlines() if l.strip().lower().startswith("my ")]
    write_autoexec("\n".join(mine) + "\n")
    pid, master = spawn()
    out = sys.stdout.buffer
    buf = b""
    steps = [(b"Node:", b"\x1b"), (b"* ", ("C %s\r" % call).encode()),
             (b"=>", b"sys\r"), (b"=>", b"prgexit\r")]
    deadline = time.time() + 30
    while time.time() < deadline:
        r, _, _ = select.select([master], [], [], 0.5)
        if r:
            try:
                data = os.read(master, 4096)
            except OSError:
                data = b""
            if not data:
                break
            out.write(data)
            out.flush()
            buf += data
        if steps and steps[0][0] in buf:
            buf = b""
            os.write(master, steps.pop(0)[1])
            time.sleep(0.3)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    os.waitpid(pid, 0)
    os.close(master)
    if steps:
        log("first pass did not finish; continuing anyway")
    else:
        log("first pass saved call and alias")


def prepare():
    # Start fresh every time: XNet keeps binary NET*.CFG state files.
    if os.path.isdir(WORKDIR):
        shutil.rmtree(WORKDIR)
    os.makedirs(WORKDIR)
    with open(TEMPLATE, "r", encoding="ascii") as f:
        text = string.Template(f.read()).safe_substitute(os.environ)
    if os.environ.get("XNET_TWO_PASS", "1") != "0":
        first_pass(text)
    write_autoexec(text)
    log("AUTOEXEC.NET rendered from %s" % TEMPLATE)
    for line in text.splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            log("  " + line)


def main():
    prepare()
    pid, master = spawn()

    def forward_signal(signum, _frame):
        try:
            os.kill(pid, signal.SIGKILL)
        finally:
            sys.exit(128 + signum)

    signal.signal(signal.SIGTERM, forward_signal)
    signal.signal(signal.SIGINT, forward_signal)

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", PORT))
    srv.listen(4)
    log("linuxsnet pid %d, console on tcp port %d" % (pid, PORT))

    client = None
    out = sys.stdout.buffer
    while True:
        rlist = [master, srv] + ([client] if client else [])
        try:
            ready, _, _ = select.select(rlist, [], [], 1.0)
        except InterruptedError:
            continue
        if master in ready:
            try:
                data = os.read(master, 4096)
            except OSError:
                data = b""
            if not data:
                break
            out.write(data)
            out.flush()
            if client:
                try:
                    client.sendall(data)
                except OSError:
                    client.close()
                    client = None
        if srv in ready:
            new, addr = srv.accept()
            new.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            if client:
                log("console client replaced by %s:%d" % addr)
                client.close()
            else:
                log("console client %s:%d connected" % addr)
            client = new
        if client and client in ready:
            try:
                data = client.recv(4096)
            except OSError:
                data = b""
            if not data:
                log("console client disconnected")
                client.close()
                client = None
            else:
                os.write(master, data)

    # Console closed: linuxsnet has gone (or is going).
    status = 0
    for _ in range(50):
        done, status = os.waitpid(pid, os.WNOHANG)
        if done:
            break
        time.sleep(0.1)
    else:
        os.kill(pid, signal.SIGKILL)
        _, status = os.waitpid(pid, 0)
    code = os.waitstatus_to_exitcode(status)
    log("linuxsnet exited (%d)" % code)
    sys.exit(code if code > 0 else 1)


if __name__ == "__main__":
    main()
