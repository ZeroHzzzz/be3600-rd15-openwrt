# RE 首轮结果（2026-11-14 19:10）

工具链已就绪，APPSBL（工作中的 U-Boot NAND 驱动）已完成 首轮反编译，找到
一个可验证的差异：**quad(x4) 读模式**。

## 1. 工具链

| 组件 | 版本/位置 | 备注 |
| --- | --- | --- |
| dsh-rea-agents | 1.0.8（profile 插件） | 页面/API 管理 pin 版本 |
| rea-agents | **6.7.0**（pin） | 6.9.0 要求 Node ≥22.23.4，本机 22.22.1 |
| Ghidra | 12.1.4 `~/.local/tools/ghidra_12.1.4_PUBLIC` | REA 6.7 只接受 12.1.x |
| JDK | Temurin 25.0.5 `~/.local/tools/jdk-25.0.5+8` | REA/Ghidra 12.1 都要 25+ |

`rea doctor` 的 ghidra provider 已 healthy。DSH 会话里的 `mcp__rea__*`
尚未注册：MCP 子进程在插件安装前启动失败，需要重启 harness 才会重连；
目前直接用 `node scripts/rea.mjs` CLI。

## 2. 逆向对象与产出

- 目标：`mtd14_0_APPSBL.bin`（U-Boot 2016.01，ARM32 ELF，478 KB，base 0x4a400000）
- Ghidra 导入成功：5 段、1460 函数、2831 字符串
- 已反编译（引用 `qpic_nand*` 字符串的函数）：
  - `qpic_nand_read_id_serial` @0x4a424dfc
  - `qpic_nand_read_page_scope_multi_page` @0x4a423a10
  - `qpic_nand_read_oob` @0x4a4236d8
  - `qpic_nand_write` @0x4a424acc

## 3. 关键差异：读命令的传输模式

反编译出的读页函数里，FLASH_CMD 由分支给出两个常量：

```
0x38000000 = SPI_TRANSFER_MODE_x1 | SPI_WP | SPI_HOLD
0x78000000 = SPI_TRANSFER_MODE_x4 | SPI_WP | SPI_HOLD
```

分支条件是 `*(char *)(nandc + 0x60)`——即 flash 的 quad/wide 标志。
**工作正常的 U-Boot 在 x4 模式下读页**。

而 Linux `spi-qpic-snand.c`：

- `qcom_spi_cmd_mapping()` 把 `SPI_TRANSFER_MODE_x1` 写死；
- 芯片条目 `W25N01KW` 的 flags = `0`，没有 `SPINAND_HAS_QE_BIT`，
  所以 SPI-NAND 核心永远不会开 quad，页操作全部是 1x1；
- 虽然 `qcom_spi_is_page_op()` 支持 4x4 页操作，但核心不会发出这种 op。

原始 dmesg 佐证：原厂 5.4 驱动打印
`qcom-nandc 79b0000.nand: x4 mode enabled already remotely`
——SBL 已经把闪存/控制器留在 x4 模式。

## 4. 可验证的修复假设

在 `winbond.c` 的 `W25N01KW` 条目上：

1. flags 加 `SPINAND_HAS_QE_BIT`；
2. 确认 read/write cache variants 里有 4S 版本（已有：
   `1S_4S_4S`、`1S_1S_4S`、`PROG_LOAD_1S_1S_4S`）。

这样核心会置 QE 并使页读写走 4x4，与 U-Boot 一致。

验证标准（RAM 启动，只读）：

```
nanddump -l 0x800 /dev/mtd19     # 期望 ECC failed: 0
ubiattach -m 19 -d 0             # 期望成功
```

## 5. 尚未确定的部分（不要当成结论）

- LK 参考源码 `qpic_nand.c` 是**并行 ONFI** 路径（addr cycles=5、
  recovery=7、bsy gap=2），APPSBL 这里是 **SPI NAND** 路径
  （Linux 用 addr cycles=3、bsy gap=20），两套常数不能直接互换；
  寄存器差异需要从设备上实测确认。
- x1 与 x4 的差异是否就是 ECC 失败的根因，尚未验证：当前证据只能说明
  工作路径是 x4、故障路径是 x1。
