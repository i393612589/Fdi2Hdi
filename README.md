# fdi2hdi — 把多张 PC-98 软盘镜像合并成一张可引导硬盘镜像

[中文](#中文) ｜ [English](#english)

---

## 中文

把若干 PC-98 软盘镜像（`.FDI`）里的文件全部取出、合并去重，装进一张**新建的**
FAT12 分区，配好 IPL / 分区表 / MS-DOS 引导，输出成一张 `.HDI` 硬盘镜像。
挂到模拟器上开机即可运行，从此不再换盘。

> 典型用途：分卷发行的 PC-98 游戏（如 11 张盘的冒险游戏）原本玩到一半会提示
> 「ディスクCを入れてください」。合并成一张硬盘后，引擎每次打开文件都能成功，
> 换盘提示自然消失。

### 为什么这不是「格式转换」

这一点常被误解，所以写在最前面：

| | FDI | HDI |
|---|---|---|
| 本质 | 裸 1.2MB 软盘 | 硬盘 |
| 头部 | 4096 字节（仅几何） | 4096 字节（几何 + 容量） |
| 分区表 | 无 | **有**（IPL 内 `0x0D0`） |
| 引导扇区 | 软盘引导 | 分区引导扇区 |
| 文件系统 | FAT12（软盘参数） | FAT12（硬盘参数） |

所以没有「一键转换」可言——FDI 里根本没有分区表和硬盘几何。
本工具做的是：**新建一张硬盘 → 从软盘把文件拷进去 → 写好引导**。

### 它需要什么

1. **一组 FDI 软盘镜像**
2. **一个可引导的 PC-98 MS-DOS 硬盘镜像（捐赠盘 / donor）**

捐赠盘用来提供三样东西（本仓库不附带 DOS，请自备合法来源）：

- IPL（第 0 扇区，**含分区表**）
- 分区引导扇区模板
- 系统文件：`IO.SYS`、`MSDOS.SYS`、`COMMAND.COM`、`HIMEM.SYS`

任何能正常启动 PC-98 MS-DOS 6.2 的 `.HDI` 都可以当捐赠盘。

### 环境要求

- Python 3.8+（实测 3.12）
- **仅用标准库**，不需要 `pip install` 任何东西

### 仓库结构

```
fdi2hdi/
  fdi2hdi.py    主程序（合并 + 构建 HDI）
  verify.py     校验：把产物 HDI 与源 FDI 逐字节比对
  pcfdi.py      FDI 读取（FAT12 软盘）
  pchdi.py      HDI 读取（解析捐赠盘、读取产物）
  README.md
  LICENSE
```

### 快速开始

```powershell
# 1) 最简：把某目录下所有 FDI 合并成一张 40MB 硬盘
python fdi2hdi.py --out GAME.HDI disks\*.FDI

# 2) 指定捐赠盘、启动程序、卷标
python fdi2hdi.py --out GAME.HDI ^
    --dos-image "D:\dos\MSDOS62.HDI" ^
    --run NEKO.EXE --label "MY GAME" disks\*.FDI

# 3) 先只到 DOS 提示符，方便调试
python fdi2hdi.py --out DEBUG.HDI --no-run disks\*.FDI

# 4) 校验产物（强烈建议）
python verify.py GAME.HDI disks\*.FDI
```

`verify.py` 的输出：

```
image : GAME.HDI  (1204 cyl x 4 head x 17 spt, FAT12, 39.98 MB)
sources: 11 FDI
identical : 788
mismatched: 0
hdi-only  : 6  (system files, CONFIG.SYS, AUTOEXEC.BAT)
RESULT: OK
```

### 挂载到模拟器

1. `HardDisk → IDE #0 → Open` 选择产物 HDI
2. **把 FDD1 / FDD2 全部弹出**（PC-98 引导顺序软驱优先，不弹就还是从软盘启动）
3. `Emulate → Reset`

`np21x64w.ini` 建议：

```ini
IDE_BIOS  = false
AIDEBIOS  = true      # Anex86 IDE BIOS，实测必须开
FDD1FILE  =           # 留空
FDD2FILE  =           # 留空
```

### 关于「空 HDI 文件」——需要多大、什么格式

**结论：不需要手工准备空 HDI。** 工具会自己从零写出完整的硬盘镜像
（头部、IPL、分区表、文件系统全包），你只要给它 FDI 和捐赠盘。

但如果要理解产物规格，或者你想自己用模拟器造一张，参数如下：

#### 产物格式（Anex86 HDI）

| 字段 | 值 |
|---|---|
| 头部大小 | 4096 字节 |
| `0x00` Reserved | 0 |
| `0x04` PDA | 容量（MB），工具自动填 |
| `0x08` HeaderSize | 4096 |
| `0x0C` DataSize | 柱面 × 磁头 × 扇区 × 字节数 |
| `0x10` 每扇区字节 | **512** |
| `0x14` 每道扇区 | **17** |
| `0x18` 磁头数 | **4**（见「三个坑」第 2 条） |
| `0x1C` 柱面数 | 见下表 |

#### 容量怎么选

每柱面 = 4 磁头 × 17 扇区 × 512 字节 = **34,816 字节**。

| 柱面数（`--cyls`） | 镜像大小 | 适用场景 |
|---:|---:|---|
| 270 | 8.96 MiB | 太小，装不下多盘游戏 |
| 431 | 14.31 MiB | 理论下限（约 10.7MB 数据） |
| 602 | 19.99 MiB | 小型项目 |
| **1204** | **39.98 MiB** | **默认值，实测可用** |
| 2408 | 79.96 MiB | 数据量很大时 |

```
可用分区字节 ≈ (柱面数 - 1) × 34,816
```

（第 0 柱面留给 IPL 和分区表，分区从柱面 1 开始。）

#### 如果你确实想自己造一张空 HDI

用 np21x64w 自带的：

```
Emulate → NewDisk → 文件类型选 "Anex86 hard disk image (*.HDI)" → 容量填 40
```

⚠️ 注意：模拟器造出来的 40MB 盘是 **602 柱面 × 8 磁头**，而捐赠盘的分区表
是按 **4 磁头**算的（柱面 1 偏移 34,816）。两者混用会报 `no system files`。
所以：

- **推荐**：不预造，交给 `fdi2hdi.py`（默认 `--heads 4`）
- 若预造了：用 `--geometry-from` 并确保磁头数与捐赠盘一致

此外，空的（未格式化的）HDI **不能**当捐赠盘——它没有 DOS 系统文件，
工具会报 `donor is missing IO.SYS, ...`。

### 参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `fdis` | 必填 | 输入的 FDI，支持通配符，可写多个 |
| `--out` | 必填 | 输出 HDI 路径 |
| `--dos-image` | 内置默认路径 | 捐赠盘（IPL + DOS 系统文件） |
| `--geometry-from` | — | 从某张 HDI 复制柱面/磁头/扇区 |
| `--cyls` | `1204` | 柱面数（最常用的扩容手段） |
| `--heads` | `4` | 磁头数，**必须与捐赠盘分区表一致** |
| `--spt` | `17` | 每道扇区数 |
| `--sec` | `512` | 扇区字节数 |
| `--spc` | 自动 | 簇大小（扇区）。不填时自动挑最小可行值 |
| `--label` | 空 | 卷标（≤11 字符，FAT 限制） |
| `--run` | `NECRO` | 自动执行的程序（启动盘根目录下） |
| `--no-run` | — | 只引导到提示符，不自动执行 |

### 三个必须知道的坑

这三条都是实际调出来的，改动参数前请先读：

#### 1. `spf`（每 FAT 扇区数）绝对不能改

PC-98 MS-DOS 的引导代码假定 `spf = 4`。簇数不够时**不要加 FAT 扇区**，
而要**调大簇大小 `--spc`**。工具就是这么做的：

```text
spf=4 → FAT 有 2730 个表项
spc=4（4KB 簇）→ 最多 10.6 MB
spc=8（8KB 簇）→ 最多 21.3 MB
spc=16（16KB 簇）→ 最多 42.6 MB
```

实测：改成 `spf=5` 会直接黑屏。

#### 2. 磁头数必须与捐赠盘分区表一致

分区表把分区 1 放在「柱面 1」，其字节偏移 = `每道扇区 × 磁头数 × 扇区字节`
= `17 × 4 × 512 = 34,816`。若改成 8 磁头，偏移变 69,632，而 BIOS 仍按分区表
去 34,816 读 → 读到 FAT 数据 → 报 `no system files` 并拒绝引导。

**要扩容请加柱面，不要加磁头。**

#### 3. `AUTOEXEC.BAT` 里不要写死盘符

DOS 给启动分区分配的盘符不保证是 `C:`（实测出现过 `A:\>`）。工具生成的脚本是：

```bat
@ECHO OFF
CLS
CD \
NECRO
```

在「启动盘自己的根目录」执行，与盘符无关。**不要**加 `C:` 那一行。

### 工作原理

1. 逐个 FDI 解析软盘 FAT12，取全部文件（跳过卷标项）
2. 按路径去重；同路径不同内容时保留第一份并告警
3. 跳过软盘自带的 DOS/引导文件（`CONFIG.SYS`、`MEGDOS.SYS`、`IO98.SYS`），
   避免与硬盘上的 MS-DOS 冲突
4. 计算所需簇数与分区大小，自动选择能装下的最小簇大小
5. 分配顺序：`IO.SYS` → `MSDOS.SYS` → `COMMAND.COM` → `HIMEM.SYS` →
   `CONFIG.SYS` → `AUTOEXEC.BAT` → 子目录 → 其余文件
   （MS-DOS 要求前两个系统文件位于根目录最前且簇连续）
6. 写入 IPL（柱面 0，含分区表）、分区引导扇区、双份 FAT、根目录、数据区
7. 输出 HDI 头：`PDA = 容量 MB`

### 产物结构

```
偏移 0        4096 字节 HDI 头
偏移 4096     柱面 0（IPL + 分区表）        34,816 字节
偏移 39,296   分区起点（柱面 1）
              ├─ 引导扇区（MS-DOS 6.20，bps=1024 / spf=4 / media=0xF8）
              ├─ FAT#1（4 扇区 × 1024）
              ├─ FAT#2
              ├─ 根目录（768 项）
              └─ 数据簇（8KB/簇）
```

根目录里的 `CONFIG.SYS`、`AUTOEXEC.BAT` 由工具生成：

```
REM CONFIG.SYS
DOS=HIGH,UMB
DEVICE=HIMEM.SYS
SHELL=COMMAND.COM /P

REM AUTOEXEC.BAT
@ECHO OFF
CLS
CD \
NECRO
```

### 实测

11 张盘的 PC-98 冒险游戏，10.7 MB 数据：

```text
inputs: 11 FDI
merged files: 788
plan: cluster=8192 B, clusters=1810, partition=14641 sectors (14.30 MB)
wrote GAME.HDI (39.98 MB, used 14.16 MB of 14.27 MB)
boot: 1204 cyl x 4 head x 17 spt, partition at +34816, cluster 8192 B
```

校验：

```text
identical : 788
mismatched: 0
RESULT: OK
```

在 np21x64w 上（`HardDisk → IDE #0`，软盘全弹）可成功引导 MS-DOS 6.20
并直接启动游戏。

### 已知限制

- **必须有捐赠盘**：本工具不生成 DOS 系统文件
- **只支持 FAT12**：受 `spf=4` 限制，最大约 21 MB（spc=8）。数据更多时需
  更大 `--spc`，但簇变大后小文件浪费空间也变多
- **根目录上限 768 项**：子目录里的文件不受此限
- **只支持 8.3 文件名**：PC-98 时代本来如此
- **不做 CRC**：写入后请用 `verify.py` 复查

### 许可

MIT，见 `LICENSE`。捐赠盘、DOS 系统文件、游戏数据请自行确保合法使用。

---

## English

Merge the contents of several PC-98 floppy images (`.FDI`) into a single,
**bootable** hard-disk image (`.HDI`).

Typical use case: a multi-disk PC-98 game that keeps asking
*"please insert disk C"*. Once every file lives on one hard disk, the engine's
`open()` always succeeds and the prompt never appears again.

### Why this is not a "format converter"

| | FDI | HDI |
|---|---|---|
| Nature | bare 1.2 MB floppy | hard disk |
| Header | 4096 B (geometry only) | 4096 B (geometry + capacity) |
| Partition table | none | **yes** (inside the IPL at `0x0D0`) |
| Boot sector | floppy boot | partition boot sector |
| Filesystem | FAT12 (floppy params) | FAT12 (hard-disk params) |

An FDI has no partition table and no hard-disk geometry, so a one-click
conversion is impossible. This tool *builds a new hard disk* and copies the
files into it.

### Requirements

1. A set of `.FDI` floppy images
2. **A bootable PC-98 MS-DOS hard-disk image (the "donor")**

The donor supplies the IPL (sector 0, **including the partition table**), the
partition boot-sector template, and `IO.SYS` / `MSDOS.SYS` / `COMMAND.COM` /
`HIMEM.SYS`. Any `.HDI` that boots PC-98 MS-DOS 6.2 will do. This repository
does **not** ship DOS.

### Runtime

- Python 3.8+ (tested on 3.12)
- **Standard library only** — no `pip install`

### Repository layout

```
fdi2hdi/
  fdi2hdi.py    main tool (merge + build HDI)
  verify.py     check: compare the built HDI against the source FDIs
  pcfdi.py      FDI reader (FAT12 floppy)
  pchdi.py      HDI reader (donor parsing, result reading)
  README.md
  LICENSE
```

### Quick start

```powershell
python fdi2hdi.py --out GAME.HDI disks\*.FDI
python fdi2hdi.py --out GAME.HDI --dos-image D:\dos\MSDOS62.HDI --run NEKO.EXE disks\*.FDI
python fdi2hdi.py --out DEBUG.HDI --no-run disks\*.FDI
python verify.py GAME.HDI disks\*.FDI
```

### Mount in the emulator

1. `HardDisk → IDE #0 → Open` → pick the built HDI
2. **Eject FDD1 / FDD2** (PC-98 boots floppies first)
3. `Emulate → Reset`

Recommended `np21x64w.ini`:

```ini
IDE_BIOS = false
AIDEBIOS = true
FDD1FILE =
FDD2FILE =
```

### Do you need an empty HDI? What size / format?

**No.** The tool writes a complete disk image from scratch (header, IPL,
partition table, filesystem). You only need the FDIs and a donor.

For reference, the produced format:

| Field | Value |
|---|---|
| Header size | 4096 bytes |
| `0x00` reserved | 0 |
| `0x04` PDA | capacity in MB (filled automatically) |
| `0x08` header size | 4096 |
| `0x0C` data size | cylinders × heads × sectors × bytes |
| `0x10` bytes/sector | **512** |
| `0x14` sectors/track | **17** |
| `0x18` heads | **4** (see pitfall #2) |
| `0x1C` cylinders | see table |

One cylinder = 4 heads × 17 sectors × 512 B = **34,816 bytes**.

| `--cyls` | Image size | Notes |
|---:|---:|---|
| 270 | 8.96 MiB | too small for multi-disk games |
| 431 | 14.31 MiB | theoretical minimum (≈10.7 MB payload) |
| 602 | 19.99 MiB | small projects |
| **1204** | **39.98 MiB** | **default, verified working** |
| 2408 | 79.96 MiB | large payloads |

```
usable partition bytes ≈ (cylinders - 1) × 34,816
```

If you insist on creating an empty HDI yourself:
`Emulate → NewDisk → "Anex86 hard disk image (*.HDI)" → size 40`.
⚠️ That yields **602 cyl × 8 heads**, while the donor partition table assumes
**4 heads** (partition at byte 34,816); mixing them gives `no system files`.
Prefer letting `fdi2hdi.py` create the image.

An empty (unformatted) HDI **cannot** be used as a donor: it has no DOS system
files and the tool fails with `donor is missing IO.SYS, ...`.

### CLI options

| Option | Default | Description |
|---|---|---|
| `fdis` | required | input FDI files (globs allowed, multiple) |
| `--out` | required | output HDI path |
| `--dos-image` | built-in path | donor image (IPL + DOS system files) |
| `--geometry-from` | — | copy cyl/head/spt from another HDI |
| `--cyls` | `1204` | cylinders — the usual way to add capacity |
| `--heads` | `4` | heads — **must match the donor partition table** |
| `--spt` | `17` | sectors per track |
| `--sec` | `512` | bytes per sector |
| `--spc` | auto | cluster size in sectors (auto: smallest that fits) |
| `--label` | empty | volume label (≤11 chars) |
| `--run` | `NECRO` | program to launch from the boot drive root |
| `--no-run` | — | boot to a prompt only |

### Three pitfalls (learned the hard way)

#### 1. Never change `spf` (sectors per FAT)

The PC-98 MS-DOS boot code assumes `spf = 4`. When you need more clusters,
**increase the cluster size (`--spc`) instead of the FAT size**:

```text
spf=4 → 2730 FAT entries
spc=4  (4 KB clusters) → up to ~10.6 MB
spc=8  (8 KB clusters) → up to ~21.3 MB
spc=16 (16 KB clusters) → up to ~42.6 MB
```

Setting `spf=5` yields a black screen.

#### 2. Head count must match the donor partition table

The partition table places partition 1 at "cylinder 1", i.e. byte offset
`17 × heads × 512 = 34,816` for 4 heads. With 8 heads the offset becomes
69,632, while the BIOS still reads 34,816 per the partition table → it loads
FAT data as a boot sector → `no system files`.

**Add cylinders to grow, never heads.**

#### 3. Never hardcode a drive letter in `AUTOEXEC.BAT`

The letter DOS assigns to the boot partition is not guaranteed (observed
`A:\>`). The generated script is:

```bat
@ECHO OFF
CLS
CD \
NECRO
```

It runs from the root of whatever drive it booted from.

### How it works

1. Parse each FDI's floppy FAT12 and read every file (volume-label entries
   skipped)
2. De-duplicate by upper-cased path; on conflicting content keep the first copy
   and warn
3. Skip DOS/boot files shipped on the floppies (`CONFIG.SYS`, `MEGDOS.SYS`,
   `IO98.SYS`)
4. Compute required clusters and partition size; automatically pick the
   smallest cluster size that fits
5. Allocation order: `IO.SYS` → `MSDOS.SYS` → `COMMAND.COM` → `HIMEM.SYS` →
   `CONFIG.SYS` → `AUTOEXEC.BAT` → subdirectories → remaining files
6. Write IPL (cylinder 0 with the partition table), partition boot sector,
   two FATs, root directory, data area
7. Emit the HDI header with `PDA = capacity in MB`

### Verified on

An 11-disk PC-98 adventure game, 10.7 MB of data:

```text
inputs: 11 FDI
merged files: 788
plan: cluster=8192 B, clusters=1810, partition=14641 sectors (14.30 MB)
wrote GAME.HDI (39.98 MB, used 14.16 MB of 14.27 MB)
boot: 1204 cyl x 4 head x 17 spt, partition at +34816, cluster 8192 B

identical : 788
mismatched: 0
RESULT: OK
```

Boots MS-DOS 6.20 and starts the game in np21x64w.

### Limitations

- **A donor is mandatory** — this tool does not create DOS system files
- **FAT12 only** — bounded by `spf=4`; ~21 MB at `spc=8`
- **768 root entries** (files in subdirectories are not limited by this)
- **8.3 names only**
- **No CRC / image verification** — use `verify.py` afterwards

### License

MIT, see `LICENSE`. You are responsible for using the donor image, DOS system
files and game data legally.
