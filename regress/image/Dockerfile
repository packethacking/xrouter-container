# The XRouter image under test plus the Linux networking tools a typical
# host has (ip, ifconfig, ping, tcpdump). XRouter shells out to them for
# some things, e.g. bringing up a TUN interface from IOADDR; the published
# image is deliberately minimal and lacks them. Test-only, never pushed.
ARG XROUTER_IMAGE=ghcr.io/packethacking/xrouter:latest
FROM ${XROUTER_IMAGE}
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      iproute2 net-tools iputils-ping tcpdump procps strace \
 && rm -rf /var/lib/apt/lists/*
