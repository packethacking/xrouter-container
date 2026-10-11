# XNet 1.38 (DL1GJI) Linux build, for the interop suite only.
#
# XNet is closed source with no licence to redistribute, so this image is
# only ever built locally and never pushed. The binary is fetched from the
# distribution site at build time and checked against a known sha256.

FROM debian:bookworm-slim AS fetch
ARG XNET_URL=http://www.nl3prc.nl/packet/xnet-linux/xnet1.38/xnet1.38.tar
ARG XNET_SHA256=a3a9e20f4c415dea35802b14a1994d3932ae323b0d46097f2f2ef6df70e4171b
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL -o /tmp/xnet.tar "$XNET_URL" \
 && echo "$XNET_SHA256  /tmp/xnet.tar" | sha256sum -c - \
 && mkdir /tmp/x && tar -xf /tmp/xnet.tar -C /tmp/x linuxsnet \
 && chmod 755 /tmp/x/linuxsnet

FROM debian:bookworm-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 \
 && rm -rf /var/lib/apt/lists/*
COPY --from=fetch /tmp/x/linuxsnet /xnet/linuxsnet
COPY xnet_console.py /xnet/xnet_console.py
COPY AUTOEXEC.NET.tmpl /xnet/AUTOEXEC.NET.tmpl
ENV XNET_CALL=PN0XN \
    XNET_ALIAS=XNET \
    XNET_PEER_IP=172.28.77.10 \
    XNET_UDP_LOCAL=10093 \
    XNET_UDP_DEST=20007 \
    XNET_NODES_INTERVAL=300 \
    XNET_RTT_INTERVAL=30 \
    XNET_CONSOLE_PORT=8023
EXPOSE 8023
ENTRYPOINT ["python3", "-u", "/xnet/xnet_console.py"]
