#!/usr/bin/env bash
# Run the full release check: unit tests, self check, wheel build, wheel digest.
#
# Run me when: before a release, and before I ask the operator to tag a release.
#
# Usage: release_check.sh
#   1. Run the unit tests.
#   2. Run the checks of this repository with the profile full.
#   3. Build a wheel in a temporary folder outside the repository.
#   4. Print the SHA-256 of the wheel.
# The script stops at the first failure. It leaves no file in the repository.
# The wheel build needs the build tool (setuptools) to be available.
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$root"

tmp=$(mktemp -d)
# The wheel build can leave build folders in the source tree. Remove those that did not exist before.
leftovers=()
for item in build src/deterministic_controls.egg-info; do
  [ -e "$item" ] || leftovers+=("$item")
done
cleanup() {
  rm -rf "$tmp"
  if [ "${#leftovers[@]}" -gt 0 ]; then
    rm -rf "${leftovers[@]}"
  fi
}
trap cleanup EXIT

# Keep Python from writing bytecode into the repository.
export PYTHONDONTWRITEBYTECODE=1

echo "== unit tests"
python3 -m unittest discover -s tests

echo "== self check (profile full)"
PYTHONPATH=src python3 -m deterministic_controls check --root . --profile full

echo "== wheel build"
python3 -m pip wheel . --no-deps -w "$tmp"

wheels=("$tmp"/*.whl)
if [ ! -f "${wheels[0]}" ]; then
  echo "release_check: no wheel was built" >&2
  exit 1
fi
if [ "${#wheels[@]}" -ne 1 ]; then
  echo "release_check: expected one wheel, found ${#wheels[@]}" >&2
  exit 1
fi

echo "== wheel digest"
sha256sum "${wheels[0]}" | sed "s#  .*/#  #"
