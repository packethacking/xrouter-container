# Bug `c7bfce022cac` — SIGSEGV in HTTP body handler at 0x493feb

| field            | value                                          |
|------------------|------------------------------------------------|
| signal           | `SIGSEGV`                                      |
| RIP              | `0x493feb`                                     |
| crashing insn    | `movzbl (%rax),%eax`                           |
| containing fn    | starts at `0x493816`                           |
| reached via      | HTTP                                           |
| state            | stateful — exact saved trigger does not repro alone |

## Summary

NULL-pointer 1-byte read at `0x493feb`. The pattern is a string-walk
loop: load pointer from `[rax + 0x20]`, read first byte, branch on
zero (end of string). The pointer at `+0x20` was NULL when the crash
fired. The function at `0x493816` looks like an HTTP body / JSON
parser (the trigger that found it is a `PATCH` with both
`Transfer-Encoding: chunked` and `Content-Length`, plus a JSON body
with NUL bytes inside a key).

## Disassembly

```
0x493fd2: mov   $0x0, %eax
0x493fd7: call  0x61e2c0                  ; probably the inner parse step
0x493fdc: movl  $0x0, -0x34(%rbp)
0x493fe3: mov   -0x28(%rbp), %rax         ; load the object/header struct
0x493fe7: mov   0x20(%rax), %rax          ; field at +0x20 (string ptr; NULL)
0x493feb: movzbl (%rax), %eax             ; <-- FAULT: read first char
0x493fee: test  %al, %al                  ; check terminator
0x493ff0: jne   0x494012                  ; non-empty → continue
0x493ff2: mov   -0x28(%rbp), %rax
```

## Trigger as captured

```
PATCH /api/v1/../etc/passwd HTTP/1.0
Host: 127.0.0.1
Transfer-Encoding: chunked
Content-Length: 38
Content-Type: application/json

{"<32 NUL bytes>":1}
```

(`Transfer-Encoding: chunked` *and* `Content-Length` is the classic
request-smuggling shape; either header alone is well-defined, both
together is a parser surprise.)

## Reproduction

The exact trigger doesn't crash alone — state from earlier requests
in the fuzzer run matters. Use the deterministic-seed reproducer:

```sh
fuzz/restart-target.sh httprepro 18900 20900
sleep 5
python3 fuzz/http-fuzz.py \
    --name httprepro --http-port 18900 --udp-port 20900 \
    --probe-every 200 --duration 60 --seed 127256512
```

The bug appears within the first few thousand requests.

## Suggested fix

The HTTP body / chunked handler should reject requests that include
both `Transfer-Encoding: chunked` and `Content-Length` (RFC 7230
§3.3.3 requires either ignoring `Content-Length` or returning 400);
this would eliminate the malformed-state branch that ends with a
NULL string pointer.

Beyond that fix, the string-walk at `0x493feb` should NULL-check
`[rax+0x20]` before dereferencing it — the function should not assume
upstream parsing always populated that field.

## Severity

DoS via pre-auth HTTP. Same network reach as the canary-abort bug
(`e6ee13e65a37`): anyone who can reach `HTTPPORT` can crash the node.
The NULL-deref is not a memory-corruption primitive, so RCE
exploitability is unlikely. **MEDIUM-HIGH**.
