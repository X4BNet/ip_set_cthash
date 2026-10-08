#!/usr/bin/env bash

set -euo pipefail

module_name=ip-set-cthash
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "$script_dir"

case "${1:-}" in
    --install|--uninstall) action=$1 ;;
    *) echo "Usage: $0 {--install|--uninstall}" >&2; exit 2 ;;
esac

command -v dkms >/dev/null 2>&1 || {
    echo "dkms is required to install $module_name" >&2
    exit 1
}

module_version=$(./version.sh)
source_root=${DKMS_SOURCE_ROOT:-/usr/src}
source_dir="$source_root/$module_name-$module_version"

if [[ "$action" == --uninstall ]]; then
    dkms remove "$module_name/$module_version" --all || true
    rm -rf "$source_dir"
    exit 0
fi

target_kernel=${KVERSION:?KVERSION must identify the target kernel}

while IFS= read -r old_version; do
    [[ -z "$old_version" || "$old_version" == "$module_version" ]] && continue
    dkms remove "$module_name/$old_version" --all
    rm -rf "$source_root/$module_name-$old_version"
done < <(dkms status "$module_name" 2>/dev/null |
	sed -n "s#^$module_name/\\([^,:]*\\).*#\\1#p" | sort -u)

# Remove the target build while the registered source tree still exists.
# Removing it after replacing /usr/src can make DKMS unregister the complete
# module version when this is its last installed kernel.
dkms remove "$module_name/$module_version" -k "$target_kernel" >/dev/null 2>&1 || true

rm -rf "$source_dir"
install -d "$source_dir"
cp -p ./*.[ch] Makefile.in configure dkms.conf install-dkms.sh version.sh "$source_dir/"
chmod 0755 "$source_dir/configure" "$source_dir/install-dkms.sh" "$source_dir/version.sh"
printf '%s\n' "$module_version" > "$source_dir/.module-version"

# grep -q can make dkms receive SIGPIPE when more than one kernel is listed;
# pipefail would then misclassify the registered version as absent.
if ! dkms status "$module_name/$module_version" 2>/dev/null | grep "^$module_name/" >/dev/null; then
    dkms add "$module_name/$module_version"
fi
dkms build "$module_name/$module_version" -k "$target_kernel"
dkms install "$module_name/$module_version" -k "$target_kernel"
