# XRouter feature / behaviour inventory (for the regression suite)

Baseline: **505c** (`ghcr.io/packethacking/xrouter:505c-amd64`). Built 2026-10-13 from
the OARC wiki (`packet:xrouter*`), the MAN/HELP pages shipped in the image
(`/opt/xrouter/skel/MAN`, `/opt/xrouter/skel/HELP`), and a short live session
against 505c (marked **[live]**). Sources are given as wiki page ids or
`MAN:<file>` / `HELP:<file>`.

Most wiki tour pages (`packet:xrouter:tour`, `:full-fat`, `:telnet-interfaces`,
`:bbs`, `:help`) are screenshots with little text. The MAN pages carry the
detail. The `packet:xrouter:docs` page is an auto-generated index of the same
MAN sections (MAN1 commands, MAN4 PMS, MAN6 interfaces, MAN7 directives,
MAN8 files, MAN9 topics).

---

## 0. Console basics [live]

- Telnet banner: `Xrouter v505c` then `Callsign: `. With ACCESS.SYS `0.0.0.0/0 1`
  a valid callsign is enough. After login the CTEXT is sent and **no prompt**.
- Every node reply is prefixed with `NODECALL:NODEALIAS} `, e.g.
  `PN0XR:XRNODE} Ports:`. A blank line follows the header line.
- Lists end with `(End of list)`.
- A sysop-only command from a user gets `PN0XR:XRNODE} Command needs SYSOP status`.
- Commands abbreviate (minimum shown as `N[odes]`). When too few args are given,
  the command prints its syntax (`packet:xrouter:help`).
- Help: `?` gives basic commands, `? *` the full list, `? **` the list with
  descriptions, `? <cmd>` the syntax, `H` / `H *` / `H <topic>` the help files
  (with wildcards, e.g. `H A*`, and suggestions for typos) (`packet:xrouter:help`).
- `?` output [live]:
  ```
  PN0XR:XRNODE} Basic commands:
   <C>onnect <B>ye <I>nfo <M>heard <N>odes <P>orts <R>outes <U>sers <V>ersion
  Use "? *" for full list
  ```
- Typing anything while a `C` is pending aborts it: `Operation aborted` [live].

## 1. Console commands

### 1.1 Becoming sysop

| Route | Rule | Source |
|---|---|---|
| Local console / XrMon console | always full sysop | MAN:@ |
| `@` alone | prints a 5x5 digit grid. The sysop picks one row and replies `@ <5 chars>`: the characters of the password at those positions. | MAN:@, `packet:xrouter:telnet-interfaces` |
| `@ <plaintext password>` | accepted on "secure" uplinks. Reply `Ok`. Wrong password gives `Invalid password` [live]. | MAN:@ |
| No PASSWORD.SYS entry for the caller | doc says "Bad command". 505c answers `Error!` [live]. | MAN:@ |
| PASSWORD.SYS | `<callsign> <password>` per line, no SSID, case-insensitive, `;`/`#` comments. Used for AX25 remote sysop, RLOGIN and FTP. | MAN:PASSWORD.SYS |
| RLOGINPORT (513) | sysop-only login with the PASSWORD.SYS password | MAN:RLOGINPORT.7, `:telnet-interfaces` |
| PORT `SYSOP=1` | everyone on that port is sysop (secure links only), default 0 | MAN:SYSOP.7 |
| APPL `APPLFLAGS` bit 1 | the application gets sysop privileges | MAN:APPLS.9 |

USERPASS.SYS (`<call> <password>`) holds **user** passwords for telnet 23,
telproxy 2323, APRS server 1448 and RHP AUTH. It is not used for sysop.

ACCESS.SYS (`<subnet>[/bits] <flags>`, longest match wins, `0.0.0.0/0` is the
default) controls telnet login by source IP. Flags: 1 = valid callsign only,
2 = password required, 4 = guest allowed (password `guest`), 8 = trusted / LAN
(HTTP, RHP, AGW need no auth; does not affect Telnet/FTP). Common values:
`1` (callsign only), `3` (callsign + password), `7` (callsign + password or
`guest`). Guests cannot SEND, CHAT, CONNECT or send APRS messages. TELNET for
guests is limited by TELGUEST.ACL (no file means no TELNET). (MAN:ACCESS.SYS)

The telnet tiers are: port 23 is user level, 513 RLOGIN is sysop, 2323 is the
telnet proxy (binary after login, for machine use) (`packet:xrouter:telnet-interfaces`).

### 1.2 Full command list as printed by `? *` [live]

User (`PN0TST` over telnet):
```
?  arp amsg ansi aprs axroutes axtest bye BLOG connect chat cq cx date dx echo
finger gping gtracert help host info iproutes j links lang l4links listen
mheard nodes nftp nping nrr ntracert ports ping PMS quit routes stats send
telnet time tracert ttylink users version WALL watch wx yell
```
Sysop (after `@`) adds:
```
< *** @ acl applmask bcast bcpoll bell blevel capture cflags cmd ctext ctflags
ctrl digiflag digiport dhcp discard dos dun dial dns exclude exit fec frack ftp
fulldup getfile gnet idtext idpath ids iface ip ipaddress iplink kill keepalive
loadnodes log mhclear mhflags man maxframe maxhops maxtxhops mdir mfrom mhsize
minqual mintxqual mmask mon motd mport mqtt mtp mto nat netmask nodesint notify
ntty odn paclen pcap persist pipe pipeflag ppp putfile peers ps quality radio
resptime restart retries reboot rip shell slottime savenodes smtp start stop
sms talk tcp tnc tsync txdelay txok txport txtail udp udplocal udpremote
unproto wait xlink core
```
Some commands have no MAN page (`aprs`, `axtest`, `gtracert` has HELP only,
`getfile/putfile`, `maxhops/maxtxhops`, `mdir/mfrom`, `mtp`, `notify`, `odn`,
`ps`, `smtp`, `core`, `***`). Treat these as "exists" checks only.

### 1.3 User-level commands (all users unless noted)

