#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

git submodule update --init --depth=1 --filter=blob:none pak-public-kit
git -C pak-public-kit sparse-checkout init --cone
git -C pak-public-kit sparse-checkout set output/data output/scripts
git -C pak-public-kit fetch --depth=1 --filter=blob:none origin master
git -C pak-public-kit switch --detach FETCH_HEAD
git -C pak-public-kit sparse-checkout reapply