- 下一步更硬的证据：从原厂系统或 U-Boot 侧只读 dump QPIC 寄存器
  （`NAND_DEV0_CFG0/CFG1`、`NAND_EBI2_ECC_BUF_CFG`、FLASH_CMD），
  与 RAM 版 OpenWrt 的同一组寄存器对比。

## 6. 资产

| 内容 | 路径 |
| --- | --- |
| 反编译输出 | `.research/appsbl-decomp2.log` |
| REA analyze 证据 | `.research/appsbl-analyze2.json` |
| LK 参考源码 | `.research/qpic_nand_lk.c` / `.research/qpic_nand_lk.h` |
| 原厂 rootfs（已解包） | `.research/stock_rootfs/`（内核 5.4.213，qcom_nandc 为内建） |
| 原厂 UBI 解包脚本 | `.research/ubi_extract.py` |

---

## 7. 19:32 实验：打开 QE 位（quad）后仍失败，但暴露了真正的问题

改动：`W25N01KW` 条目 flags `0` → `SPINAND_HAS_QE_BIT`，`make -j8` 重编
（19:08–19:32，全量重编约 24 分钟），RAM 启动成功。

结果：

```
nanddump -l 0x800 /dev/mtd19
  ECC failed: 2302  ECC corrected: 12
  ECC: 1 uncorrectable bitflip(s) at offset 0x00000000
连续 8 页逐页读：每页 1 个不可纠正错误
```

**自写自读复测（mtd22，当前驱动）**：写 2048×0xAA，

```
原始 sha256 6af367cb...
读回 sha256 b69ec1ad...
cmp -l: 57 字节不同，散布在 444, 517, 754, 777, 843, 948, 1033-1037, 1549-1557 ...
```

**关键证据**：写完后读该页 OOB，64 字节全是 `0xff`；而原厂页面的 OOB 有完整
ECC 字节（`ff df fa a3 75 85 4f 40 ...`）。

→ 结论修正：**QPIC 在 program 时根本没有生成/写入 ECC 奇偶校验**，
所以自写自读必然失败；这不是总线宽度问题（quad 已开，无变化）。
原厂页面读不出来是第二个问题（ECC 解码布局），但写路径不修，永远无法自洽。

Linux 驱动与工作驱动（qcom_nandc/LK）不一致的寄存器位：

| 字段 | spi-qpic-snand（坏） | qcom_nandc / LK（好） |
| --- | --- | --- |
| DISABLE_STATUS_AFTER_WRITE | 1 | 0 |
| NUM_ADDR_CYCLES | 3 | 5 |
| NAND_RECOVERY_CYCLES | 0 | 7 |
| WR_RD_BSY_GAP | 20 | 2 |
| ECC_BUF_CFG | 恒写 0x203 | 仅 `!qpic_version2` 时写 0x203 |

（SPI NAND 的地址周期数应当与并行 NAND 不同，这一项不能照搬；
但 status-after-write / bsy gap / recovery 这几项是候选。）

下一步：从 APPSBL 反编译出 `qpic_nand_init` 的实际 cfg0/cfg1 值，
按实际值改驱动寄存器；或先用 `devmem` 在 U-Boot / 原厂内核侧读同一组寄存器。

---

## 8. 19:55 反编译 qpic_nand_init：寄存器配置与 Linux 一致

从 APPSBL 二进制里取出 cfg0/cfg1 常量（Flash 常量 `DAT_4a4257b4` = `0x18040810`）：

| 字段 | U-Boot 实测 | Linux `spi-qpic-snand` |
| --- | --- | --- |
| UD_SIZE_BYTES（bits 18:9） | 516 | 516 |
| NUM_ADDR_CYCLES（29:27） | 3 | 3 |
| DISABLE_STATUS_AFTER_WRITE（bit4） | 1 | 1 |
| SPARE_SIZE（26:23） | 4 | 4 |
| PARITY_RS（22:19） | 0 | 7（`qcom_nandc` 也是 7） |
| WR_RD_BSY_GAP（cfg1 22:17） | 20 | 20 |
| RECOVERY_CYCLES（cfg1 4:2） | 0 | 0 |
| ECC_BCH_CFG | `0x42040000\|7<<8` = 516/7/4bit/force-clk | 相同 |
| BAD_BLOCK_BYTE | 465 | 465 |