| Command | Syntax | Notes / output shape |
|---|---|---|
| ? / HELP | `? [*|**|cmd]`, `H[elp] [cmd|topic|*]` | see §0 |
| BYE / QUIT | `B[ye]`, `Q[uit]` | `Goodbye` [live]. Ends all dependent sessions. |
| CONNECT | `C[onnect] [port] <call> [V(ia) digi[,digi...]] [svcnum] [S]` | Known node gives an L4 connect (port ignored). Force L2 with `C 4 MLVN-1` or `C 4 !G4FPV`. Up to 7 digis: `C 3 G6YAK V G8NTU G8EPR`. `S` = stay. A svcnum goes to a NetRomX service, e.g. `C kidder 2` = PMS. Not for guests. Output: `Trying PN0ZZZ...` then `Failure with PN0ZZZ` or `Connected to ...` [live]. |
| CX | `CX [port] <call> [V digis] [S]` | L2 connect using mod-128 |
| PORTS | `P[orts]` | `Ports:` then lines like `  1 AXUDP test` [live]. ADD/DROP/START are sysop. |
| USERS | `U[sers]` | header `Sess#  Start-time Idle Type Lnk User`, row `    1  13/10 16:58  0s Cmd  TCP (pn0tst)`, `<-->` for established and `<~~>` for setting up. Link types L2/L4/TCP/CON/TTY. |
| LINKS | `L[inks] [id#]` | header `Remote Local Prt Sta V Try T3 Pac Max Idle Txq Rxq Id` |
| L4LINKS | `L4[links] [circuit#]` | header `Local Cct Remote @HostNode Cct S Txq Rxq Rtt Tr T/o Con Cho Ack`. States 1-5 (HELP:L4LINKS). |
| NODES | see §6 | |
| ROUTES | see §6 | |
| MHEARD | `MH[eard] [nodecall] <portnum|ALL>` | `MH not enabled on port 1` when MHEARD is unset on an AXUDP port [live]. TYPE column letters D/N/I/A. |
| J | `J` | last 20 connected stations: `Recent sessions:` |
| INFO | `I[nfo] [topic|nodecall|nodealias]`, `I PAGE`, `I *` | `Info:` + INFOTEXT + `Type INFO PAGE for more about this node` [live] |
| VERSION | `V[ersion]` | `XrLin multi-protocol router, 64-bit v 505c [static] (15/3/26)` + copyright line [live] |
| STATS | `S[tats] [L1|L2|L3|L4|IP|UDP|TCP|*|?|AX25|AXIP|AXUDP|AXTCP|LAPB|ICMP|IDS|NCMP|NODES]` | one-page summary, `Time active (mins): ...`. IDS is sysop-only. |
| TIME | `TI[me] [node|hh:mm]` | remote time works only on XRouter nodes. Setting is sysop. |
| SEND | `SE[nd] <port> <destcall> [V digi,...] <text>` | UI frame, up to 8 digis. Reply `Message sent` [live]. Not for guests. |
| CQ | `CQ [v[ia] digi,...] [text]` | |
| PING | `PING <host|ip> [len [interval]]` | `hit <RETURN> to quit...` / `Pinging x with 0 bytes of data:`. Not for guests. |
| TRACERT | `TR[acert] <host> [maxhops [maxwait(ms)]]` | default 30 hops, 4 s |
| NPING / NTRACERT / NRR | `NP[ing] <node> [bytes [secs]]`, `NT[racert] <node> [maxhops [maxwait]]`, `NRR <node>` | NetRom ping / trace / record route |
| GPING / GTRACERT | `GP[ing] <addr> [len [sec]]` | GNET |
| IPROUTE | `IPR[oute]` | header `Destination Len Gateway Port Mode Metric Timer Flg`. Default row is `0.0.0.0 0 0.0.0.0 0 k 1 0` [live]. Can be disabled via `IP ROUTE CMD`. |
| ARP | `ARP` | doc says user-visible per `ARP CMD` (default 9). 505c gives a user `Command needs SYSOP status` [live]. |
| HOST / FINGER | `HO[st] <name|ip>`, `FINGER <user|user@host|@host>` | |
| TELNET / TTYLINK | `TELNET <host|ip> [port]`, `TT[ylink] <host> [port]` | not for guests |
| CHAT | `CH[at] [nodecall]` | not for guests. Chat commands start with `/` (§2.10). |
| PMS | `PM[s] [nodecall|nodealias]` | §5. `BBS` too when PMSTYPE=4. |
| BLOG / WALL | `BL[og] [node]`, `W[all] [node]` | |
| ECHO | `EC[ho] [node]` | |
| AMSG | `AM[sg] <portnum>` | APRS messaging. Guests cannot send. |
| DX / WX | `DX [port|node [port]]`, `WX [callsign|LOCAL]` | |
| LANG | `LA[ng] [en|fr|es|nl]` | |
| ANSI | `AN[si] [on|off]` | |
| LISTEN / WATCH | `LIS[ten] <port> [0]`, `WAT[ch] port[+port] | OFF` | |
| NFTP | `NF[tp] <target>` | the client is sysop-only, the server is open |
| YELL | `Y[ell]` | page the sysop |
| XLINK | `X[link] <SLIP|PPP>` | modem ports only |

NetRomX standard services (`C <node> <svc>`, HELP:SERVICES, `packet:xrouter:netromx`):
0 CMD, 1 INFO, 2 PMS, 7 ECHO, 8 CHAT, 9 DISCARD, 13 DAYTIME, 14 APRS,
16 WX, 18 SMS, 19 CHARGEN, 21 NFTP, 23 TELNET, 26 MHEARD, 27 DXLIST, 28 WALL,
29 BLOG, 79 FINGER, 80 HTTP, 87 NTTY, 110 POP3, 1883 MQTT.

### 1.4 Sysop-only commands (MAN AVAILABILITY sections)

Port parameter get/set commands. All take the form `<CMD> <port> [value]`.
The reply is `Port 1 frack = 2000` [live]; global ones use port 0:
`Global nodesinterval = 60`. Runtime changes last until restart.
`FRACK`, `RESPTIME`, `RETRIES`, `MAXFRAME`, `PACLEN <port|0>`, `PERSIST`,
`SLOTTIME`, `TXDELAY`, `TXTAIL`, `FULLDUP`, `TXOK <port> [0-3]`, `TXPORT`,
`QUALITY <port> [0-255]`, `MINQUAL`, `MINTXQUAL`, `NODESINT <port|0>`,
`DIGIFLAG <port> [0-1023]` (min abbrev `DIGIF`), `DIGIPORT`, `CFLAGS <port> [0-31]`,
`CTFLAGS`, `CTEXT <port> [cmd [text]]`, `IDTEXT <port|0> [text]`, `IDPATH`,
`UNPROTO <port> [path]`, `EXCLUDE <port> [call,...|clear|none]`, `APPLMASK`,
`IPADDRESS <port|0>`, `NETMASK`, `IPLINK <port> [ip|host]`, `UDPLOCAL`, `UDPREMOTE`,
`KEEPALIVE`, `MHFLAGS`, `MHSIZE <port> [slots]`, `MHCLEAR <port>`, `PIPE`, `PIPEFLAG`, `FEC`.

Defaults seen on an AXUDP port with no overrides [live]: digiflag 7,
cflags 3, mhflags 255, paclen 256, maxframe 3, minqual 10, unproto empty,
idpath `ID`, nodesinterval 60.

Others:

