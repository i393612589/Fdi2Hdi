"""PC-98 FDI (Anex86 floppy image) reader.

FDI container layout (4096-byte header, then raw C/H/S data):

    0x00 uint32  reserved (0)
    0x04 uint32  PDA / media id  (0x90 = 1.2 MB, 0x30 = 1.44 MB, 0x10 = 640K/720K)
    0x08 uint32  header size (4096)
    0x0C uint32  data size = file size - header size
    0x10 uint32  bytes per sector
    0x14 uint32  sectors per track
    0x18 uint32  heads
    0x1C uint32  cylinders

A 1.2 MB PC-98 floppy is 1024 B x 8 sectors x 2 heads x 77 cylinders.

The filesystem is plain FAT12 with a PC-98 BPB.  Only reading is implemented
here; writing is done by fdi2hdi.py when it assembles the hard disk.
"""
import struct

HEADER_SIZE = 4096


class Floppy:
    """Read-only view of a PC-98 FDI image."""

    def __init__(self, raw=None, path=None):
        if raw is None:
            if path is None:
                raise ValueError('need raw bytes or a path')
            with open(path, 'rb') as fh:
                raw = fh.read()
        if len(raw) < HEADER_SIZE:
            raise ValueError('file too small to be an FDI image')
        self.raw = raw
        self.header = raw[:HEADER_SIZE]
        (self.reserved, self.pda, self.hdr_size, self.data_size,
         self.sector_size, self.spt, self.heads,
         self.cylinders) = struct.unpack_from('<8I', self.header, 0)
        self.dsk = raw[self.hdr_size:]

        d = self.dsk
        self.bps = struct.unpack_from('<H', d, 11)[0]
        self.spc = d[13]
        self.resv = struct.unpack_from('<H', d, 14)[0]
        self.nfats = d[16]
        self.rootent = struct.unpack_from('<H', d, 17)[0]
        self.totsec = struct.unpack_from('<H', d, 19)[0]
        self.fatsec = struct.unpack_from('<H', d, 22)[0]

        self.fat_off = self.resv * self.bps
        self.root_off = (self.resv + self.nfats * self.fatsec) * self.bps
        self.data_off = self.root_off + self.rootent * 32
        self.cs = self.spc * self.bps

    # -- FAT ---------------------------------------------------------
    def fat_get(self, i):
        off = self.fat_off + i + i // 2
        v = self.dsk[off] | (self.dsk[off + 1] << 8)
        return (v >> 4) if (i & 1) else (v & 0xFFF)

    def chain(self, c):
        out = []
        seen = set()
        while 2 <= c < 0xFF0 and c not in seen:
            seen.add(c)
            out.append(c)
            c = self.fat_get(c)
        return out

    # -- directories --------------------------------------------------
    def _dir_blocks(self, cluster):
        if cluster == 0:
            per = self.bps // 32
            return [(self.root_off + i * self.bps, per)
                    for i in range(self.rootent // per)]
        blocks = []
        for c in self.chain(cluster):
            base = self.data_off + (c - 2) * self.cs
            for k in range(self.cs // self.bps):
                blocks.append((base + k * self.bps, self.bps // 32))
        return blocks

    def walk(self, cluster=0, prefix=''):
        """Return every file entry below `cluster` (0 = root)."""
        out = []
        for blk, count in self._dir_blocks(cluster):
            for i in range(count):
                off = blk + i * 32
                ent = self.dsk[off:off + 32]
                if len(ent) < 32 or ent[0] == 0:
                    continue
                if ent[0] == 0xE5:            # deleted
                    continue
                attr = ent[11]
                if attr & 0x08:               # volume label
                    continue
                name = ent[0:8].decode('cp932', 'replace').rstrip(' ')
                ext = ent[8:11].decode('cp932', 'replace').rstrip(' ')
                if name in ('.', '..'):
                    continue
                cl = struct.unpack_from('<H', ent, 26)[0]
                size = struct.unpack_from('<I', ent, 28)[0]
                path = prefix + '/' + name + ('.' + ext if ext else '')
                if attr & 0x10:
                    out += self.walk(cl, path)
                else:
                    out.append(dict(path=path, name=name, ext=ext, attr=attr,
                                    cluster=cl, size=size))
        return out

    def read_file(self, f):
        out = bytearray()
        for c in self.chain(f['cluster']):
            base = self.data_off + (c - 2) * self.cs
            out += self.dsk[base:base + self.cs]
        return bytes(out[:f['size']])

    def read_path(self, path):
        want = path.upper()
        for f in self.walk():
            if f['path'].upper() == want:
                return self.read_file(f)
        raise KeyError(path)

    def __repr__(self):
        return ('<Floppy %d cyl x %d head x %d spt x %dB, FAT12, %d bytes>'
                % (self.cylinders, self.heads, self.spt, self.sector_size,
                   len(self.dsk)))