**结论：初始化寄存器基本相同，之前猜的 status-after-write / bsy gap / recovery 差异
不成立**（DRAM 里 `0x280000>>17 = 20`，和 Linux 一样）。

差别在写路径的结构：U-Boot 的 `qpic_nand_write` → `FUN_4a4246e8` 按 codeword 下发
BAM 描述符，并在 ECC 使能时把 `ECC_BCH_CFG`（`+0x5c`）写进控制器；quad 标志
（`+0x60`）决定命令是 `x1` 还是 `x4`。

而 Linux 的 `qcom_spi_program_ecc` 只在前 n-1 个 codeword 写数据（`cw_data=516`），
不为它们写 OOB，依赖硬件生成 ECC——实测 OOB 全 `0xff`，说明硬件并没有生成。
这就是自写自读失败的落点，下一步要对照 U-Boot 的 528 字节/codeword 程序序列。

---

## 9. 20:05 决定性对比：U-Boot 写页有 ECC，Linux 没有

在 U-Boot 里对 crash 分区（物理偏移 0x64c0000）写入一页 0xAA：

```
U-Boot: nand erase 0x64c0000 0x20000
        nand write 0x47000000 0x64c0000 0x800   (0x47000000 已 mw.b 填 0xaa)
```

回到内存 OpenWrt 读同一页的 OOB：

```
mtd22（U-Boot 写的页）
00000000  ff c6 cb ae 82 9a 2a b0  ff ff ff ff ff c6 cb ae
00000010  82 9a 2a b0 ff ff ff ff  ff c6 cb ae 82 9a 2a b0
00000020  ff ff ff ff ...
```

- 12 字节/codeword 的周期非常清楚：`[1 BBM][7 ECC][4 spare]` × 4，最后 16 字节是空闲区
- **和 Linux 驱动的 `bytes = 7+4+1 = 12` 假设一致**
- 原厂页面的 OOB 也是同样的 12 字节周期

而 Linux 自己写同一页时 OOB 全 `0xff`（第 7 节）。

结论：

1. `nanddump -o` 确实能读出 ECC 字节——之前的"写路径没有 ECC"判断成立；
2. 布局（12 B/cw、64 B OOB）两边一致，不是布局问题；
3. 差异在 program 路径本身：同样的 cfg0/ecc_bch_cfg，U-Boot 的写让硬件生成
   了奇偶校验，Linux 的 `qcom_spi_program_ecc` 没有。

附注：U-Boot 里 `md 0x79b0000` 只能读到 0x00–0x18；0x1c 及之后是只写寄存器，
读取会触发 data abort 并复位。读到的 `FLASH_CMD = 0x78800034`
= `x4 | SPI_WP | SPI_HOLD | FS_DEVICE_WP | PAGE_ACC | LAST_PAGE | op 0x4`。

---

## 10. 20:20 写路径修复成功：program 必须用 OP_PAGE_PROGRAM_WITH_ECC

改动（`drivers/spi/spi-qpic-snand.c`，`SPINAND_PROGRAM_EXECUTE` 分支）：

```c
- SPI_WP | SPI_HOLD | OP_PROGRAM_PAGE);          /* 0x6 */
+ SPI_WP | SPI_HOLD | OP_PAGE_PROGRAM_WITH_ECC); /* 0x7 */
```

实测（RAM 启动，写 mtd22 一页 0xAA）：

```
QPIC PROG_ECC cw=4 cmd=0x38000037 cfg0=0x9a3c08d0 cfg1=0x8287440 bch=0x42040700 buf=0x203
QPIC PROG_ECC cw0 data=516 oob=12
...

OOB: ff c6 cb ae 82 9a 2a b0 | ff ff ff ff  ×4  ← 有 ECC 了
nanddump -n（raw 读）: 0 字节差异，2048/2048 完全一致
```

结论：**写路径已修好**——数据和 ECC 都正确写入，raw 读回逐字节一致。

## 11. 仍然卡在读路径

