#!/bin/sh
# Render the TNN config from templates and environment, then run TNN.
#
# Environment (defaults suit the interop suite):
#   TNN_CALL         node callsign                 (PN0TN)
#   TNN_ALIAS        node alias                    (TNN)
#   TNN_AXUDP_PORT   local UDP port for AX25IP     (10093)
#   TNN_PEER_CALL    neighbour callsign            (PN0XR)
#   TNN_PEER_ALIAS   neighbour alias               (XRNODE)
#   TNN_PEER_IP      where to send AXUDP           (172.28.77.10, the relay)
#   TNN_PEER_PORT    UDP port at TNN_PEER_IP       (20007)
#   TNN_TELNET_PORT  telnet console port           (23)
#   TNN_NODES_10S    NODES broadcast interval for non-INP3 neighbours,
#                    in 10 s units                 (6)
#   TNN_SYSOP_PW     sysop password; SYSOP asks for 5 characters of it
#   TNN_CONSOLE_PW   console password              (Geheim)
set -eu
: "${TNN_CALL:=PN0TN}"
: "${TNN_ALIAS:=TNN}"
: "${TNN_AXUDP_PORT:=10093}"
: "${TNN_PEER_CALL:=PN0XR}"
: "${TNN_PEER_ALIAS:=XRNODE}"
: "${TNN_PEER_IP:=172.28.77.10}"
: "${TNN_PEER_PORT:=20007}"
: "${TNN_TELNET_PORT:=23}"
: "${TNN_NODES_10S:=6}"
: "${TNN_SYSOP_PW:=SSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSS}"
: "${TNN_CONSOLE_PW:=Geheim}"
export TNN_CALL TNN_ALIAS TNN_AXUDP_PORT TNN_PEER_CALL TNN_PEER_ALIAS TNN_PEER_IP \
       TNN_PEER_PORT TNN_TELNET_PORT TNN_NODES_10S TNN_SYSOP_PW TNN_CONSOLE_PW

cd /usr/local/tnn
for f in tnn.ini ax25ip.cfg tnn179.tnb tnn179.pas; do
  envsubst < "/etc/tnn-templates/$f" > "$f"
done
rm -f tnn.pid
exec ./tnn "$@"
