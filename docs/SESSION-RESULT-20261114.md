# RD15 · 2026-11-14 会话结果（保存用）

> 本轮目标：让 OpenWrt 内核在这台机器的 Winbond W25N01KW 上正确读写 NAND。
> 结论：**写路径已修复并可复现；读路径的 ECC 解码仍未解决。**
> 详细证据见 `RE-FINDINGS-20261114.md`（分段记录每一轮的假设与实测）。

---

## 1. 最终状态

| 项 | 状态 |
| --- | --- |
| 写路径（ECC 生成、数据落盘） | ✅ 已修复，raw 读回 2048/2048 逐字节一致 |
| 读路径（ECC 解码） | ❌ 仍失败，每页 2 次 ECC failed |
| 设备 | 原厂固件运行中，flash 仅 crash 分区有测试页 |
| 构建树源码 | 已清理，只保留写路径修复；见下方补丁 |

## 2. 唯一需要的代码改动

补丁：`patches/0001-spi-qpic-snand-program-with-ecc.patch`

```diff
 case SPINAND_PROGRAM_EXECUTE:
     *cmd = (PAGE_ACC | LAST_PAGE | SPI_TRANSFER_MODE_x1 |
-            SPI_WP | SPI_HOLD | OP_PROGRAM_PAGE);
+            SPI_WP | SPI_HOLD | OP_PAGE_PROGRAM_WITH_ECC);
```

另外移除了 `NAND_EBI2_ECC_BUF_CFG` 的写入（对齐 `qcom_nandc` 的
`if (!nandc->props->qpic_version2)` 行为）。

**作用**：QPIC 的 ECC 引擎只有在 `OP_PAGE_PROGRAM_WITH_ECC (0x7)` 时才会在
program 阶段生成奇偶校验，`OP_PROGRAM_PAGE (0x6)` 下 OOB 全为 `0xff`。

## 3. 读路径：已排除项

按顺序排除（每项都有实测记录）：

1. ECC 强度/步长（4-bit / 512，与原厂 DTB 一致）
2. OOB 布局（12 B/codeword，与 U-Boot 写出的逐字节同构）
3. 芯片 ID / QE / quad 模式（开 QE 无改善）
4. 读命令变体：`0x3`、`0x4` 都试过
5. `ECC_BUF_CFG`（写入与不写都试过）
6. `NAND_AUTO_STATUS_EN = 0xb000b`（U-Boot 会写，Linux 加了无改善）
7. cfg0 与 U-Boot 对齐（清 bit31 / `ECC_PARITY_SIZE_BYTES_RS`）

## 4. 剩余假设

读侧 DMA 描述符 / `read_location` 排布与 U-Boot 不同。U-Boot 的 ECC 读页序列：

```
FLASH_CMD = 0x38080034  (x1|WP|HOLD|FS_DEVICE_WP|PAGE_ACC|LAST_PAGE|op 0x4)
每 CW：516 数据 + 12 spare
最后 CW：500 + 16 + 12（三段）
每 CW 一个 12 字节位置表项，最后 CW 用 LAST_CW_0..3
```

Linux 当前：最后 CW 是 500+27 两段、位置寄存器只用 2 个、命令缺
`FS_DEVICE_WP`。完整移植是下一步工作。

## 5. 本轮工具链（可复用）

| 组件 | 位置 |
| --- | --- |
| rea-agents 6.7.0（DSH 插件固定版本） | `~/.dsh/profiles/web/node_modules/rea-agents` |
| Ghidra 12.1.4 | `~/.local/tools/ghidra_12.1.4_PUBLIC` |
| JDK 25 | `~/.local/tools/jdk-25.0.5+8` |
| APPSBL Ghidra 工程 | `~/ghidra-proj/qpic`（程序 `mtd14_0_APPSBL.bin`） |
| 反编译脚本 | `ghscripts/DumpQpic.java`、`DumpInit.java`、`DumpByAddr.java` |

## 6. 复现命令