| Command | Syntax |
|---|---|
| NODES add/drop/bcast | `N A[dd] <call>[:alias] <via> <port> <qual> [!]`, `N D[rop] <call>`, `N BC <port>` |
| ROUTES add/drop | `R A[dd] <call> <port> <qual> [!] [V digis] [maxframe [frack [paclen [maxtt [maxhops]]]]]`, `R D[rop] <call> <port>` |
| BCAST / BCPOLL | `BC[ast] <port|T[imes]>`, `BCP[oll] <port>` |
| SAVENODES / LOADNODES | `SA[venodes] [file]`, `LOADNODES [file]` |
| IP | §4 (`IP ROUTE ...`, `IP BAN ...`, `IP QUIET`, `IP TTL`, `IP CONFIG`, `IP HEARD`) |
| ARP | `ARP A[dd]|D[rop]|F[lush]|L[ist]|M[axq]|LE[arn]|P[ublish]|T[imeout]|W[ait]|C[md]` |
| ACL / NAT / RIP / DNS / DHCP / DUN / PPP / TCP / UDP / PCAP | IP-stack management |
| IFACE / PORTS | `IF[ace] A[dd] <n> <type> <mtu> [id]`, `D[isplay]`, `DR[op]`, `L[ist]`, `STA[rt]`, `STO[p]`; `P A[dd] <port> <iface> <id>`, `P D[rop]`, `P S[tart]` |
| AXROUTES | `AX[routes] [port|call|X]` |
| KILL | `K[ill] [all | <sess> ...]` |
| TALK / NTTY / SMS | sysop chat |
| MONITOR / MMASK / MPORT / MTO / CAPTURE / WATCH | tracing: `MON [on|off]`, `MM [hex]` (`43FF` hex dump, `47FF` incl. KISS, `3FF` normal), `MP [mask|p+p|ALL|NONE]` |
| CMD | `CM[d] <ADD|DROP> <alias> [args]` (custom commands, also `COMMAND=` in cfg) |
| MAN | `MAN [section] [topic]`. Bare `MAN` lists section 1 topics [live]. |
| LOG / IDS / MOTD / BELL / DATE / TSYNC | admin |
| SHELL / `!` / DOS / `<` script / WAIT | OS shell, PZTDOS, scripts |
| START / STOP | daemons (e.g. IGATE) |
| RESTART / REBOOT / EXIT | `EXIT <0-255>` |
| LINKED | `*** LINKED AS <call>` (ENABLE_LINKED widens access) |
| MQTT / RADIO / TNC / CTRL / DIAL / GNET / PEERS / FTP / DISCARD / NFTP client | misc |

## 2. XROUTER.CFG (MAN:XROUTER.CFG, MAN:PORTSMORE.6, MAN:IFACES.6)

Format: `KEY=value`, one per line, case-insensitive. Comments start with `;` or
`#` in column 1. Lines are at most 255 chars. Blocks: `INTERFACE=n..ENDINTERFACE`,
`PORT=n..ENDPORT`, `APPL=n..ENDAPPL`, `CONSOLE..ENDCONSOLE`, `RADIO..ENDRADIO`,
`ROUTES`. **Interfaces must be defined before the ports that use them.**
Multi-line texts (`CTEXT`, `INFOTEXT`, `IDTEXT`) use the form keyword alone on a
line, then the text, then `***`. A bad block aborts the boot with
`XROUTER.CFG: ERROR in line N [ENDINTERFACE] - Bad or missing protocol` in
`LOG/BOOTLOG.TXT` [live] (TYPE=LOOPBACK without PROTOCOL=NONE).

### 2.1 Global keywords (defaults)

Identity: `NODECALL`* `NODEALIAS`* `CONSOLECALL` `LOCATOR` `LATITUDE`/`LONGITUDE`
(999) `QTH` `CONTACT` `HOSTNAME`.
Texts: `CTEXT` (block), `CTFLAGS` (doc: 9 in CFG summary, 1 in PORTSMORE),
`INFOTEXT`, `IDTEXT`, `IDINTERVAL` (15 min).
NetRom: `NODESINTERVAL` (60 min), `MINQUAL` (10), `MAXNODES` (200),
`MAXROUTES` (30), `OBSINIT` (5), `OBSMIN` (3), `L3TTL` (25), `MAXHOPS` (30),
`MAXTT` (500 s per CFG page, the horizon is 60000 x 10 ms), `INPBCINTERVAL`
(600 s), `L3RTTINTERVAL` (300 s), `QUALADJUST`, `BLEVEL`, `HIDENODES`,
`SORTBYCALL`, `ROUTES` (locked routes), `PROXY`, `APPLQUAL` (150).
L4: `L4WINDOW` (10), `L4TIMEOUT` (120), `L4RETRIES` (3), `L4DELAY` (3),
`L4T3` (840), `MAXCIRCUITS` (20).
L2: `PACLEN` (120 global), `T3` (180 s), `IDLETIME` (900), `MAXLINKS` (30),
`EXCLUDE`.
IP: `IPADDRESS` (0.0.0.0 means all IP is disabled, including AXUDP/AXIP/AXTCP/HTTP),
`IPIP` (0), `IPENCAP` (0), `IPUDPPORT` (94), `IPTTL` (255), `MAXARP` (20),
`DNS`, `DOMAIN` (ampr.org.), `SYNCACHE*`.
TCP service ports (each `KEY=n1 [n2]`: one value covers both stacks unless
EXTERNAL is used; two values mean XRouter stack then Linux stack; 0 or empty
disables; below 1024 on Linux needs CAP_NET_BIND_SERVICE; MAN:TCP-PORTS.6):
`ECHOPORT` 7, `DISCARDPORT` 9, `FTPPORT` 21, `TELNETPORT` 23, `FINGERPORT` 79,
`HTTPPORT` 80, `TTYLINKPORT` 87, `RLOGINPORT` 513, `SOCKSPORT` 1080,
`APRSPORT` 1448, `MQTTPORT` 1883, `TELPROXYPORT` 2323, `CHATPORT` 3600,
`AGWPORT` 8000, `RHPPORT` 9000. Also `HTTPROOT` (HTTP), `HAMLIBPORT`, `RIGSRVPORT`.
Services: `PMSCALL` `PMSALIAS` `PMSQUAL` (0) `PMSHADDR` `PMSTYPE` (1)
`KILONFWD`; `CHATCALL` `CHATALIAS` `CHATLINKS` `CHATQUAL` (150) `CHATLOG`;
`APRSCALL` `IGATE` `UIFLOOD` (WIDE) `UITRACE` (TRACE) `WXFILE`;
`MQTTSERVADDR` `MQTTSERVPORT` (1883) `MAPSERVADDR` `MAPSERVPORT` `MAPCOMMENT`;
`MAXSESSIONS` (20) `SESSLIMIT` (10) `MAXTCP` (20) `ENABLE_LINKED`
`DEFAULTLANG` `NUMCONSOLES` (3) `BOOTWIN` (6) colours.