- 默认（带 ECC）读回仍有 38 字节差异，`ECC failed: 4`（4 个 codeword 全失败）
- 原厂页面 `ECC failed: 2293 → 2294`，没有改善
- 试过把读命令改成 `OP_PAGE_READ_WITH_ECC_SPARE (0x4)`（对齐 U-Boot 的 0x34），无改善
- 读侧插桩（`QPIC READ_ECC`）没有打印出来，读请求可能走了别的分支
  （`read_page_raw` / `read_page_oob`），需要再确认

下一步方向：确认读请求实际走的分支；若走 `read_page_ecc`，把
`read_location` 的 data/oob 切分改成与写路径对称的 516+12 / 500+27
（现在用的是 464+1+52+11 的旧布局），再测。

---

## 12. 20:33 读路径尝试全部无效，收口

已试（均无改善，读回仍 38 字节差异、每页 2 次 ECC failed）：

1. 读命令 `OP_PAGE_READ_WITH_ECC (0x3)` → `OP_PAGE_READ_WITH_ECC_SPARE (0x4)`
2. 去掉 `NAND_EBI2_ECC_BUF_CFG` 的写入（对齐 qcom_nandc 的
   `if (!qpic_version2)` 行为，0x203 不再被写）
3. cfg0 对齐 U-Boot 常量：清掉 bit31 `SET_RD_MODE_AFTER_STATUS`
   和 bits22:19 `ECC_PARITY_SIZE_BYTES_RS`

保留的有效改动：

- `SPINAND_PROGRAM_EXECUTE` 用 `OP_PAGE_PROGRAM_WITH_ECC (0x7)`：**写路径已修复**
- 移除 `ECC_BUF_CFG` 写入（与厂商驱动一致；无副作用）

待回退（验证无效、偏离厂商驱动）：

- 读命令回 `OP_PAGE_READ_WITH_ECC (0x3)`
- cfg0 恢复 bit31=1、`ECC_PARITY_SIZE_BYTES_RS=7`

## 13. 读路径剩余假设

- 硬件能力没问题：U-Boot 用同一颗 flash 正常读（原厂固件启动即证明）
- 写已能生成与 U-Boot 逐字节一致的 ECC，但同一控制器读回自己写的页仍
  `ECC failed`，说明读侧的 ECC 解码配置或 read_location 切分与写入不对齐
- 下一步建议：反编译 U-Boot `qpic_nand_read_page_scope_multi_page`
  实际写入的 cfg0/cfg1/ecc_bch_cfg（注意 0x1c 之后只写不可读），
  与 Linux 读路径逐位对比；重点看 read_location 的 data/oob 切分
  （Linux 当前 516+12 / 500+27，与写入一致，可能需要改成
  整页 2112 连续读取后由 ECC 引擎自行剔除 spare）

设备当前：内存版 OpenWrt（cfg0 测试镜像），断电重启回原厂。

---

## 14. 20:42 NAND_AUTO_STATUS_EN 也无效果，收口

U-Boot 读页时会写 `0x79b002c (NAND_AUTO_STATUS_EN) = 0xb000b`，两个 Linux 驱动
都没碰这个寄存器。已加入读路径并实测：**无改善**（每页仍 2 次 ECC failed）。

### 当前代码状态（已清理）

保留：
- `SPINAND_PROGRAM_EXECUTE` → `OP_PAGE_PROGRAM_WITH_ECC (0x7)`（写路径修复）
- 不写 `NAND_EBI2_ECC_BUF_CFG`（与 qcom_nandc 的 `!qpic_version2` 行为一致）

已回退（验证无效）：
- 读命令 0x4、cfg0 的 bit31/RS 对齐、NAND_AUTO_STATUS_EN、全部调试打印

注意：`bin/` 里 20:38 的镜像仍含实验改动，源码已清理；下次 `make -j8`
才会产出干净镜像。

### 读路径仍未解决，已知排除项

ECC 强度/步长、OOB 布局（12B/cw 已与 U-Boot 逐字节对齐）、cmd 变体、
ECC_BUF_CFG、AUTO_STATUS_EN、cfg0 差异，均已排除。
写已经能生成与 U-Boot 完全一致的 ECC，但读回仍然解码失败——
剩下最可能的是**读侧 DMA 描述符/read_location 的排布**与 U-Boot 不同
（U-Boot 每个 CW 用 12 字节的位置表 + 3~4 段描述符）。

