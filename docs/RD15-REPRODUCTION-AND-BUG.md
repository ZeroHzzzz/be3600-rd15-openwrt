# RD15 复现与排障记录（设备数据 + 方法 + 根因）

> 目的：让其他人拿到同型号机器时，能按本文复现检测、判断自己的硬件批次，
> 并避开我们踩过的坑。配套证据见 `RE-FINDINGS-20261114.md`。
>
> 隐私说明：MAC、序列号、Wi-Fi 校准数据已做脱敏；`ART`/`bdata` 分区
> 属于每台设备独有，**不要复制或外传**。

---

## 1. 设备与实测数据（本机）

| 项目 | 实测值 | 获取方式 |
| --- | --- | --- |
| 型号 | 小米 BE3600 2.5G，代号 `RD15` | `cat /tmp/sysinfo/board_name` → `xiaomi,rd15` |
| SoC | Qualcomm IPQ5332，4×Cortex-A53，256 MiB DDR | 原厂 `dmesg`、`bdinfo` |
| 原厂固件 | MIWIFI 1.0.87（OpenWrt 18.06，内核 5.4.213，armv7l） | `cat /etc/openwrt_release` |
| 参考板 | AP-MI04.1-C2 | 原厂 `/tmp/sysinfo/board_name` |
| 闪存 | **Winbond W25N01KWZEIG**，128 MiB SPI-NAND | 原厂 `dmesg`：`Manufacturer ID 0xef, Chip ID 0xbe` |
| 闪存参数 | page 2048 B，OOB **64 B**，erase 128 KiB，SLC | `dmesg` / U-Boot `nand info` |
| 原厂 ECC | **4-bit / 512 B**，bus-width 8 | 原厂 DTB `/soc/nand@79b0000/nandcs@0` |
| NAND 控制器 | QPIC `79b0000.nand` / `79b0000.spi` | `dmesg` |
| U-Boot | 2016.01，`bootcmd=bootmiwifi`，`ethprime=eth1` | 串口 `version`、`printenv` |
| 串口 | 115200 8N1，**1.8 V** 逻辑；CH343G 适配器枚举为 CDC-ACM | `/dev/ttyACM0` |
| 2.5G PHY | **QCA8081**，MDIO 地址 `0x0c`，PHY ID `0x004dd101` | `/sys/class/mdio_bus/.../phy_id` |
| 交换芯片 | Motorcomm YT9215S（LAN1–3），MDIO `0x1d` | `dmesg` |
| MAC 地址 | `90:fb:5d:1c:xx:xx`（已脱敏） | 原厂 `nvram`、`ip link` |

### 分区（原厂 SMEM 布局，Linux mtd 编号）

| mtd | 名称 | 说明 |
| --- | --- | --- |
| 2 | `0:MIBIB` | 分区表，**永不写** |
| 14/15 | `0:APPSBL` / `_1` | U-Boot，**永不写** |
| 13 | `0:APPSBLENV` | U-Boot 环境（含槽位标志） |
| 17 | `0:ART` | 每机 Wi-Fi 校准/MAC，**永不写、不分享** |
| 19 | `rootfs` | 槽 0，42 MiB，UBI |
| 20 | `rootfs_1` | 槽 1，42 MiB，UBI |
| 22 | `crash` | 测试/崩溃转储，实验中做过读写测试 |

### 2.5G PHY 存在两种硬件批次（重要）

- 移植作者的机器：**YT8821**，MDIO `0x07`，PHY ID `0x4f51ea19`
- 本机：**QCA8081**，MDIO `0x0c`，PHY ID `0x004dd101`

原厂 `/lib/miwifi/arch/lib_arch_phy_eth.sh` 的判断逻辑：

```sh
PHY_TYPE=$( [ -d /sys/bus/mdio_bus/devices/90000.mdio:0c ] && echo "qca8081" || echo "yt8821")
```

**结论：同型号不同批次，2.5G PHY 不同。** 不要照搬别人 DTS 里的 PHY 地址。

---

## 2. 如何得到这些数据（方法）

1. **串口**：1.8 V USB-TTL，115200 8N1。只接 GND/路由 TX/RX，不接 VCC。
   原厂默认 `uart_en=0`，需先通过 SSH 写
   `nvram set uart_en=1; nvram set boot_wait=on; nvram set bootdelay=15; nvram commit`。