### 2.2 INTERFACE block

Needs `TYPE` and `MTU`, else no boot. Keys: `ID`, `TYPE`
(AGW|ASYNC|AXIP|AXTCP|AXUDP|EXTERNAL|LOOPBACK|TCP|TUN|UDP|YAM), `PROTOCOL`
(ASCII|AX25|AXIP|AXTCP|AXUDP|DEDHOST|ETHER|HDLC|IP|KISS|MODEM|NETROM|NONE|PPP|SLIP|TNC|TNC2),
`COM` (device, tun name, or UDP remote port; `COM=0` parks it), `SPEED`, `FLOW`,
`INTNUM` (TCP listen port for AXTCP/TCP, local UDP port for UDP, AGW port),
`IOADDR` (AGW/TCP peer IP; TUN far-end IP), `KISSOPTIONS`
(NONE|POLLED|CHECKSUM|ACKMODE|SLAVE|NOPARMS), `CONFIG`, `CHANNEL(S)`, `APPLNUM`, `RADIO`.

```
INTERFACE=9          ; AXUDP: unlimited ports, one per partner
    TYPE=AXUDP
    MTU=256
ENDINTERFACE
PORT=8
    ID=AXUDP link with VK1UDP
    INTERFACENUM=9
    IPLINK=27.69.88.73   ; mandatory (with ID, INTERFACENUM)
    UDPLOCAL=93          ; XRouter receives on (default 93)
    UDPREMOTE=93         ; XRouter sends to (default 93)
    FRACK=2000
    RESPTIME=200
ENDPORT
```
AXUDP stack rule: no IPADDRESS means blocked. A localhost IPLINK or no
ETHERNET port means the Linux stack is used. Otherwise XRouter's stack, which
then needs IP routes (MAN:AXUDP-IFACE.6).
BPQ link example (`packet:xrouter:howtos:xrbpq`): BPQ `MAP GB7XRP localhost 9393 B`
with `UDP 10093`; XRouter `IPLINK=localhost UDPLOCAL=9393 UDPREMOTE=10093`.

AXIP (IP protocol 93): `TYPE=AXIP` + `MTU`. The port takes `IPLINK=` only (no
UDP ports). It needs CAP_NET_RAW. It is disabled without IPADDRESS. Only one
AXIP node per public IP. Do not set up AXIP and AXUDP to the same partner
(MAN:AXIP-IFACE.6).

AXTCP: `INTNUM=9393` makes a server. Each `CONFIG=<alias> <host> <tcpport>`
adds a client connection (several allowed). Exactly one PORT per AXTCP
interface. Always uses the Linux stack (MAN:AXTCP-IFACE.6).

KISS: serial `TYPE=ASYNC COM=/dev/ttyUSB1 SPEED=9600 PROTOCOL=KISS`; KISS over TCP
(Direwolf) `TYPE=TCP PROTOCOL=KISS IOADDR=127.0.0.1 INTNUM=8001 MTU=1500`,
ports select `CHANNEL=A..P` (`packet:xrpi-direwolf`, `packet:xrouter:howtos:xrkiss`).

TUN (MAN:TUN-IFACE.6):
```
INTERFACE=1
    ID=Tunnel to Linux
    TYPE=TUN
    COM=tun99            ; persistent tunnel name (or XRouter creates it)
    PROTOCOL=IP
    IOADDR=192.168.0.98  ; optional: Linux-end IP; XRouter creates and configures the tunnel
    MTU=1500
ENDINTERFACE
PORT=3
    ID=Tunnel
    INTERFACENUM=1
    IPADDRESS=192.168.0.99   ; XRouter end; must equal the tunnel *destination* address
ENDPORT
; IPROUTE.SYS:
IP ROUTE ADD 192.168.0.0/24 192.168.0.100 3 d
```
Without IOADDR the sysop configures the Linux end, e.g. in BOOTCMDS.SYS
`shell ip address add ...` / `wait 300` / `shell ip link set dev tun99 up`.
Tunnels need root or CAP_NET_ADMIN.

LOOPBACK: `TYPE=LOOPBACK PROTOCOL=NONE`, one port, for self-connect tests.

### 2.3 PORT block (MAN:PORTSMORE.6)

Required: `ID`, `INTERFACENUM`. L2: `FRACK` (7000), `RESPTIME` (2000; doc also
says 1500), `RETRIES` (10), `MAXFRAME` (3; 8-63 tries mod-128), `PACLEN`
(0 = adaptive), `PERSIST` (64), `SLOTTIME` (100), `TXDELAY` (300), `TXTAIL`
(100), `RFBAUDS` (1200), `KEEPALIVE`, `CHANNEL` (A).
Access: `CFLAGS` (3: 1 = uplinks, 2 = downlinks, 4 = apps may downlink,
8 = no L3RTT, 16 = L2 frag; sysop can always downlink), `EXCLUDE`, `VALIDCALLS`,
`USERS` (255), `SESSLIMIT` (255), `SYSOP` (0), `APPLMASK` (255).
Identity: `PORTCALL`, `PORTALIAS`, `PORTALIAS2` (digipeat-only alias that does
not accept connects), `PMSCALL`/`PMSALIAS`, `CHATCALL`/`CHATALIAS`,
`CTEXT=<line|file>`, `CTFLAGS` (1 = on connect to PORTALIAS, 2 = PORTCALL).
A port without a CTEXT loads `CTEXTn.SYS` or inherits the global one.
NetRom: `QUALITY` (10; 0 disables L3/L4 on the port), `MINQUAL`, `MINTXQUAL` (0),
`NODESINTERVAL` (0 = ignore received broadcasts), `MAXHOPS`, `MAXTT`, `PROXY`.
UI: `DIGIFLAG` (7), `DIGIPORT` (0 = same port), `UNPROTO=dest,digi,...`,
`IDPATH` (`ID`), `IDTEXT` (single line), `BCAST`, `BCFROM`, `APRSPATH`,
`PIPE=<port> [calls]`, `PIPEFLAG` (3), `MHEARD` (n slots, 0 = off; doc says
default 15, but an AXUDP port shows it off [live]), `MHFLAGS` (255; 1 direct,
2 direct digis, 4 digipeated, 8 separate).
IP: `IPADDRESS`, `NETMASK`, `IPLINK`, `UDPLOCAL`, `UDPREMOTE`, `DHCP`, `DYNDNS`.
Radio: `FULLDUP`, `SOFTDCD`, `TXPORT`, `INTERLOCK`, `CWID`, `FEC`, `FREQUENCY`, `INITSTR`.

### 2.4 APPL block (MAN:APPLS.9)

