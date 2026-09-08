#!/bin/sh
set -e

matrix-jitsi-bot db migrate

exec matrix-jitsi-bot "$@"