---

## 15. 21:05 读描述符移植失败（已回退）

按 U-Boot 序列改 `qcom_spi_read_page_ecc`（最后 CW 500+16+12、
非最后 CW OOB=12、read cmd 加 `FS_DEVICE_WP`）后，RAM 启动成功但读路径
直接失效：

```
qcom_snand 79b0000.spi: failure in submitting cmd descriptor   (每 2 秒重复)
```

系统卡死、无 shell、无网络，只能断电恢复。已用补丁把源码回退到干净状态
（`patches/0001-...`）并重编，镜像在 TFTP 根目录待用。

结论：**描述符序列不能靠反编译猜测直接改**——BAM 描述符的长度限制/寄存器
写入顺序与 Linux 的 `qcom_write_reg_dma` 语义不同，猜错会让整个命令
描述符提交失败。

后续若还要做，需要先确认 U-Boot 每个描述符的 (dst, size, flags) 语义，
再用最小步进验证（比如只改最后 CW 的分段，不动非最后 CW）。

---

## 16. 21:20 决定性验证：U-Boot 能读 Linux 写的页

Linux（0x7 写路径）写入 mtd22 一页 0xAA 后，进入 U-Boot：

```
nand read 0x47000000 0x64c0000 0x800
  2048 bytes read: OK
crc32 0x47000000 0x800
  7ac10820        # = crc32(2048 × 0xAA)，与期望完全一致
```

结论：

1. **Linux 的写路径产物是标准的**：数据和 ECC 都能被 U-Boot 的 ECC 引擎正确解码
2. **问题 100% 在 Linux 读路径**：同一页同一个控制器，U-Boot 能读，Linux 读就
   报 ECC failed 并把数据改坏

新的主假设：Linux 的 `qcom_spi_read_page_ecc` **每个 codeword 发一次
读命令**（`qcom_spi_config_cw_read` 在循环里 4 次，每次 PAGE_ACC|LAST_PAGE），
而 U-Boot 是**每页发一次读命令**、随后用 BAM 描述符把整页搬出来。
按 CW 重复发命令会让 ECC 引擎的状态/解码上下文错乱。

下一步：把读路径改成"每页一条命令 + 按 CW 位置表搬运"，或先加
`qcom_spi_check_error` 的状态打印确认引擎报告的是纠正还是失败。

---

## 17. 21:35 尝试用原厂内核做参考：工具链受阻

原厂固件也是 Linux（5.4.213），其内建 `qcom_nandc` 能正常读这颗 flash，
是最理想的参考实现。已完成的准备工作：

- UBI 的 `kernel` 卷是 FIT：`kernel@1`，LZMA 压缩，load 0x40008000
- 已解出裸 ARM Image（10.7 MB）：`re/stock_vmlinux.bin`
- 解析脚本：`re/fit_extract.py`

受阻点：

1. 原厂系统没有 `/proc/kallsyms`（CONFIG_KALLSYMS 关闭），拿不到函数地址
2. 裸 Image 不是 ELF、无符号；字符串地址未出现在字面量池里
   （内核 PIC/KASLR，用 PC 相对寻址），无法直接定位引用点
3. 反编译 10 MB 裸 ARM 镜像需要完整 Ghidra 分析，成本高
4. 外网检索厂商源码/补丁被代理挡住（patchwork、lore 均不可达）

结论：这条路可行但成本高，需要专门安排时间做"裸镜像 + 符号恢复"。

---

## 18. 21:35 读命令加 FS_DEVICE_WP 失败（已回退）

把读命令对齐 U-Boot 的 `0x38080034`（`OP_PAGE_READ_WITH_ECC_SPARE` +
`FS_DEVICE_WP`）后，内核同样报：

```
qcom_snand 79b0000.spi: failure in submitting cmd descriptor   (每 2 秒)
```

系统卡死，需要断电。说明 **`FS_DEVICE_WP`(bit23) 在 Linux 这条 BAM 描述符
路径上不可用**（U-Boot 的裸机路径可以，但 Linux 的 `qcom_write_reg_dma`
提交方式不接受）。