`APPL=1..8`, ending with `ENDAPPL`. Keys: `APPLNAME` (command-line shortcut),
`APPLCALL`, `APPLALIAS` (L2 connectable if the port APPLMASK bit is set),
`APPLQUAL` (non-zero means it is in NODES broadcasts and L4-connectable),
`APPLFLAGS` (1 = sysop, 2 = guests ok, 4 = XRouter sends `Connected to (applcall)`
to the user, 8 = sends `Connected to (usercall)` to the app), `APPLTYPE=TCP,[ip:]port`.
```
APPL=1
    APPLNAME=SYSOP
    APPLTYPE=TCP,8015
    APPLCALL=G9ZZZ
ENDAPPL
```
An APPL or command alias named `PMS` overrides the internal PMS.

### 2.5 Other config files

`IPROUTE.SYS` (§4), `ACCESS.SYS`, `PASSWORD.SYS`, `USERPASS.SYS`, `TELGUEST.ACL`,
`TELPROXY.ACL`, `HTTP.SYS` (rewrite/proxy), `HTTP.ACL`, `HTTPBAN.SYS`,
`BOOTCMDS.SYS` (console commands at boot), `CRONTAB.SYS`, `XRNODES` (saved
nodes/routes: `ROUTE ADD <call> <port> <qual> [!] [VIA d1 d2  ] [opts]`,
`NODE ADD <alias:call> <r1> <p1> <q1> [!] ...`), `ENCAP.TXT`/`XENCAP.TXT`,
`IGATE.CFG`, PMS files (§5). Boot order for IP: IPROUTE.SYS, then ENCAP.TXT, then BOOTCMDS.SYS.

## 3. Digipeating (MAN:DIGIFLAG.7, DIGIFLAG, APRS.9, PORTSMORE.6, BCAST.9)

DIGIFLAG bits (per port, default **7**, 0 = no digipeating):

| Value | Meaning |
|---|---|
| 1 | digipeat UI frames (normal digi via node call/alias) |
| 2 | digipeat non-UI (connected-mode) frames |
| 4 | RELAY generic (deprecated) |
| 8 | TRACE generic (deprecated) |
| 16 | WIDE generic (deprecated) |
| 32 | APRS 3rd-party digi via L4 |
| 64 | digi to Internet (IGate) |
| 128 | digi from Internet (IGate) |
| 256 | UITRACE n-N (inserts own call, decrements SSID) |
| 512 | UIFLOOD n-N (decrements SSID, does not insert call) |

- "Regular" digipeating uses XRouter's normal callsign or alias in the digi
  field. Bits 0 and 1 control it independently of the generic APRS bits.
  `PORTALIAS2` adds a digipeat-only alias.
- `UITRACE` (global) defaults to `TRACE` and `UIFLOOD` to `WIDE`. The New-N
  setup is `UITRACE=WIDE` and `UIFLOOD=GBR`. Duplicate suppression means a frame
  is not repeated twice.
- `DIGIPORT=n` sends digipeated frames out on port n, one port only.
- Examples: `DIGIFLAG=5` (UI + RELAY); `DIGIF 3 259` (UITRACE + normal);
  `DIGIF 2 0` (all off).
- `CFLAGS=0` on APRS-only ports stops connects while the digi keeps working.
- UI broadcast (not digipeating): received non-digipeated UI frames whose dest
  is in a port's `BCAST=MAIL,FBB` list are re-sent on every port with that
  dest in its BCAST. `BCFROM=` limits who may use it. If no port matches, the
  frame goes only on the receiving port.
- Pipes: `PIPE=2 [GB7PZT,KDRBBS]` and `PIPEFLAG` (1 UI not to us, 2 non-UI not
  to us, 4 UI to us, 8 non-UI to us, 16/32 our TX, 64 budlisted, 128 NetRom,
  256 IP/ARP, 512 bi-directional; suggested value 515).
- Beacons: `IDTEXT` every `IDINTERVAL` to `IDPATH` (default dest `ID`, no digis;
  e.g. `IDPATH=APRS,RELAY,WIDE`). An APRS position `!ddmm.mmN/dddmm.mmW#` within
  the first 40 chars sets the node position. `SEND <port> <dest> [V digis] text`
  sends a one-off UI frame.
- Stats: `S` / `STATS AX25` count "L2 Digipeated" per port (MAN:STATS.9).
- Regression G8 ("beacon digi via the node no longer relayed") falls under bit 1
  (UI digi) with default 7.

## 4. IP (MAN:IP, IPROUTE.SYS, ARP, IPADDRESS.7, IPIP.9, TUN-IFACE.6, IP-STACKS.6)

- XRouter has its **own IP stack** and also uses the Linux one. The global
  `IPADDRESS` is the core address, normally amprnet 44.x, and is the inner
  address for tunnels. A port `IPADDRESS` overrides it on that port. Global
  0.0.0.0 disables **all** IP.
- IP over AX.25: give the RF/AXUDP port an IPADDRESS (or inherit), add a route
  with mode `d` (datagram) or `v` (virtual circuit), and ARP entries for slow links:
  ```
  IP ROUTE ADD 44.131.95.0/24 44.131.95.240 9 d
  IP ROUTE DEFAULT 3 44.131.90.6 v
  ARP ADD 44.131.91.2 ax25 gb7pzt-5
  ARP PUB 44.131.91.127 ax25 g8pzt     ; proxy ARP
  ```
- Route syntax: `IP R[oute] A[dd] <host>[/len] <gateway> <port> [mode [metric [private]]]`.
  Modes: d datagram, v VC, n NetRom, e encap (proto 4), i IPIP (proto 94),
  u IPUDP (UDP 94), k kernel (Linux stack), r reject, s silent discard.
  For e/i/u/n/r/s the port is ignored (use 0). Also `ADDP[rivate]`,
  `D[rop] <host> <len>`, `DE[fault] <port> [gw [mode]]`, `L[ist]`, `LO[ad]`
  (reload IPROUTE.SYS), `LOO[kup] <host>`, `C[md] [0-1]`; `IP T[tl]`,
  `IP Q[uiet] <1 no echo reply|2 no proto-unreach|4 no TCP RST|8 no ICMP errors>`,
  `IP C[onfig]`, `IP H[eard]`, `IP BAN ...` (honeypot `IP BAN PORT ADD tcp 445`).
- IPROUTE.SYS takes `ACL PERMIT|DENY`, `ARP ADD|PUBLISH`, `DUN`, `IP CMD|ROUTE ADD|ROUTE DEFAULT|QUIET|TTL`,
  `NAT ADD`, `RIP ADD|LEARN|REFUSE|TIMEOUT`. It is read at boot and by `IP ROUTE LOAD`.
- AMPRNet tunnelling: set `IPADDRESS=44.x.x.x` (core) and the LAN IP on the
  Ethernet/TUN port. `IPIP=1` enables protocol 94, `IPENCAP=1` protocol 4.
  Route `IP ROUTE ADD 44.131.91.0/24 66.23.18.2 0 ipip` (gateway = partner's
  public IP). XENCAP.TXT: `route addprivate 44.0.0.0/8 ipip 66.23.18.2`.
  You may need `ACL PERMIT 0.0.0.0/32 0.0.0.0/0`. The front-end router must
  forward IP protocol 94 (or 4). IPUDP is the NAT-friendly alternative.
