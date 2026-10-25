"""PC-98 HDI (hard disk image) reader.

Container layout (same family as FDI, bigger geometry):

    0x00 uint32  reserved (0)
    0x04 uint32  PDA — for HDI this is usually the capacity in MB
    0x08 uint32  header size (4096)
    0x0C uint32  data size = file size - header size
    0x10 uint32  bytes per sector (512 for hard disks)
    0x14 uint32  sectors per track
    0x18 uint32  heads
    0x1C uint32  cylinders

Partition 1 starts at cylinder 1, i.e. byte offset
`sectors_per_track * heads * bytes_per_sector` inside the data area.
The partition itself holds an ordinary FAT12/FAT16 volume whose BPB may use a
different logical sector size (1024 is typical on PC-98).

Reading only — fdi2hdi.py writes the images.
"""
import struct

HEADER_SIZE = 4096


class Hdi:
    def __init__(self, path=None, raw=None):
        if raw is None:
            if path is None:
                raise ValueError('need raw bytes or a path')
            with open(path, 'rb') as fh:
                raw = fh.read()
        (self.reserved, self.pda, self.hdr_size, self.data_size,
         self.sector_size, self.spt, self.heads,
         self.cylinders) = struct.unpack_from('<8I', raw, 0)
        self.data = raw[self.hdr_size:]
        self.part = self.spt * self.heads * self.sector_size

        bs = self.data[self.part:self.part + self.sector_size]
        self.bps = struct.unpack_from('<H', bs, 11)[0]
        self.spc = bs[13]
        self.resv = struct.unpack_from('<H', bs, 14)[0]
        self.nfat = bs[16]
        self.rootent = struct.unpack_from('<H', bs, 17)[0]
        self.tsp = struct.unpack_from('<H', bs, 19)[0]
        self.media = bs[21]
        self.spf = struct.unpack_from('<H', bs, 22)[0]

        self.cs = self.spc * self.bps
        self.fat_off = self.part + self.resv * self.bps
        self.root_off = self.part + (self.resv + self.nfat * self.spf) * self.bps
        self.data_off = self.root_off + self.rootent * 32
        self.bits = 16 if self.clusters() >= 0xFF0 else 12

    def clusters(self):
        used = (self.resv + self.nfat * self.spf) * self.bps + self.rootent * 32
        return (self.tsp * self.bps - used) // self.cs

    # -- FAT ---------------------------------------------------------
    def fat_get(self, i):
        if self.bits == 12:
            off = self.fat_off + i + i // 2
            v = self.data[off] | (self.data[off + 1] << 8)
            return (v >> 4) if (i & 1) else (v & 0xFFF)
        return struct.unpack_from('<H', self.data, self.fat_off + i * 2)[0]

    def chain(self, c):
        out = []
        seen = set()
        limit = 0xFF8 if self.bits == 12 else 0xFFF8
        while 2 <= c < limit and c not in seen:
            seen.add(c)
            out.append(c)
            c = self.fat_get(c)
        return out

    # -- directories --------------------------------------------------
    def _blocks(self, cluster, size=0, is_root=False):
        if is_root:
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
        out = []
        for blk, count in self._blocks(cluster, is_root=(cluster == 0)):
            for i in range(count):
                off = blk + i * 32
                ent = self.data[off:off + 32]
                if len(ent) < 32 or ent[0] == 0:
                    continue
                if ent[0] == 0xE5:
                    continue
                attr = ent[11]
                if attr & 0x08:
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

    def read_chain(self, cluster, size=None):
        buf = bytearray()
        for c in self.chain(cluster):
            base = self.data_off + (c - 2) * self.cs
            buf += self.data[base:base + self.cs]
        return bytes(buf[:size]) if size is not None else bytes(buf)

    def read_path(self, path):
        want = path.upper()
        for f in self.walk():
            if f['path'].upper() == want:
                return self.read_chain(f['cluster'], f['size'])
        raise KeyError(path)

    def __repr__(self):
        return ('<Hdi %d cyl x %d head x %d spt x %dB, FAT%d, %.2f MB>'
                % (self.cylinders, self.heads, self.spt, self.sector_size,
                   self.bits, len(self.data) / 1048576.0))
