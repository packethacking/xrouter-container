"""XRouter telnet console for the regress tests (builds on interop's)."""

from __future__ import annotations

from consoles import XRouterConsole


class XRConsole(XRouterConsole):
    def __init__(self, host: str, port: int, call: str = "PN0TST", name: str = "xrouter", log=None):
        self.log = log
        super().__init__(host, port, call=call, name=name)

    def sysop(self, password: str) -> None:
        """Become sysop. The plain text form of '@' (MAN @) is fine on telnet."""
        out = self.cmd(f"@ {password}")
        if "Ok" not in out:
            raise RuntimeError(f"{self.name}: sysop login failed: {out!r}")

    def cmd(self, line: str, wait: float = 1.0) -> str:
        out = super().cmd(line, wait)
        if self.log:
            self.log(f"--- {self.name} >>> {line}\n{out}")
        return out

    def run(self, line: str, until: str, timeout: float = 20.0) -> str:
        """Send a command and wait for a regex, e.g. for PING's replies."""
        out = self.ask(line, until, timeout)
        if self.log:
            self.log(f"--- {self.name} >>> {line}\n{out}")
        return out