- Linux IP connectivity is via a TUN port (§2.2) plus routes. Note the AXIP rule:
  an EXTERN or TUN interface plus a non-localhost IPLINK makes AXIP use
  XRouter's stack and need IPROUTE.SYS routes.
- Default table with no IPROUTE.SYS: a single `0.0.0.0/0 gw 0.0.0.0 port 0 mode k` [live].
- ARP: `ARP [L[ist]]` shows `Host type Time Q Hw Address`. `ARP CMD` default 9
  (secure sysops only). TIMEOUT 900, WAIT 30, MAXQ 100. `ARP LEARN <port|default> on|off`.
- Diagnostics: `PING <host> [len [interval]]` (empty line aborts), `TR[acert] <host> [maxhops [ms]]`,
  `HOST`, `IP ROUTE LOOKUP <host>`, `STATS IP|ICMP|TCP|UDP`, `PCAP on|off`, `MTO <ip>[:port]`.
- Regression G11 (44/8 not routed out of TUN): test route lookup and ping
  through a TUN port with `IP ROUTE ADD 44.0.0.0/8 <linux-end> <tunport> d`.

## 5. PMS / BBS (MAN:PMS.9, PMSTYPE.7, PMS.CFG, FWD.SYS, `packet:xrouter:bbs`, HELP/PMS/*)

Config: `PMSCALL=G8PZT-2` (needed for direct L2 connect; must differ from
NODECALL), `PMSALIAS`, `PMSQUAL` (non-zero means NetRom-visible), `PMSHADDR` (needed to
forward), `PMSTYPE` (0 reserved, **1 PMS default** (reverse forward only),
2 forward + reverse, 3 adds relaying ("sleeper BBS"), **4 full BBS** (adds the `BBS`
command; via `PMS` only personal mail is shown)). Access is via `PMS [node]`,
`BBS` (type 4), NetRomX service 2, L2 to PMSCALL, or L4 to PMSALIAS. BYE/QUIT returns
to the node if entered from the node (`  - Logged off` then `PN0XR:XRNODE} Welcome back` [live]),
otherwise it disconnects.

Entry text and prompt [live] (relevant to G10):
```
PN0XR:XRNODE} Connected to PMS
[XR-505c-HM$]
Welcome to PN0XR's PMS
You have 0 new messages
Please use the 'NH' command to set your 'home' BBS.

[0] B,H,I,J,K,KM,L,LM,LN,M,N,R,SB,SP,SR,U,? >
```
`[n]` is the current message number, updated after read/kill/send.

User `? *` list [live]: `? Bye CB CP Help Info I@ IC IH IN IQ IZ Jlist JKlist Kill
K> K< KM List L$ L> L< L@ LA Lang LB LC LF LL LM LN LO LP LQ LR LS LT LU LUP
Mine Name NC NH NI NL NP NQ NZ OLR Read R> R< R@ RH RM RN ROute SB SP SR Unread`.

Main commands (MAN:PMS.9): `<n> [n...]` read; `R[ead] <n..>` read without routing
headers; `RH <n..>` read with `R:` lines and RFC822 headers; `RM`, `RN`,
`R> to`, `R< from`, `R@ at`; `L[ist] [n | f l]`, `L <n` (n onwards), `LL n` (last n,
newest first), `LM`, `LN`, `LB`, `LP`, `LU`, `LR`, `LF`, `L$`, `LS text`,
`LT text`, `L> to`, `L< from`, `L@ at`, `LA/LO n`, `LC`; `S` (to sysop), `SP <call>`,
`SB <topic>`, `SR`; `K[ill] <n..>`, `KM`, `K> call`, `K< call`; `CB`/`CP` copy;
`U <n>` unread; `N`/`NH`/`NQ`/`NZ`/`NC`/`NP`/`NI` user record; `I`/`I@`/`IC`/`IH`/`IN`/`IQ`/`IZ`
white pages; `J`. Sysop-only: `EH`, `EX[port]`, `IM[port]`, `HO[ld]`, `UH`,
`FF` (force forward), `FP` (force poll), `SF`, `VF`, `KF`, `KH`, `KR`, `K@`,
`LH`, `MB`, `MF`, `MFH`, `MP`. Non-sysops may only kill their own messages.

Session transcripts [live]:
```
SP PN0XR
To: PN0XR @ PN0XR
Enter subject (or empty line to abort):
Test subject
Enter message, ending ctrl-Z or /EX (/QQ to abort)
Line one of body
/EX
*** Message 1 saved
L
 Msg# TS Rcvd  Size  To      At     From   Subject
    1 PN 16:59  244  PN0XR          PN0TST Test subject
1            (or R 1)
Msg#: 1  Type: PN  Size: 244
Rcvd: 13/10/26 at 16:59   Created: 13/10/26 at 16:59Z
From: PN0TST
To:   PN0XR
MID:  ACE6363010XR
Subj: Test subject
<blank><blank>Line one of body
[ end of message 1 ]
K 1  ->  Msg 1 deleted
L    ->  No messages found
SB ALL -> To: ALL @ PN0XR ... list shows "2 BN ... ALL ... PN0TST Bull subject"
```
Status letters: ' ' unread local, `$` unforwarded, `F` forwarded, `R` read,
`H` held. TS column = type (P/B) + status (N new).

Forwarding: DISTRIB.SYS decides *what* is queued to whom. FWD.SYS (PMS dir, read
live) decides *when and how*, in blocks:
```
@GB7NXT F          ; F=forward, P=poll
0-6                ; days (0=Sun)
0-23               ; hours
C KIDDER           ; connect script: T secs, C call, S text, W text
C GB7NXT
W NXTNOD:GB7NXT}
S BBS
------
```
PMS.CFG: `SysopCallsign`, `HousekeepInterval` (24 h), `ForwardInterval` (900 s),
`FwdKickOnRcv` (1), `AutoRenumber` (0), `MaxAgeB` (30), `MaxAgePR` (180),
`MaxAgeMid` (30), `WpUpdateTo`. Other files: BADWORDS.SYS, EXPORT.SYS,
HOLD.SYS, REJECT.SYS; `PMS/mail.in` is auto-imported. Messages are stored as
files in `PMS/`. Supports SID/MID/BID, MBL forwarding, FBB compressed
(regression G9: compressed forward ok but read-by-number disconnects).

## 6. NET/ROM, INP3, route selection (MAN:NODES, ROUTES, INP3.9, TDR.9, PERMLINKS.9, AUTOQUAL.9, QUALITY.7, PORTSMORE.6)