```sh
cd rd15-build
export PATH=$PWD/../rd15-openwrt/.deps/root/usr/bin:$PATH
make -j8

# 发布到 TFTP 根目录（dnsmasq 已在 192.168.31.100:69）
cp bin/targets/qualcommbe/ipq53xx/*initramfs-uImage.itb \
   ../rd15-openwrt/out/rd15-r35705-20261114/

# RAM 启动（内存版里 reboot 不生效，先 sysrq）
ssh -i keys/rd15_openwrt_ed25519 root@192.168.31.1 'echo b > /proc/sysrq-trigger'
python3 .research/ram_boot.py --port /dev/ttyACM0 --wait \
  --file openwrt-qualcommbe-ipq53xx-xiaomi_rd15-initramfs-uImage.itb
```

验证写路径：

```sh
flash_erase /dev/mtd22 0 1
dd if=/dev/zero bs=2048 count=1 | tr '\000' '\252' > /tmp/p
dd if=/tmp/p of=/dev/mtd22 bs=2048 count=1
nanddump -n -a -l 2048 /dev/mtd22 > /tmp/raw   # raw 读，应与 /tmp/p 完全一致
nanddump -o -l 2048 /dev/mtd22 | tail -c 64 | hexdump -C   # OOB 应有 ECC 字节
```

## 7. 下一步（二选一）

1. **继续移植读描述符**：按第 4 节序列改 `qcom_spi_read_page_ecc`，
   预计 1–3 轮编译；不保证成功。
2. **出上游报告**：linux-mtd 邮件列表，附本文件与 `RE-FINDINGS-20261114.md`
   的证据链。写路径的 `0x7` 发现本身就有上游价值。

---

## 8. 归档产物（2026-11-14 20:51）

| 文件 | 说明 |
| --- | --- |
| `patches/0001-spi-qpic-snand-program-with-ecc.patch` | 唯一代码改动，已用 `patch -p1 --dry-run` 验证 |
| `images/rd15-qe-writefix-initramfs.itb` | 干净源码编译，含写路径修复 |
| `images/rd15-qe-writefix-sysupgrade.bin` | 同版本 sysupgrade |
| `images/SHA256SUMS` | 上面两个文件的校验和 |
| `re/qpic-read-func.c` / `qpic-init-func.c` | APPSBL 反编译输出 |
| `re/qpic_nand_lk.c` / `.h` | Qualcomm LK 参考源码 |

initramfs `sha256 = d094d63f8e894e53712d757da4c2ce4d1769298ac02a36256686171943584a7d`

---

## 9. 2026-11-15 00:25 更新：NAND 读写问题已解决

根因是 `SPINAND_SET_FEATURE` 的 BAM 写时序：feature 值在命令之后才写，
导致 spi-nand 核心关闭"片内 ECC"的操作从未生效，芯片 ECC 与主机 ECC 冲突。

修复后（`patches/0001` 现含三处改动）：
- 原厂页读：ECC failed 0
- 自写自读：逐字节一致
- UBI 自动挂载、卷与 squashfs 均正常

镜像：`images/rd15-fixed-initramfs.itb`（`sha256 127b0c2a…`）

**下一步（需用户确认，未执行）**：用 `install-slot0.sh` 把 OpenWrt 写入槽 0。
设备当前仍在原厂固件上（RAM 跑修复版），flash 只有 crash 分区测试页。

---

## 10. 2026-11-15 08:40 安装完成，OpenWrt 已跑在槽 0

根因（详见 RE-FINDINGS 第 26 节）：`SPINAND_SET_FEATURE` 的 BAM 写时序错误，
芯片片内 ECC 从未被关闭。修复后读写完全正常。

### 安装过程（两次）

1. 第一次用 `out/` 里 17:45 的旧内核 FIT → 启动时 UBI 挂载失败
   （装进去的内核不含修复）。设备卡在等待 root 设备，断电恢复。