2. **TFTP + RAM 引导**：PC 静态 `192.168.31.100/24`，dnsmasq 提供 TFTP；
   U-Boot 里 `tftpboot 0x47000000 <initramfs.itb>`，再
   `bootm 0x47000000#config@mi04.1-c2`。网线接 **LAN 口**（U-Boot 的 eth0 在交换机上）。
3. **原厂 DTB**：从原厂固件的 FIT 中提取 `fdt@1`，用 `dtc -I dtb -O dts` 查看。
4. **MDIO/PHY 探测**：给 DTS 的 `&mdio` 加 `ethernet-phy@<addr>` 节点，
   RAM 启动后读 `/sys/class/mdio_bus/<bus>/<bus>:<addr>/phy_id` 与 `driver` 符号链接；
   缺失会打印 `MDIO device at address N is missing`。
5. **QPIC 寄存器/命令追踪**：在内核驱动里临时加 `dev_info` 打印
   `qcom_spi_exec_op` 的 opcode/地址/长度，以及 `qcom_spi_program_ecc` 的
   cfg0/cfg1/ecc_bch_cfg。注意：调试计数器会被启动阶段的 BBM 扫描耗尽，
   要么改成"开机后清空 dmesg 再复现"，要么按 opcode/长度过滤。
6. **原生固件对照**：U-Boot 里 `nand read` + `crc32` 验证内核写入的数据；
   用 U-Boot 写一页，再回 Linux 读 OOB，交叉验证 ECC 布局。
7. **原厂内核分析**：UBI `kernel` 卷是 LZMA 的裸 ARM Image，可用
   `scripts/feeds` 同源的 Ghidra（ARM:LE:32:v7，base 0x40008000）分析；
   无 `/proc/kallsyms`（CONFIG_KALLSYMS 关闭），符号恢复困难。

---

## 3. 核心 bug：NAND 读写（已解决）

### 现象

- 原厂 UBI 挂不上：`vtbl_check: bad CRC`、`ECC failed: 2293`
- 内核写页再读回 sha 不一致
- U-Boot 读内核写的页报 `ecc failure`

### 根因

`spi-qpic-snand` 驱动处理 `SPINAND_SET_FEATURE` 时，**先排入 FLASH_CMD/EXEC
描述符，之后才把 feature 值写进 `NAND_FLASH_FEATURES`**。命令执行时读到旧值，
导致 spi-nand 核心关闭**芯片片内 ECC** 的操作从未生效；片内 ECC 与主机 ECC
冲突，于是数据写进去 U-Boot 能读、Linux 自己读不回来。

### 为什么是内核 bug

- 同类操作在慢速/串行路径下可能"碰巧"正确，BAM 批量提交时暴露；
- 上游 master 已修复该顺序（`qcom_spi_send_cmdaddr()` 中先写 feature 再发命令），
  并补充了 QUAD 模式、`0xeb/0x6b/0x34` opcode 等支持；
- 我们使用的 OpenWrt 6.18.39 内核树仍是旧实现，属于**缺少上游修复的驱动 bug**，
  不是硬件故障，也不是配置错误。

### 需要移植的两处驱动改动

1. `SPINAND_PROGRAM_EXECUTE` 用 `OP_PAGE_PROGRAM_WITH_ECC (0x7)`
   （否则 QPIC 不生成 ECC，OOB 全 0xff）
2. `SET_FEATURE` 值在 `FLASH_CMD` 之前写入（根因）

可选：不写 `NAND_EBI2_ECC_BUF_CFG`，对齐 `qcom_nandc` 的 `qpic_version2` 行为。

补丁：`patches/0001-spi-qpic-snand-program-with-ecc.patch`
（构建树正式补丁：`rd15-build/target/linux/qualcommbe/patches-6.18/2041-*.patch`）

---

## 4. 实验记录（按时间，结论已固化）

| 实验 | 结果 |
| --- | --- |
| 原厂 DTB 解析 | 4-bit ECC / 512 / bus-width 8 |
| 读 OOB 原始字节 | 12 B/codeword 周期，ECC 布局与 U-Boot 一致 |
| 写命令 0x6 → 0x7 | OOB 出现 ECC，raw 读回 0 差异 |
| 读命令 0x3/0x4 变体 | 均无效（当时写路径未修） |
| 清 `ECC_PARITY_RS` / bit31 | 无效 |
| `NAND_AUTO_STATUS_EN=0xb000b` | 无效 |
| 8-bit ECC（64 B OOB） | 不可行（需要 cw_data=512 且仍未生成 ECC） |
| **`SET_FEATURE` 时序修复** | **读写全部正常** |
| U-Boot 读 Linux 写的页 | `2048 bytes read: OK`，crc 一致（证明写路径标准） |