- Two separate metric domains in one node table. **Quality** (NetRom
  broadcasts, UI every NODESINTERVAL) and **time** (INP3 unicasts: trip time in
  10 ms units, horizon 60000; hops, horizon 30). They are never converted into
  each other. Nodes learned only via INP3 are stored with quality 0. XRouter
  "considers information from both domains when making routing decisions". The
  docs give no exact comparison rule, so tests must pin the observed 505c
  behaviour (G7: INP3 route via a neighbour preferred over a direct 1-hop
  quality-192 route).
- Neighbour quality: port `QUALITY` (default 10) or `ROUTE ADD` qual. A node's
  quality via a neighbour comes from the broadcast quality derated by the route
  quality (standard NetRom). It must be >= MINQUAL to be accepted.
  `MINTXQUAL` limits what is broadcast. `QUALADJUST` derates by callsign.
  `BLEVEL` derates the budlist. Route qual 256-511 means autoqual starting at
  qual-256.
- Obsolescence: a node is set to `OBSINIT` (5) when heard and decremented each
  broadcast; below `OBSMIN` (3) it is obsolete. `Obs2` is the separate counter
  for time metrics.
- INP3 (MAN:INP3.9): RIFs on the L2 inter-node link, PID 0xCF. A RIF is `0xFF`
  then RIPs (`axcall, hops, tt(2 bytes), options(len,type 0=alias 1=IP)`) then `0x00`.
  Positive info is sent on schedule (INPBCINTERVAL, doc 600 s). Negative info
  is sent at once. Poisoned reverse. `MAXTT`/`MAXHOPS` (global/port/route) cap
  what is accepted. A route MAXTT of 0 disables INP3 on it. `MAXTT=0` or
  `MAXHOPS=0` gives pure NetRom; `MINQUAL=255` gives pure time domain.
- Permanent links: if port QUALITY and NODESINTERVAL are both non-zero, XRouter
  connects L2 to every newly heard neighbour, measures RTT (L3RTT every
  L3RTTINTERVAL), and checks every T3. A failed link marks all its nodes
  unusable. Route state flags in `R`: `>` open, `~` opening, `x` failed, blank
  closed. `!` at the end means locked.
- Commands and outputs:
  - `N` lists `ALIAS:CALL` in columns, then `n nodes found` [live]. Hidden `#`
    aliases are excluded (`N *` includes them). Filters: `N +`, `N > q`, `N < q`,
    `N B call`, `N C`, `N F`, `N H`, `N I`, `N J`, `N N`, `N O`, `N P`, `N Q`, `N R`,
    `N S`, `N T`, `N V call`, `N X`, `N HE`. A node added by hand behind a
    not-yet-open route is **not** listed by bare `N` but is shown by `N <call>` [live].
  - `N <call|alias>` gives a detail block and `Routes to:` [live, 505c format has an RF column]:
    ```
    Routes to: FARNOD:PN0FAR
      Qty Obs Pt Via          Stt  Hop Obs2 RF
      150  5   1 PN0NB        0.00  0   0   Y <
    ```
    `>` marks the active route and `<` the preferred one. Doc example (older):
    `> 150  5   5 G4FPV   1.22  1   4 <`. The info line reads
    `Info for: MLVN:G4FPV FR=3538 RTT=2.8 Q=0 Hop=1 {PEER}` plus `Supports:
    INP3 L3ROUT NRR NCMP L4X NDP PMS XRCHAT RTCHAT`.
  - `R` [live]: `Port Callsign  Qty Nod RF` / `~  1 PN0NB     192   1! N `.
    Doc format: `>  5 G4FPV 150 70!`. Options: `R L|Q|R|T|X [port]`, `R <port> <call>`
    (full page), `R *`, `R **`. `R T` columns `Tdr Stt Flg Maxtt/hops` (Flg 1 locked,
    2 INP3, 4 L3RTT, 8 XRouter, 16 autoqual).
  - `ROUTE ADD PN0NB 1 192 !` replies `Ok`. `NODES ADD PN0FAR:FARNOD PN0NB 1 150` replies `Ok`.
    `NODES DROP PN0FAR` replies `Ok` [live].
  - `N BC T` [live]:
    ```
    Nodes Broadcast Times:
      Interval (mins):      60
      Next Bcast in secs:   21
      Next Bcast Due:       16:59:21
    INP3 Unicast Times:
      Interval (secs):      3600      <-- default shown is 3600, MAN says 600 (cf. G4)
      Last Full Update:     ---
    ```
  - `BCAST <port>` / `N BC <port>` force a broadcast. `BCPOLL <port>` asks
    neighbours to broadcast. `SAVENODES`/`LOADNODES`. `NRR`, `NPING`,
    `NTRACERT`. `L4` for circuits.
- Own services appear in `N` as nodes: `XRCHAT:PN0XR-8 XRPMS:PN0XR-2`
  (CHATCALL/PMSCALL with non-zero quals) [live]. APPLQUAL does the same for apps.
- Known issues from groups.io: G5 own-node tt 0, G6 broadcasts only on first port.

## 7. HTTP server, REST, MQTT, RHP, AGW

### 7.1 HTTP (MAN:HTTP-SRV.9, HTTPPORT.7, `packet:xrouter:full-fat`, `:htmlinfopage`)
- `HTTPPORT` (80; also NetRomX service 80). Root is `HTTPROOT` (default `HTTP/`).
  Climbing out of the root gets the client IP banned. `INDEX.HTM` then `DEFAULT.HTM`.
- Without an index, `/` is the inbuilt "legacy" summary page [live]:
  `<title>Node XRNODE:PN0XR Information Summary</title>` with a link to `/info`.
- Full-fat pages (inbuilt) [live links from `/info`]: `/info`, `/ports`, `/links`,
  `/routes`, `/nodes`, `/stats`, `/users`, `/terminal`, `/chat`, `/pms`, `/admin`.
  Writable pages (terminal, chat, pms, wall, blog) need auth unless the client is
  LAN or flagged 8 in ACCESS.SYS. CSS can be customised.
- Command execution: `GET /exec?cmd=n&arg1=h` runs `N H` inside the EXEC.HTM
  template (`<TEXT>` tag). SSI tags: `<!--#ECHO VAR=DATE_LOCAL -->`,
  `<!--#EXEC CMD="r r" -->`, `FLASTMOD`, `FSIZE`, `INCLUDE FILE|VIRTUAL`.
  Also URL rewrite and proxy (HTTP.SYS, HTTP.ACL) and HTTPBAN.SYS URL patterns
  (IP ban up to 200 hosts). Unknown path gives `404 text/html`
  `HTTP error 404 - Not Found` [live].