教训：读命令/描述符相关改动一旦写错会让 RAM 会话卡死、只能断电恢复。
以后这类实验前先把可用镜像留在 TFTP 根目录，并准备断电。

已回退到干净补丁并重编；设备需断电重启恢复原厂。

---

## 19. 22:05 安全调试环境 + 原厂内核反编译进展

### 安全调试镜像（重要）

把 DTS 的 `bootargs-append` 从
`" ubi.mtd=rootfs ubi.block=0,ubi_rootfs root=/dev/ubiblock0_1 clk_ignore_unused"`
改成 `" clk_ignore_unused"`，启动时不再自动挂 UBI。实测：

- 正常启动、网络可用、`ubinfo` 显示 0 个 UBI 设备
- 读路径写坏时只会在命令层报错，不会卡死 init（不用再断电）

以后所有读路径实验都用这个镜像。测试完记得把 bootargs 改回去（安装流程需要）。

### 原厂内核反编译

- 原厂 FIT 的 kernel@1 是 LZMA 压缩的裸 ARM Image（10.7 MB）
- Ghidra 12.1.4 以 `ARM:LE:32:v7`、base `0x40008000` 完整分析成功
  （工程 `~/ghidra-stock`）
- PIC 寻址导致字符串引用没能自动建立，改为扫 QPIC 寄存器偏移常量：
  - `movw #0xf24` @ `0x40469af4`、`movw #0xf44` @ `0x40469b28`
  - 定位到寄存器偏移分派函数（起点约 `0x40469a18`），调用者：
    `0x40469c50`、`0x4046a6cc`

### 待查

加入了 `qcom_spi_check_error` 的状态打印（`QPIC CHK`），确认已编进
ITB 里的内核（解压后字符串存在），但运行时读页没有打印，dmesg 为空。
需要下次确认读请求实际走的是哪条分支（可能是 raw/oob 路径）。

---

## 20. 22:17 关键线索：移植作者用的是 8-bit/128B OOB 的另一种闪存

翻到上游移植仓库 `victorpivotto-cloud/openwrt-xiaomi-be3600-rd15` 的
`docs/hardware.md`：

> Flash: SPI-NAND **GD5F1GM7REYIG**，128 MiB，2048 B 页，**128 B OOB**，
> 主机 ECC **8 bit / 512 B**（4/512 会 `-EBADMSG`）

也就是说：
- 同一个 `spi-qpic-snand` 驱动在 **8-bit + 128 B OOB** 的 GD5F 上是能工作的
- 我们这台是 **Winbond W25N01KWZEIG，64 B OOB，4-bit**（原厂 DTB 也是 4-bit）
- **驱动的 4-bit / 64 B OOB 这条几何路径可能本身有 bug**

## 21. 22:17 8-bit 实验（失败，已回退）

- DTS 改 `nand-ecc-strength = <8>`：写页 OOB 全 0xff（ECC 未生成），
  自读 61 字节差异
- 再加上 `cw_data = 512`（64 B OOB 下 8-bit 需 512+16=528）：OOB 仍全 0xff，
  自读 54 字节差异

结论：64 B OOB 的 Winbond 上跑 8-bit 不可行；已回退到 4-bit 干净状态并重编。

## 22. 下一步建议

对照"能工作的 8-bit/128B 路径"和"坏掉的 4-bit/64B 路径"，重点看：
- `qcom_spi_ooblayout_ecc/free` 在 64 B/4-bit 下的区间（0..37 + 53..64，
  空闲 37..53）与实测硬件布局（ECC 0..47、空闲 48..64）**不一致**
- `cw_data=516`、`spare_bytes=4`、`ecc_bytes_hw=7` 的组合是否适用于 64 B OOB
- `qcom_spi_program_ecc` 的 per-CW 数据/奇偶加载顺序

上述差异很可能就是上游要修的点，适合写进 linux-mtd 报告。

---

## 23. 22:45 确认镜像链路正常 + 读走 dirmap

在 `qcom_spi_probe` 加了 `QPIC PROBE MARKER` 后启动：

