#!/bin/sh
set -eu

bundle_path=$1

# Flutter 3.47 includes the default flavor in the Linux output path.
flavored_bundle=${bundle_path%/release/bundle}/f_generic/release/bundle
if [ -x "$flavored_bundle/mhabit" ]; then
    bundle_path=$flavored_bundle
elif [ ! -x "$bundle_path/mhabit" ]; then
    printf 'Cannot find the mHabit bundle in %s or %s\n' "$bundle_path" "$flavored_bundle" >&2
    exit 1
fi

install -D "$bundle_path/mhabit" /app/bin/mhabit
cp -r "$bundle_path/lib" /app/bin/lib
cp -r "$bundle_path/data" /app/bin/data
