#!/bin/sh
# Build the lite image in the isolated Lima VM (linux/amd64 via Rosetta). No upload.
set -eu
L="env LIMA_HOME=/Users/pyryouri/Developer/.tuppi-linux /Users/pyryouri/Developer/toolchains/lima-2.2.1/bin/limactl"
$L start --tty=false tuppi
$L shell tuppi sudo docker build --platform linux/amd64 -t tuppi-online:lite /Users/pyryouri/Developer/deploy/TuppiNetwork-lite
$L shell tuppi sudo docker image inspect tuppi-online:lite --format '{{.Id}} {{.Os}}/{{.Architecture}}'
