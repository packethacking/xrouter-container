# Multi-arch image for XRouter, the closed-source packet node by G8PZT.
# Binaries are mirrored on OARC compute object storage under canonical
# names; the workflow / build.sh feeds the right URL + sha256 for each
# (version, arch) combination via build args.
#
# The fetch stage runs on the build host's native arch (faster than QEMU
# for a tarball download + sha verify), then COPY --from=fetch lifts the
# results into the target-arch runtime image.

FROM --platform=$BUILDPLATFORM debian:bookworm-slim AS fetch

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        unzip \
    && rm -rf /var/lib/apt/lists/*

ARG SUPPORT_URL
ARG SUPPORT_SHA256
ARG BIN_URL
ARG BIN_SHA256

WORKDIR /work

# Support tree: HELP/MAN/INFO/MISC + sample .SYS / .ACL / .CFG files.
# The dummy XROUTER.CFG is renamed to .example so the entrypoint won't
# auto-copy it into /data on first run — sysops should bring their own.
RUN curl -fsSL -o support.zip "$SUPPORT_URL" \
    && echo "$SUPPORT_SHA256  support.zip" | sha256sum -c - \
    && unzip -q support.zip -d unzipped \
    && mv unzipped/xrouter /skel \
    && mv /skel/XROUTER.CFG /skel/XROUTER.CFG.example

# Prepend a Docker-specific note to the example. The static-linked
# binary cannot use the glibc system resolver (NSS modules are
# dynamic), so any hostname lookup XRouter performs — IGATE,
# DynDNS, AMPR routing, etc. — needs an explicit DNS= directive.
# The annotated MISC/XROUTER.CFG does document DNS= at line ~339,
# but its comment mis-states that it's optional for Linux; on a
# static build it is mandatory for any hostname resolution. We
# therefore add the directive (Google Public DNS) up front, with
# context, so anyone copying the example into XROUTER.CFG starts
# off in a working state.
RUN { \
        printf '%s\n' \
        '# ---------------------------------------------------------------------' \
        '# This file shipped with the packethacking/xrouter Docker image.' \
        '#' \
        '# The XRouter binary in the image is statically linked, which means' \
        '# the glibc system resolver is unavailable: any DNS lookup XRouter' \
        '# performs (IGATE, DynDNS, AMPR routing, etc.) requires an explicit' \
        '# DNS= directive. The line below uses Google Public DNS; replace' \
        '# with your preferred resolver if you wish.' \
        '# ---------------------------------------------------------------------' \
        'DNS=8.8.8.8' \
        '' ; \
        cat /skel/XROUTER.CFG.example ; \
    } > /skel/XROUTER.CFG.example.new \
    && mv /skel/XROUTER.CFG.example.new /skel/XROUTER.CFG.example

# Per-arch ELF, fetched as a bare binary — no archive to unpack.
RUN curl -fsSL -o /xrouter "$BIN_URL" \
    && echo "$BIN_SHA256  /xrouter" | sha256sum -c - \
    && chmod +x /xrouter


FROM debian:bookworm-slim AS runtime

COPY --from=fetch /skel /opt/xrouter/skel
COPY --from=fetch /xrouter /usr/local/bin/xrouter
COPY docker/entrypoint.sh /usr/local/bin/xrouter-entrypoint.sh
RUN chmod +x /usr/local/bin/xrouter-entrypoint.sh

ARG XROUTER_VERSION
LABEL org.opencontainers.image.source="https://github.com/packethacking/xrouter-container"
LABEL org.opencontainers.image.title="xrouter"
LABEL org.opencontainers.image.description="XRouter packet radio node, packaged for Docker"
LABEL org.opencontainers.image.version="$XROUTER_VERSION"

# /data is the working directory at runtime — XROUTER.CFG lives here
# along with state files (XRNODES, LOG/, CHAT/, PMS/, etc.).
VOLUME ["/data"]
WORKDIR /data

# Common defaults from the example cfg: telnet 23, HTTP 80, telnet
# proxy 2323. The dummy cfg shipped with XRouter has these disabled
# (loopback only). Override via XROUTER.CFG and re-publish as needed.
EXPOSE 23/tcp 80/tcp 2323/tcp

ENTRYPOINT ["/usr/local/bin/xrouter-entrypoint.sh"]
