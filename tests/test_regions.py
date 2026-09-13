#!/usr/bin/env python3
"""Compile the production region macros and verify bucket/lock ownership.

Run with: python3 tests/test_regions.py
No kernel headers or loaded module are needed.
"""

from pathlib import Path
import os
import shlex
import subprocess
import tempfile


SOURCE = Path(__file__).resolve().parents[1] / "src/ip_set_hash_gen.h"

HARNESS = r"""
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#define jhash_size(n) (1U << (n))

REGION_MACROS

static void check_bucket(uint32_t key, unsigned int bits)
{
    uint32_t region = ahash_region(key, bits);
    assert(region < ahash_numof_locks(bits));
    assert(ahash_bucket_start(region, bits) <= key);
    assert(key < ahash_bucket_end(region, bits));
}

int main(void)
{
    unsigned int bits;
    /* Creation permits at least 64 buckets; htable_size caps bits at 31. */
    for (bits = 6; bits <= 31; bits++) {
        uint32_t size = jhash_size(bits);
        uint32_t regions = ahash_numof_locks(bits);
        uint32_t expected = bits <= 10 ? 1U : size / 1024U;
        uint32_t r, end = 0;
        assert(regions == expected);
        for (r = 0; r < regions; r++) {
            uint32_t start = ahash_bucket_start(r, bits);
            uint32_t last = ahash_bucket_end(r, bits);
            /* No gaps, overlap, empty regions or out-of-bounds GC scans. */
            assert(start == end);
            assert(start < last && last <= size);
            assert(last - start == size / regions);
            assert(ahash_region(start, bits) == r);
            assert(ahash_region(last - 1, bits) == r);
            check_bucket(start + (last - start) / 2, bits);
            if (bits < 31) {
                /* Both possible destinations when the hash mask grows. */
                check_bucket(start, bits + 1);
                check_bucket(start + size, bits + 1);
                check_bucket(last - 1, bits + 1);
                check_bucket(last - 1 + size, bits + 1);
            }
            end = last;
        }
        assert(end == size);
        /* Exhaust every bucket through the captured server's table size. */
        if (bits <= 21) {
            uint32_t key;
            for (key = 0; key < size; key++)
                check_bucket(key, bits);
        }
    }
    puts("PASS: disjoint regions, ownership and resize boundaries (bits 6..31)");
    return 0;
}
"""


def main():
    source = SOURCE.read_text()
    start = source.index("#define HTABLE_REGION_BITS")
    end = source.index("struct htable_gc", start)
    harness = HARNESS.replace("REGION_MACROS", source[start:end])
    with tempfile.TemporaryDirectory(prefix="ipset-regions-") as directory:
        path = Path(directory)
        (path / "regions.c").write_text(harness)
        subprocess.run(
            shlex.split(os.environ.get("CC", "cc"))
            + ["-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
               "-fsanitize=undefined", "-fno-sanitize-recover=all",
               str(path / "regions.c"), "-o", str(path / "regions")],
            check=True,
        )
        subprocess.run([str(path / "regions")], check=True)


if __name__ == "__main__":
    main()
