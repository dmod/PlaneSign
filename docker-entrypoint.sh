#!/bin/sh
set -eu

PLANESIGN_ROOT=/planesign
DATAFILES_DIR="$PLANESIGN_ROOT/datafiles"
DATAFILES_SEED_DIR="$PLANESIGN_ROOT/datafiles.init"

# Seed the host-mounted datafiles directory with built-in defaults if it's empty.
if [ -d "$DATAFILES_DIR" ]; then
  if [ -z "$(find "$DATAFILES_DIR" -mindepth 1 -print -quit 2>/dev/null)" ]; then
    echo "Seeding $DATAFILES_DIR with built-in PlaneSign datafiles..."
    cp -an "$DATAFILES_SEED_DIR"/. "$DATAFILES_DIR"/
  fi
fi

exec "$@"
