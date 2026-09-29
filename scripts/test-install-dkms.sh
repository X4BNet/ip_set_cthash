#!/usr/bin/env bash

set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
work_dir=$(mktemp -d /tmp/ip-set-cthash-dkms-test.XXXXXX)
trap 'rm -rf "$work_dir"' EXIT

module_name=ip-set-cthash
module_version=$(cd "$repo_root/src" && ./version.sh)

run_case() {
    local name=$1
    local retain_other_kernel=$2
    local case_dir="$work_dir/$name"
    local source_root="$case_dir/usr-src"
    local source_dir="$source_root/$module_name-$module_version"
    local state_dir="$case_dir/state"
    local log_file="$case_dir/dkms.log"
    local target_kernel=6.12.109-x4b+zen2

    mkdir -p "$source_dir" "$state_dir/kernels"
    touch "$source_dir/old-source" "$state_dir/registered"
    touch "$state_dir/kernels/$target_kernel"
    if [[ "$retain_other_kernel" == true ]]; then
        touch "$state_dir/kernels/6.12.109-x4bparse+zen2"
    fi

    PATH="$repo_root/scripts/test-fixtures/install-dkms:$PATH" \
    DKMS_SOURCE_ROOT="$source_root" \
    KVERSION="$target_kernel" \
    MOCK_DKMS_LOG="$log_file" \
    MOCK_DKMS_STATE="$state_dir" \
    MOCK_MODULE_NAME="$module_name" \
    MOCK_MODULE_VERSION="$module_version" \
    MOCK_SOURCE_DIR="$source_dir" \
        "$repo_root/src/install-dkms.sh" --install

    test -f "$state_dir/registered"
    test -f "$state_dir/kernels/$target_kernel"
    test -f "$source_dir/Makefile.in"
    test ! -e "$source_dir/old-source"
    grep -Fqx "remove $module_name/$module_version -k $target_kernel" "$log_file"
    grep -Fqx "build $module_name/$module_version -k $target_kernel" "$log_file"
    grep -Fqx "install $module_name/$module_version -k $target_kernel" "$log_file"

    if [[ "$retain_other_kernel" == true ]]; then
        test -f "$state_dir/kernels/6.12.109-x4bparse+zen2"
        ! grep -Fqx "add $module_name/$module_version" "$log_file"
    else
        grep -Fqx "add $module_name/$module_version" "$log_file"
    fi
}

run_case multi-kernel true
run_case single-kernel false

echo "install-dkms tests passed"