2. 用重建后的内核（`build_dir/.../xiaomi_rd15-uImage.itb`，00:22）+ root.squashfs
   重跑安装器 → `INSTALL_OK`。
3. 重启验证：

```
cmdline: ubi.mtd=rootfs ...
/rom:  squashfs (ro)
/overlay: ubifs on /dev/ubi0_2 (rw)
/ : overlayfs
ubi0: 3 volumes (kernel, ubi_rootfs, rootfs_data)
持久化测试：写 /etc/persist-test → 重启 → 文件仍在
```

### 归档镜像（`images/`）

| 文件 | sha256 |
| --- | --- |
| `rd15-fixed-initramfs.itb` | `127b0c2a75a8…` |
| `rd15-fixed-kernel-uImage.itb` | `3b6b7da9d85a…` |
| `rd15-fixed-root.squashfs` | `374a70a67d34…` |
| `rd15-fixed-sysupgrade.bin` | `1f9885215478…` |

`out/rd15-r35705-20261114/` 里的 `xiaomi_rd15-uImage.itb`、`root.squashfs`
已更新为修复版（08:36）。

### 回退（槽 1 原厂固件保持未动）

U-Boot 串口（`bootdelay=15`）：

```
setenv flag_boot_rootfs 1
saveenv
reset
```

切回槽 1 即原厂系统；改回 0 再 `saveenv` 可回 OpenWrt。
若 OpenWrt 无法启动，用 TFTP 引导 initramfs 后重跑安装器即可。

---

## 11. 2026-11-15 08:55 LuCI 网页界面

- 构建启用 `CONFIG_PACKAGE_luci=y` + `cgi-io`，主题带
  `luci-theme-openwrt-2020`、`luci-theme-material`、`luci-theme-bootstrap`
- 默认主题通过 `files/etc/uci-defaults/90-luci-theme` 设为 openwrt2020
- 已通过 sysupgrade 升级（保留配置），Web 正常：

```
GET  /              → 302 到 /cgi-bin/luci/
GET  /cgi-bin/luci/ → 403 + 登录页（未认证）
POST 空密码登录     → 302 /cgi-bin/luci/admin/status/overview
```

镜像：`images/rd15-luci-sysupgrade.bin`
sha256 `7f8dcf748d6364a122e8e43bc745cc0cb0f036a97fdb9b10f243e33fcdad061f`

注意：root 密码为空，需尽快在 LuCI「系统 → 管理权」设置。

---

## 12. 2026-11-15 09:00 基础配置

| 项目 | 值 |
| --- | --- |
| root 密码 | `admin`（SSH 与 LuCI） |
| 主机名 | `rd15` |
| 时区 | `CST-8` / Asia/Shanghai |
| LAN | 192.168.31.1/24 |
| DHCP | 开启，192.168.31.150–254，租期 12h |
| 防火墙 | fw4 规则已加载（135 行） |
| 默认主题 | openwrt2020（另有 material / bootstrap 可切换） |
| Wi-Fi | 驱动正常，AP 仍为 disabled |

备注：
- 安全默认里 `dhcp.lan.dhcpv4` 原本是 disabled，已改为 server
- 无 WAN/上游，NTP 无法同步，时钟已手动设置；重启后回到构建时间
- 配置备份：`backups/config/rd15-openwrt-config-20261115.tar.gz`
  （sha256 `f765aef5…`）

---

## 13. 2026-11-15 10:50 2.5G 口启用

- 本机 2.5G PHY 是 **QCA8081 @ MDIO 0x0c**（作者机器是 YT8821 @0x07）
- DTS 增加 `port@1`（sgmii + **in-band-status** + pcs0_ch0 + 时钟/复位）
- kernel 卷需手动 `ubiupdatevol`（sysupgrade 只更新了 rootfs），
  否则启动后没有 eth1
- 结果：eth1 1000Mbps（PC 侧 1G），桥接进 br-lan，ping/SSH 正常

工作内核 FIT：`xiaomi_rd15-uImage.itb` sha256 `15ba39f7…`
