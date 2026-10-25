#!/usr/bin/env python3
"""verify.py — compare a built HDI against the FDI set it was built from.

Reads every file out of the HDI with an independent reader (pchdi.Hdi) and
compares it byte-for-byte with the same path on the source floppies.

Exit status: 0 = all good, 1 = differences found.

Usage:
  python verify.py GAME.HDI disks/*.FDI
  python verify.py GAME.HDI disks/*.FDI --ignore CONFIG.SYS AUTOEXEC.BAT
"""
import sys
import os
import glob
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pcfdi import Floppy
from pchdi import Hdi

SKIP_NAMES = {'CONFIG.SYS', 'MEGDOS.SYS', 'IO98.SYS'}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('hdi')
    ap.add_argument('fdis', nargs='+')
    ap.add_argument('--ignore', nargs='*', default=[],
                    help='extra file names to ignore (case-insensitive)')
    args = ap.parse_args()

    ignore = SKIP_NAMES | {n.upper() for n in args.ignore}

    paths = []
    for pat in args.fdis:
        got = sorted(glob.glob(pat))
        paths.extend(got if got else [pat])
    paths = [p for p in paths if os.path.isfile(p)]

    src = {}
    for p in paths:
        disk = Floppy(path=p)
        for f in disk.walk():
            name = f['name'] + ('.' + f['ext'] if f['ext'] else '')
            if name.upper() in ignore:
                continue
            key = f['path'].upper()
            if key in src:
                continue
            src[key] = (p, disk.read_file(f))

    h = Hdi(path=args.hdi)
    ok = bad = missing_extra = 0
    problems = []
    seen = set()
    for f in h.walk():
        key = f['path'].upper()
        seen.add(key)
        data = h.read_chain(f['cluster'], f['size'])
        if key not in src:
            missing_extra += 1
            continue
        if src[key][1] == data:
            ok += 1
        else:
            bad += 1
            problems.append('MISMATCH %s (hdi %d B vs fdi %d B)'
                            % (f['path'], len(data), len(src[key][1])))
    for key in src:
        if key not in seen:
            bad += 1
            problems.append('MISSING  %s' % key)

    print('image : %s  (%d cyl x %d head x %d spt, FAT%d, %.2f MB)'
          % (args.hdi, h.cylinders, h.heads, h.spt, h.bits,
             len(h.data) / 1048576.0))
    print('sources: %d FDI' % len(paths))
    print('identical : %d' % ok)
    print('mismatched: %d' % bad)
    print('hdi-only  : %d  (system files, CONFIG.SYS, AUTOEXEC.BAT)' % missing_extra)
    for msg in problems[:20]:
        print('  ' + msg)
    if len(problems) > 20:
        print('  ... %d more' % (len(problems) - 20))
    print('RESULT:', 'OK' if bad == 0 else 'PROBLEMS FOUND')
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
