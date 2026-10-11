# TheNetNode (TNN) 1.79 for the NET/ROM + INP3 interop suite.
#
# TNN is licensed for non-commercial use only (NORD><LINK ALAS), so this
# image must never be pushed to a registry. It is only ever built locally
# by docker compose. The source is cloned at a pinned commit and built in
# a throwaway stage.
#
# The build is 32-bit (i386 base image) on purpose: TNN puts a pointer
# into its L3RTT frames as a decimal number, and a 64-bit build overflows
# the L3RTT number fields.
#
# Build args shorten two compile-time timers so a test run takes minutes:
#   TNN_L3RTT_SECS     L3RTT probe interval per neighbour (stock 180 s)
#   TNN_INP_FULL_10S   full INP3 RIF refresh to each INP neighbour, in
#                      10 s units (stock 360 = one hour). Changes are sent
#                      every 10 s regardless.

ARG TNN_REPO=https://github.com/dl1ne/tnn179.git
ARG TNN_SHA=53aa7c2b77b1505f8e5b3b47f9c1da06a6590302

FROM --platform=linux/386 i386/debian:bookworm-slim AS build
ARG TNN_REPO
ARG TNN_SHA
ARG TNN_L3RTT_SECS=30
ARG TNN_INP_FULL_10S=12
RUN apt-get update \
 && apt-get install -y --no-install-recommends gcc libc6-dev make git ca-certificates \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /src/tnn179
RUN git init -q . \
 && git remote add origin "$TNN_REPO" \
 && git fetch -q --depth 1 origin "$TNN_SHA" \
 && git checkout -q FETCH_HEAD \
 && test "$(git rev-parse HEAD)" = "$TNN_SHA"
# Shorten the timers; grep -q makes the build fail if the source moved.
RUN grep -q '^#define L3_RTT_TIME 180 ' include/l3local.h \
 && sed -i "s/^#define L3_RTT_TIME 180 /#define L3_RTT_TIME ${TNN_L3RTT_SECS} /" include/l3local.h \
 && grep -q 'if (++pp->brotim >= 360)' src/l3misc.c \
 && sed -i "s/if (++pp->brotim >= 360)/if (++pp->brotim >= ${TNN_INP_FULL_10S})/" src/l3misc.c
RUN make CC="gcc -fcommon" tnn \
 && install -d /out/usr/local/tnn \
 && install -m 0755 bin/tnn /out/usr/local/tnn/tnn

FROM --platform=linux/386 i386/debian:bookworm-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends gettext-base procps \
 && rm -rf /var/lib/apt/lists/*
COPY --from=build /out/usr/local/tnn/tnn /usr/local/tnn/tnn
COPY templates/ /etc/tnn-templates/
COPY entrypoint.sh /entrypoint.sh
RUN chmod 0755 /entrypoint.sh \
 && mkdir -p /usr/local/tnn/textcmd /usr/local/tnn/userexe /usr/local/tnn/sysexe \
             /usr/local/tnn/pacsat /usr/local/tnn/msg /usr/local/tnn/httpd /usr/local/tnn/speech
WORKDIR /usr/local/tnn
ENTRYPOINT ["/entrypoint.sh"]
