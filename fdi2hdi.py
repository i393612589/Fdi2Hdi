#!/usr/bin/env python3
"""fdi2hdi — merge several PC-98 floppy images (FDI) into ONE bootable
hard-disk image (HDI).

Why this is not a simple "container conversion"
-----------------------------------------------
An FDI is a bare 1.2 MB floppy: no partition table, no hard-disk geometry.
An HDI is a hard disk: 4096-byte header + IPL + partition table + a FAT
filesystem.  So this tool does not convert a container; it *builds* a fresh
hard disk and copies the files out of the floppies into it.

What it needs from a donor
--------------------------
A bootable PC-98 hard-disk image is used as the donor for:

  * the IPL (sector 0, including the partition table)
  * the partition boot-sector template
  * the MS-DOS system files: IO.SYS, MSDOS.SYS, COMMAND.COM, HIMEM.SYS

By default the donor is a known-good MS-DOS 6.20 HDD (see --dos-image).

Known constraints (learned the hard way)
----------------------------------------
  * `spf` (sectors per FAT) must NOT be changed: PC-98 MS-DOS boot code
    assumes the template's value (4).  If more clusters are needed, raise
    `--spc` (cluster size) instead.
  * with spf=4 the FAT holds 2730 entries; the tool picks `--spc`
    automatically when you do not specify one.
  * the partition table in the donor IPL places partition 1 at cylinder 1
    computed with the donor's head count, so keep the same `--heads`
    (default 4) or the BIOS will read the wrong sector and complain
    "no system files".
  * the drive letter DOS assigns to the boot partition is not guaranteed;
    the generated AUTOEXEC.BAT therefore never hardcodes one.

Examples
--------
  python fdi2hdi.py --out GAME.HDI disks/*.FDI
  python fdi2hdi.py --out GAME.HDI --geometry-from newdisk.hdi *.FDI
  python fdi2hdi.py --out GAME.HDI --run NEKO.EXE --label "MY GAME" *.FDI
"""
import sys
import os
import glob
import struct
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pcfdi import Floppy
from pchdi import Hdi

DEFAULT_DOS_IMAGE = r'E:\np2\Rookies(J)[汉化版wuwei].hdi'
DOS_FILES = ['IO.SYS', 'MSDOS.SYS', 'COMMAND.COM', 'HIMEM.SYS']

# DOS/boot files carried on the floppies themselves; they would clash with the
# hard disk's own MS-DOS, so they are skipped.
SKIP_NAMES = {'CONFIG.SYS', 'MEGDOS.SYS', 'IO98.SYS'}

BPS = 1024          # logical sector size inside the partition (PC-98 norm)
RESV = 1
NFAT = 2
ROOTENT = 768
SPF = 4             # must not change, see module docstring
MAX_FAT_ENTRIES = SPF * BPS * 2 // 3      # FAT12: 4096 * 2 / 3 = 2730