```
[0.959003] qcom_snand 79b0000.spi: QPIC PROBE MARKER 2026-11-14-A
[0.961210] spi-nand spi0.0: Winbond SPI NAND was found.
```

说明镜像/驱动都是最新构建，之前的“打印不出来”不是构建问题。

而读页时 `qcom_spi_read_page` 与 `qcom_spi_check_error` 的打印都没有出现，
说明 **mtd 读没有走 `qcom_spi_read_page`**，而是走 SPI-NAND 核心的
dirmap 路径（`spinand_mtd_read` → `spi_mem_dirmap_read`）。
下一步需要抓 `qcom_spi_exec_op` 的完整 opcode 序列（已加
`QPIC EXECSEEN` 打印，镜像已构建，等待上机测试）。这能直接看出读页时
ECC 相关命令是否真的下发、参数是什么。

设备在 22:45 后串口只剩噪声、网络不通，疑似断电或复位异常，
需要物理检查后再继续。

---

## 24. 00:03 读路径追踪：打印被启动阶段耗尽

在 `qcom_spi_probe` 标记确认镜像新鲜之后，启动日志里抓到了驱动真实的 op 序列：

```
[4.931] QPIC EXECSEEN op=13 addr=0x0 a=1/3 d=0:0:0
[4.937] QPIC EXECSEEN op=0b addr=0x800 a=1/2 d=1:1:64
[4.943] QPIC READ entry page=0 raw=1 oob=1 len=64
```

这是 probe 阶段读 OOB/坏块标记（raw=1），说明 `qcom_spi_exec_op` 打印本身有效。

之前"读页没有打印"的原因：调试计数器在启动阶段被这些 BBM/OOB 读消耗完了，
不是读路径不走驱动。

已改为**无条件打印**并构建了 00:02 镜像（`EXECSEEN` 每次 op 都打），
计划：开机后 `dmesg -c` 清空，再读一页，只留下本次读的完整序列。

设备在 00:05 再次出现串口噪声（0xEF/0xFE）、网络不通，需要断电重启。

---

## 25. 00:16 移植上游关键修复：SET_FEATURE 写时序

对比上游 master 的 `spi-qpic-snand.c`（648 行 diff）发现一个疑似根因：

**旧驱动在 `qcom_spi_io_op()` 里处理 `SPINAND_SET_FEATURE`：先排入
FLASH_CMD/EXEC 描述符，再把 feature 值写进 `NAND_FLASH_FEATURES`。**
上游注释指出：feature 值必须在命令执行**之前**写入，否则控制器会沿用
上一次的旧值。

这会影响两件关键的事：
1. spi-nand 核心初始化时用 SET_FEATURE 关闭芯片**片内 ECC**
   （`spinand_ecc_enable(spinand, false)`）
2. 用 SET_FEATURE 设置/读取 **QUAD 使能位**（配置寄存器 0xB0）

如果片内 ECC 从没被真正关闭，芯片自带的 ECC 会和主机 ECC 冲突——这正好
解释“写进去的页 U-Boot 能正确读、Linux 读回来却 ECC 全错”。

### 已做的改动（`spi-qpic-snand.c`）

1. `qcom_spi_send_cmdaddr()`：在写 FLASH_CMD 之前，先把 feature 值写进
   `NAND_FLASH_FEATURES`（上游做法）
2. `qcom_spi_io_op()`：`SPINAND_SET_FEATURE` 分支改为 `return 0`
3. 加 `QPIC SETFEATURE addr=.. val=..` 打印，便于确认片内 ECC/QUAD 写入

镜像：00:16 构建，已复制到 TFTP 根目录。
设备在 00:10 后断电/无响应，等上电后测试：

```
# 预期启动日志里能看到 SETFEATURE val 里 ECC 位被清零、QUAD 位被置位
nanddump -l 0x800 /dev/mtd19        # 期望 ECC failed: 0
dd ... /dev/mtd22; dd 读回比对        # 期望 0 字节差异
```

---

## 26. 00:23 根因确认并修复：SET_FEATURE 写时序