### 7.2 REST (JSON, MAN:REST-*.9)
| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/netrom/nodes` | `[{"id":"PN0XR-8","alias":"XRCHAT"},...]` [live] |
| GET | `/api/v1/netrom/nodes/{call}` | `id alias qual rtt hops sent rcvd queue position locator qth ipaddr tcp software version` [live] |
| GET | `/api/v1/netrom/routes[?port=n][&detail=n or l2,inp,rty,rat,arq,tim]` | `id port call qual sntt lock state(closed/opening/open/failed) nodes` |
| GET | `/api/v1/netrom/routes/{id}` | |
| GET | `/api/v1/netrom/circuits` | `[]` when idle [live] |
| GET | `/api/v1/mail/msgs[?offset&maxitems&to&at&from&subject]` | 505c returns `{"filters":{...},"msgs":[{id,mid,rcvd,dated,size,type,status,to,from,subject,links:[{rel:"view",href},{rel:"delete",...}]}]}` [live]; the MAN describes a bare array |
| GET | `/api/v1/mail/msgs/{n}` | adds `text` (with headers) |
| POST | `/api/v1/mail/msgs` | JSON `{from,to,type:"P"|"B",subject,text}` gives `{"id":22}`. Needs `Content-Type: application/json`, else 415. |
| GET/POST | `/api/v1/wall/posts[/{n}]`, `/api/v1/blog/posts[/{n}]` | |
| GET | `/api/v1/weather/stations[/{id}]` | |
Errors: 400 bad resource, 404 unknown API, 415 non-JSON POST.

### 7.3 RHP (Remote Host Protocol v2, `packet:white-papers:pwp-0222`, `:pwp-0245`, MAN:RHPPORT.7)
- TCP `RHPPORT` (doc default 9000; **505c did not listen on 9000 when RHPPORT
  was not set** [live]; interop configs set `RHPPORT=9000`). Frames are a 2-byte
  big-endian length followed by a JSON object. WebSocket at `ws://host:port/rhp`.
- Localhost and LAN (10/8, 172.16/12, 192.168/16) need no auth. Others send
  `{"type":"auth","user":..,"pass":..}` (checked against USERPASS.SYS), reply
  `authReply` errCode 0 or 14. ACCESS.SYS flag 8 whitelists.
- Messages: `open`/`openReply` (pfam `unix|inet|ax25|netrom`, mode
  `stream|dgram|seqpkt|custom|semiraw|trace|raw`, port, local, remote, flags
  0x80 active, 0 passive/listen, 1/2/4 trace in/out/S), `accept` (handle,
  child, remote, local, port), `status` (flags 1 CONOK, 2 CONNECTED, 4 BUSY),
  `statusReply`, `send`/`sendReply` (has `status`), `recv` (seqno, handle, data;
  trace adds action/port/srce/dest/ctrl/frametype...), `close`/`closeReply`,
  BSD style `socket`, `bind`, `listen`, `connect`, `sendto` and their `*Reply`.
  A request `id` is echoed. Without an id only errors (and openReply) are sent.
- Addresses: AX25 `g8pzt-1`; NETROM `<user>[@node][:svc]`; INET `ip[:port]`.
- Error codes: 0 Ok, 1 Unspecified, 2 Bad or missing type, 3 Invalid handle,
  4 No memory, 5 Bad mode, 6 Invalid local address, 7 Invalid remote, 8 Bad family,
  9 Duplicate socket, 10 No such port, 11 Invalid protocol, 12 Bad parameter,
  13 No buffers, 14 Unauthorised, 15 No Route, 16 Operation not supported.
- Known (PROGRESS.md G1-G3): bindReply JSON malformed, listen on listener
  refused since 505d, send/sendto reply without handle.

### 7.4 MQTT (`packet:xrouter:mqtt-iface`, MAN:MQTT-SRV.9, MQTT-PUB.9)
- Internal broker on `MQTTPORT` (1883, also NetRomX 1883). The publisher to an
  external broker is enabled by `MQTTSERVADDR` (+ `MQTTSERVPORT`).
- Topics: `xrouter/get/{nodecall}/{nodes|routes|links|circuits|users|recent|jlist|mheard|config|channels|wx|allwx|node/{call}|mail/msg/{n}|wall/msg/{n}|blog/msg/{n}}`,
  replies on `xrouter/status/{nodecall}/{resource}`; put:
  `xrouter/put/{nodecall}/{chat|mail|wall|blog|wx|ax25/{port}|kiss/{iface}|ipv4|nr3b}`;
  events: `xrouter/event/{nodecall}/{session|link|circuit|pmsg|chat/{type}|wall|blog|wx|radio/{n}}`;
  raw: `xrouter/{kiss|ax25|ipv4|nr3b}/{nodecall}/{rcvd|sent}[/{n}]`.

### 7.5 Other TCP services
Telnet 23 (user), RLOGIN 513 (sysop), TELPROXY 2323 (binary after login,
TELPROXY.ACL), CHAT 3600, AGW emulator `AGWPORT` 8000 (UI-View etc.), APRS server 1448,
FTP 21, FINGER 79, ECHO 7, DISCARD 9, TTYLINK 87, SOCKS 1080 (MAN:TCP-PORTS.6).
AGW interface to an external AGWPE/Direwolf: INTERFACE `TYPE=AGW`, `IOADDR`, `INTNUM`.

## 8. Chat server (MAN:CHAT-SRV.9, `packet:xrouter:chatserver`)
`CHAT` command, NetRomX svc 8, L2 to CHATCALL/CHATALIAS, TCP 3600. Channels 1-255
local (except 101), 256-32767 global over XRchat links (`CHATLINKS`), 101 is
the RoundTable/BPQChat gateway (topics, default `general`), negative numbers
are Tampa Ping-Pong. Default login channel 1000. Sysop channel 1234. Commands
start with `/`: `/ALERT /ANSI /BELL /BYE /CHANNEL /ECHO /EXIT /HEADERLN /JOIN
/KEEPALIV /KM /KNOWN /LEAVE /LINKS /MSG /NAME /NODES /PERSONAL /PORTS /QTH /QUIT
/RECENT /RM /STAMP /STATUS /TOPIC /USER /USERS /VERBOSE /VERSION /WHO`.

## 9. Test-harness notes [live]
- Ports below 1024 did not bind in the container (telnet 23 refused). Use e.g.
  `TELNETPORT=8023`, `HTTPPORT=8080`, `RHPPORT=9000` explicitly.
- Minimal bootable config: `NODECALL`, `NODEALIAS`, `IPADDRESS` (non-zero),
  one AXUDP INTERFACE + PORT, plus CTEXT/INFOTEXT/IDTEXT blocks. ACCESS.SYS
  `0.0.0.0/0 1` gives callsign-only login. PASSWORD.SYS `PN0XR sysoppass` lets
  `@ sysoppass` grant sysop.
- Boot errors go to `LOG/BOOTLOG.TXT`. The container exits with code 255.