class Fat12:
    """Assemble a FAT12 volume in memory."""

    def __init__(self, part_sectors, spc, bps=BPS, spf=SPF, rootent=ROOTENT,
                 resv=RESV, nfat=NFAT):
        self.bps, self.spf, self.rootent = bps, spf, rootent
        self.spc = spc
        self.cs = spc * bps
        self.tsp = part_sectors
        data_bytes = (self.tsp * bps - (resv + nfat * spf) * bps
                      - rootent * 32)
        self.nclusters = data_bytes // self.cs
        self.fat = [0] * (self.nclusters + 2)
        self.fat[0] = 0xF00 | 0xF8
        self.fat[1] = 0xFFF
        self.next = 2
        self.data = bytearray(self.cs * self.nclusters)
        self.root = []

    def alloc(self, count=1):
        first = self.next
        for i in range(count):
            c = self.next
            if c > self.nclusters + 1:
                raise SystemExit('out of clusters (need %d, have %d)'
                                 % (c, self.nclusters + 1))
            self.next += 1
            self.fat[c] = c + 1 if i < count - 1 else 0xFFF
        return first

    def write(self, payload):
        need = max(1, (len(payload) + self.cs - 1) // self.cs)
        first = self.alloc(need)
        for i in range(need):
            chunk = payload[i * self.cs:(i + 1) * self.cs]
            off = (first - 2) * self.cs + i * self.cs
            self.data[off:off + len(chunk)] = chunk
        return first

    @staticmethod
    def dirent(name, ext, attr, cluster, size):
        nm = name.upper().encode('cp932')[:8].ljust(8, b' ')
        ex = ext.upper().encode('cp932')[:3].ljust(3, b' ')
        e = bytearray(32)
        e[0:8] = nm
        e[8:11] = ex
        e[11] = attr
        struct.pack_into('<H', e, 26, cluster)
        struct.pack_into('<I', e, 28, size)
        return bytes(e)


def read_fdi_set(paths):
    """Merge every file from the given FDIs.  Returns (store, conflicts)."""
    store = {}
    conflicts = []
    for p in paths:
        disk = Floppy(path=p)
        for f in disk.walk():
            name = f['name'] + ('.' + f['ext'] if f['ext'] else '')
            if name.upper() in SKIP_NAMES:
                continue
            key = f['path'].upper()
            payload = disk.read_file(f)
            if key in store:
                if store[key][1] != payload:
                    conflicts.append(key)
                continue
            store[key] = (f['path'], payload)
    return store, conflicts


def read_donor(path):
    h = Hdi(path=path)
    files = {}
    for f in h.walk():
        base = f['path'].strip('/').upper()
        if base in DOS_FILES:
            files[base] = h.read_chain(f['cluster'], f['size'])
    missing = [d for d in DOS_FILES if d not in files]
    if missing:
        raise SystemExit('donor %s is missing %s\n'
                         'It must be a bootable PC-98 MS-DOS hard disk image.'
                         % (path, ', '.join(missing)))
    return h, files


def geometry_from(path):
    raw = open(path, 'rb').read(32)
    _, _, _, _, sec, spt, heads, cyls = struct.unpack_from('<8I', raw, 0)
    return sec, spt, heads, cyls


def plan(store, dosfiles, spc_hint, rootent=ROOTENT):
    """Pick the smallest cluster size that fits the FAT12 with spf=4."""
    sizes = dict((k, len(v[1])) for k, v in store.items())
    sizes.update({k: len(v) for k, v in dosfiles.items()})
    sizes['/CONFIG.SYS'] = 64
    sizes['/AUTOEXEC.BAT'] = 64
    dirs = {}
    for key in store:
        parts = key.strip('/').split('/')
        if len(parts) > 1:
            dirs[parts[0]] = dirs.get(parts[0], 0) + 1

    for spc in ([spc_hint] if spc_hint else [4, 8, 16, 32]):
        cs = spc * BPS
        need = sum((n + cs - 1) // cs for n in sizes.values())
        need += sum((n + 2) * 32 // cs + 1 for n in dirs.values())
        if need + 8 > MAX_FAT_ENTRIES:
            continue
        tsp = (((need + 16) * cs + (RESV + NFAT * SPF) * BPS
                + rootent * 32 + BPS - 1) // BPS)
        return spc, need, tsp
    raise SystemExit('payload does not fit FAT12 with spf=4 even at spc=32')


def main():
    ap = argparse.ArgumentParser(
        description='Merge PC-98 FDI floppy images into one bootable HDI.')
    ap.add_argument('fdis', nargs='+', help='input .FDI files (globs allowed)')
    ap.add_argument('--out', required=True, help='output .HDI')
    ap.add_argument('--dos-image', default=DEFAULT_DOS_IMAGE,
                    help='donor bootable HDD: IPL + DOS system files')
    ap.add_argument('--geometry-from', metavar='HDI',
                    help='copy cyl/head/spt from this image')
    ap.add_argument('--cyls', type=int, default=1204,
                    help='cylinders (default 1204 = 39.98 MB)')
    ap.add_argument('--heads', type=int, default=4,
                    help='heads; must match the donor partition table')
    ap.add_argument('--spt', type=int, default=17)
    ap.add_argument('--sec', type=int, default=512)
    ap.add_argument('--spc', type=int, default=0,
                    help='cluster size in sectors (default: auto)')
    ap.add_argument('--label', default='', help='volume label (<= 11 chars)')
    ap.add_argument('--run', default='NECRO',
                    help='program launched from the boot drive root')
    ap.add_argument('--no-run', action='store_true',
                    help='boot to a prompt only')
    args = ap.parse_args()

    paths = []
    for pat in args.fdis:
        got = sorted(glob.glob(pat))
        paths.extend(got if got else [pat])
    paths = [p for p in paths if os.path.isfile(p)]
    if not paths:
        raise SystemExit('no input FDI found')

    sec, spt, heads, cyls = args.sec, args.spt, args.heads, args.cyls
    if args.geometry_from:
        sec, spt, heads, cyls = geometry_from(args.geometry_from)
        print('geometry from %s: %d cyl x %d head x %d spt x %dB'
              % (args.geometry_from, cyls, heads, spt, sec))

    print('inputs: %d FDI' % len(paths))
    store, conflicts = read_fdi_set(paths)
    print('merged files: %d' % len(store))
    if conflicts:
        print('WARNING: %d path(s) appear on several floppies with different '
              'content; the first copy wins:' % len(conflicts))
        for c in conflicts[:10]:
            print('   ', c)

    donor, dosfiles = read_donor(args.dos_image)
    print('donor: %s' % args.dos_image)

    spc, need, tsp = plan(store, dosfiles, args.spc)
    print('plan: cluster=%d B, clusters=%d, partition=%d sectors (%.2f MB)'
          % (spc * BPS, need, tsp, tsp * BPS / 1048576.0))

    total = sec * spt * heads * cyls
    part = spt * heads * sec
    if tsp * BPS + part > total:
        raise SystemExit('partition does not fit: need a disk of %.2f MB'
                         % ((tsp * BPS + part) / 1048576.0))

    w = Fat12(tsp, spc)

    bs = bytearray(donor.data[donor.part:donor.part + BPS])
    struct.pack_into('<H', bs, 11, BPS)
    bs[13] = spc
    struct.pack_into('<H', bs, 14, RESV)
    bs[16] = NFAT
    struct.pack_into('<H', bs, 17, ROOTENT)
    struct.pack_into('<H', bs, 19, tsp & 0xFFFF)
    bs[21] = 0xF8
    struct.pack_into('<H', bs, 22, SPF)

    bat = ['@ECHO OFF', 'CLS', 'CD \\']
    if not args.no_run:
        bat.append(args.run)
    autoexec = ('\r\n'.join(bat) + '\r\n').encode('ascii')
    config = b'DOS=HIGH,UMB\r\nDEVICE=HIMEM.SYS\r\nSHELL=COMMAND.COM /P\r\n'

    if args.label:
        ent = bytearray(32)
        ent[0:11] = args.label.upper().encode('cp932')[:11].ljust(11, b' ')
        ent[11] = 0x08
        w.root.append(bytes(ent))

    # MS-DOS wants the two system files first in the root and contiguous
    for nm in ('IO.SYS', 'MSDOS.SYS'):
        payload = dosfiles[nm]
        c = w.write(payload)
        stem, _, ext = nm.partition('.')
        w.root.append(w.dirent(stem, ext, 0x27, c, len(payload)))
    for nm, payload in (('COMMAND.COM', dosfiles['COMMAND.COM']),
                        ('HIMEM.SYS', dosfiles['HIMEM.SYS']),
                        ('CONFIG.SYS', config),
                        ('AUTOEXEC.BAT', autoexec)):
        c = w.write(payload)
        stem, _, ext = nm.partition('.')
        w.root.append(w.dirent(stem, ext, 0x20, c, len(payload)))

    files_root = []
    subdirs = {}
    for key, (path, payload) in store.items():
        parts = path.strip('/').split('/')
        if len(parts) == 1:
            files_root.append((parts[0], payload))
        else:
            subdirs.setdefault(parts[0], []).append(('/'.join(parts[1:]), payload))

    for d in sorted(subdirs):
        w.root.append(w.dirent(d, '', 0x10, 0, 0))
    for name, payload in sorted(files_root):
        c = w.write(payload)
        stem, _, ext = name.partition('.')
        w.root.append(w.dirent(stem, ext, 0x20, c, len(payload)))

    sub_entries = {}
    for d, items in sorted(subdirs.items()):
        ents = []
        for name, payload in sorted(items):
            c = w.write(payload)
            stem, _, ext = name.partition('.')
            ents.append(w.dirent(stem, ext, 0x20, c, len(payload)))
        sub_entries[d] = ents

    idx = {}
    for k, e in enumerate(w.root):
        if e[11] & 0x10:
            idx[e[0:8].decode('cp932', 'replace').rstrip()] = k
    for d, ents in sub_entries.items():
        payload = b''.join(ents)
        n = max(1, (len(payload) + 64 + w.cs - 1) // w.cs)
        first = w.alloc(n)
        body = (w.dirent('.', '', 0x10, first, 0)
                + w.dirent('..', '', 0x10, 0, 0) + payload)
        for i in range(n):
            chunk = body[i * w.cs:(i + 1) * w.cs]
            off = (first - 2) * w.cs + i * w.cs
            w.data[off:off + len(chunk)] = chunk
        k = idx[d.upper()]
        e = bytearray(w.root[k])
        struct.pack_into('<H', e, 26, first)
        w.root[k] = bytes(e)

    if len(w.root) > ROOTENT:
        raise SystemExit('root directory overflow: %d > %d'
                         % (len(w.root), ROOTENT))

    fat = bytearray(SPF * BPS)
    for i, v in enumerate(w.fat):
        off = i + i // 2
        if off + 1 >= len(fat):
            break
        if i & 1:
            fat[off] = (fat[off] & 0x0F) | ((v << 4) & 0xF0)
            fat[off + 1] = (v >> 4) & 0xFF
        else:
            fat[off] = v & 0xFF
            fat[off + 1] = (fat[off + 1] & 0xF0) | ((v >> 8) & 0x0F)

    img = bytearray(total)
    img[0:part] = donor.data[0:part]          # IPL (with partition table)
    off = part
    img[off:off + BPS] = bs
    off += RESV * BPS
    for _ in range(NFAT):
        img[off:off + len(fat)] = fat
        off += SPF * BPS
    rootblob = b''.join(w.root).ljust(ROOTENT * 32, b'\x00')
    img[off:off + len(rootblob)] = rootblob
    off += ROOTENT * 32
    img[off:off + len(w.data)] = w.data

    hdr = struct.pack('<8I', 0, int(round(total / 1048576.0)), 4096, total,
                      sec, spt, heads, cyls) + bytes(4096 - 32)
    with open(args.out, 'wb') as fh:
        fh.write(hdr)
        fh.write(img)

    print('wrote %s (%.2f MB, used %.2f MB of %.2f MB)'
          % (args.out, (4096 + total) / 1048576.0,
             w.next * w.cs / 1048576.0, w.nclusters * w.cs / 1048576.0))
    print('boot: %d cyl x %d head x %d spt, partition at +%d, '
          'cluster %d B, %d clusters'
          % (cyls, heads, spt, part, w.cs, w.nclusters))
    return 0


if __name__ == '__main__':
    sys.exit(main())