**根因**：`qcom_spi_io_op()` 处理 `SPINAND_SET_FEATURE` 时，先把 FLASH_CMD/EXEC
排进 BAM 描述符，再把 feature 值写进 `NAND_FLASH_FEATURES`。命令执行时读到的
是寄存器里的旧值——于是：

- `spinand_ecc_enable(false)`（关闭芯片片内 ECC）**从未真正生效**；
- QUAD 使能位也没写上。

片内 ECC 一直开着，与主机 ECC 冲突：写进去的页 U-Boot 能正确读，
Linux 自己读回来却 ECC 全错（解码被片内 ECC 干扰）。

**修复**（对齐上游 master 的 `spi-qpic-snand`）：

1. `qcom_spi_send_cmdaddr()`：在 FLASH_CMD 之前把 feature 值写入
   `NAND_FLASH_FEATURES`；
2. `qcom_spi_io_op()` 的 `SPINAND_SET_FEATURE` 分支改为 `return 0`。

**验证**（00:23 干净镜像，正常启动参数）：

```
UBI 自动挂载：Volumes count 2（kernel、ubi_rootfs），336 LEBs
原厂页读取：  ECC failed: 0, ECC corrected: 1
rootfs 卷:    "hsqs"（squashfs 魔数正确）
自写自读:     write/read OK（0 字节差异）
```

## 27. 最终代码改动（`patches/0001-...`）

1. `PROGRAM_EXECUTE` 使用 `OP_PAGE_PROGRAM_WITH_ECC (0x7)`（H/W 生成 ECC 的前提）
2. `SET_FEATURE` 写时序修复（根因）
3. 移除 `NAND_EBI2_ECC_BUF_CFG` 写入（对齐 `qcom_nandc` 的 qpic v2 行为）

镜像：`images/rd15-fixed-initramfs.itb`
sha256 `127b0c2a75a877475b6f13013ed3154b8a4980733f70b0f1cb2f77fe8a54cfb1`

---

## 28. 2026-11-15 10:50 2.5G 口打通（QCA8081 批次）

### 本机 PHY 与移植作者不同

- 本机：**QCA8081**，MDIO `0x0c`，ID `0x004dd101`
- 作者机器：YT8821，MDIO `0x07`
- 原厂脚本判断：`[ -d /sys/bus/mdio_bus/devices/90000.mdio:0c ]` → qca8081

### 打通所需

1. DTS `&mdio` 下加 `ethernet-phy@c`
2. `&qcom_ppe` 加 `port@1`：`phy-mode = "sgmii"`，
   **`managed = "in-band-status"`**（关键！），`pcs-handle = <&pcs0_ch0>`，
   PORT1 的 MAC/RX/TX 时钟与复位
3. 开启 `CONFIG_MOTORCOMM_PHY`（对 QCA8081 不是必需，QCA808X 驱动已内置）
4. PPE 补丁 9991（错误路径 unwind）

### 现象与坑

- 只配 `sgmii`（out-of-band）：链路 up、桥接 forwarding，但 **eth1 RX=0**
- 加 `managed = "in-band-status"`：链路稳定后 RX/TX 正常，ping/SSH 全通
- 中间多次"链路 up 1 秒就掉"是**网线/水晶头接触不良**（协商到 100M 甚至 10M），
  换好线后稳定 1Gbps

### sysupgrade 的坑（重要）

从 RAM 系统执行 `sysupgrade` 后，**kernel 卷没有被更新**（rootfs 更新了）：
启动后的 `/proc/device-tree` 里只有 `port@2`，没有 `port@1`，因此 eth1 不存在。

验证方法：

```
dd if=/dev/ubi0_0 bs=4096 count=1200 2>/dev/null | grep -a -c eth1   # 0 表示旧内核
```

修复：手动写 kernel 卷

```
ubiupdatevol /dev/ubi0_0 /tmp/kernel-new.itb
sync && reboot
```

之后 `eth1` 出现（`qca8081` 绑定、`inband/sgmii`），加入到 `br-lan` 即工作。

当前状态：2.5G 口以 **1000Mbps** 工作（PC 是 1G 网口），
`rx=49 tx=46`，ping 0% 丢包。安装镜像的 kernel 卷已是含 port1 的版本：
`xiaomi_rd15-uImage.itb` sha256 `15ba39f7…`