---

## 5. 复现/验证步骤（最短路径）

```sh
# 1) 构建（本仓库构建树）
cd rd15-build
export PATH=$PWD/../rd15-openwrt/.deps/root/usr/bin:$PATH
make -j8

# 2) 发布到 TFTP 根目录（dnsmasq 监听 192.168.31.100:69）
cp bin/targets/qualcommbe/ipq53xx/*initramfs-uImage.itb \
   ../rd15-openwrt/out/rd15-r35705-20261114/

# 3) RAM 启动（内存版 reboot 不生效，先 sysrq）
ssh root@192.168.31.1 'echo b > /proc/sysrq-trigger'
python3 .research/ram_boot.py --port /dev/ttyACM0 --wait \
  --file openwrt-qualcommbe-ipq53xx-xiaomi_rd15-initramfs-uImage.itb

# 4) 验证 NAND
nanddump -l 0x800 /dev/mtd19      # 期望 ECC failed: 0
ubiattach -m 19 -d 0              # 期望成功，卷名 kernel/ubi_rootfs

# 5) 验证自写自读
flash_erase /dev/mtd22 0 1
dd if=/dev/zero bs=2048 count=1 | tr '\000' '\252' > /tmp/p
dd if=/tmp/p of=/dev/mtd22 bs=2048 count=1
dd if=/dev/mtd22 bs=2048 count=1 | cmp - /tmp/p && echo OK
```

安装到槽 0：`sh install-slot0.sh <kernel.itb> <sha> <root.squashfs> <sha>`，
成功会输出 `INSTALL_OK`。

---

## 6. 当前状态与限制

- 槽 0：OpenWrt（r0+35705-e46ea77ba4，6.18.39），NAND 修复已包含
- 槽 1：原厂固件保持未动（回退用；注意 `flag_boot_rootfs` 的切换本机未验证成功）
- LuCI：已装，默认主题 openwrt2020；root 密码 `admin`
- DHCP：192.168.31.150–254
- **2.5G 口**：RAM 测试镜像里 `eth1` 已创建、QCA8081 绑定成功，
  待物理网线验证链路/吞吐；安装镜像尚未合并该改动
- Wi-Fi：驱动正常，AP 未启用
- NTP：无 WAN 上游，无法同步

---

## 7. 2.5G 口（已打通，2026-11-15）

### 两种 PHY 批次

- 本机：**QCA8081**，MDIO `0x0c`，ID `0x004dd101`
- 另一批次：YT8821，MDIO `0x07`，ID `0x4f51ea19`
- 判断方法：原厂脚本看 `90000.mdio:0c` 是否存在

### 需要的 DTS 配置

```dts
&mdio {
	yt8821: ethernet-phy@7 { reg = <7>; };      /* 可选，探测用 */
	qca8081: ethernet-phy@c { reg = <0x0c>; };  /* 本机 */
};

&qcom_ppe {
	ethernet-ports {
		ppe_port1: port@1 {
			reg = <1>;
			phy-mode = "sgmii";
			managed = "in-band-status";   /* 关键：QSDK 用 in-band AN */
			phy-handle = <&qca8081>;
			pcs-handle = <&pcs0_ch0>;
			clocks = <&nsscc NSS_CC_PORT1_MAC_CLK>,
				 <&nsscc NSS_CC_PORT1_RX_CLK>,
				 <&nsscc NSS_CC_PORT1_TX_CLK>;
			clock-names = "mac", "rx", "tx";
			resets = ...PORT1...;
			reset-names = "mac", "rx", "tx";
		};
	};
};
```

要点：

- 只配 `sgmii`（out-of-band）时链路能 up，但 **RX 永远 0**
- 加 `managed = "in-band-status"` 后正常收发
- 不要用 `2500base-x`（当前 PCS 下链路不稳）
- 网线质量差会导致 10M/100M 抖动，别误判成驱动问题

### 内核 FIT 更新注意

从 RAM 系统 sysupgrade 后，**kernel 卷不会更新**，启动后没有 `port@1`。
必须手动：

```sh
ubiupdatevol /dev/ubi0_0 /tmp/xiaomi_rd15-uImage.itb
sync && reboot
```

验证：`dd if=/dev/ubi0_0 bs=4096 count=1200 | grep -a -c eth1` 应为 1。

当前安装镜像：eth1 = QCA8081，1000Mbps（PC 为 1G 网口），
桥接进 br-lan，ping/SSH 正常。
