# 小米 BE3600 2.5G (RD15) 刷 OpenWrt 全过程记录

> 记录把 OpenWrt 装进小米 BE3600 2.5G（RD15，IPQ5332）时遇到的问题、原因和
> 解决方式。文中 MAC 已脱敏；`ART` 分区是每台机器独有的数据，不要复制外传。

---

## 1. 目标

- 在 RD15 上安装并运行 OpenWrt（保留原厂固件作为回退）
- 解决移植镜像"能启动但 NAND 挂载失败/读写不一致"的问题
- 启用 2.5G 网口

## 2. 设备信息（本机实测）

| 项目 | 实测值 |
| --- | --- |
| 型号 | 小米 BE3600 2.5G，`xiaomi,rd15` |
| SoC | Qualcomm IPQ5332，4×Cortex-A53，256 MiB DDR |
| 原厂固件 | MIWIFI 1.0.87（OpenWrt 18.06 / Linux 5.4.213 / armv7l） |
| 参考板 | AP-MI04.1-C2 |
| 闪存 | Winbond W25N01KWZEIG，128 MiB SPI-NAND |
| 闪存参数 | page 2048 B，OOB 64 B，erase 128 KiB，SLC |
| 原厂 ECC | 4-bit / 512 B，bus-width 8 |
| NAND 控制器 | QPIC `79b0000.spi` |
| U-Boot | 2016.01，`bootcmd=bootmiwifi`，`bootdelay=15` |
| 串口 | 115200 8N1，**1.8 V**，CH343G → `/dev/ttyACM0` |
| 2.5G PHY | **QCA8081**，MDIO `0x0c`，ID `0x004dd101` |
| 交换芯片 | Motorcomm YT9215S（LAN1-3），MDIO `0x1d` |
| 安装结果 | OpenWrt r0+35705，内核 6.18.39，槽 0 |

### 分区

| mtd | 名称 | 说明 |
| --- | --- | --- |
| 2 | `0:MIBIB` | 分区表，永不写 |
| 13 | `0:APPSBLENV` | U-Boot 环境 |
| 14/15 | `0:APPSBL` / `_1` | U-Boot，永不写 |
| 17 | `0:ART` | Wi-Fi 校准/MAC，永不写 |
| 19 | `rootfs` | 槽 0，42 MiB UBI |
| 20 | `rootfs_1` | 槽 1，42 MiB UBI |
| 22 | `crash` | 测试分区 |

## 3. 问题现象

移植镜像（`openwrt-qualcommbe-ipq53xx-xiaomi_rd15`）RAM 启动后：

- `ubiattach` 失败：`vtbl_check: bad CRC`、`ECC failed: 2293`
- 内核写入页再读回，sha 不一致
- U-Boot 读内核写的页报 `ecc failure`
- 原厂固件一切正常，U-Boot 也能读原厂页

## 4. 方法

| 手段 | 用途 |
| --- | --- |
| 1.8 V 串口 | 全程控制台；U-Boot 中断 |
| TFTP + RAM 引导 | 不写 flash 反复试验 |
| 原厂 DTB 解析（`dtc`） | ECC 参数、PHY 地址、MAC 模式 |
| QPIC 驱动加 `dev_info` | 抓 `exec_op` 的 opcode/地址/长度 |
| U-Boot `nand read` + `crc32` | 交叉验证内核写入的数据 |
| Ghidra（ARM:LE:32:v7） | 原厂 5.4 内核 `qcom_nandc` 分析 |
| 原厂 rootfs 脚本分析 | PHY 选型、port 配置、启动逻辑 |
| `ubiupdatevol` | 手动写 kernel 卷 |

## 5. 排查时间线（关键实验）

### 5.1 写路径

| 实验 | 结果 |
| --- | --- |
| 写命令 `0x6`（OP_PROGRAM_PAGE） | OOB 全 `0xff`，无 ECC |
| 写命令 `0x7`（OP_PAGE_PROGRAM_WITH_ECC） | OOB 出现 ECC，raw 读回 0 差异 |
| U-Boot 读内核写页 | crc 一致 → 写路径标准 |

### 5.2 读路径：排除法

ECC 强度（4/8 位）、OOB 布局、`ECC_PARITY_RS`、`AUTO_STATUS_EN`、
quad 读等方向逐一排除后，问题仍指向"芯片片内 ECC 未被关闭"。
关键证据是写路径：改用 `OP_PAGE_PROGRAM_WITH_ECC (0x7)` 后 OOB 才出现 ECC，
而 U-Boot 能正确读取内核写入的页，说明 flash 上的数据本身是对的。

### 5.3 根因

对比上游 master 的 `spi-qpic-snand.c` 发现：旧驱动处理
`SPINAND_SET_FEATURE` 时**先提交 FLASH_CMD/EXEC 描述符，之后再写
`NAND_FLASH_FEATURES`**。BAM 批量执行时命令读到旧值，导致
spi-nand 核心关闭芯片**片内 ECC** 的操作从未生效。片内 ECC 与主机 ECC
冲突 → 写进去的页 U-Boot 能读、Linux 读不回。

### 5.4 修复

1. `SPINAND_PROGRAM_EXECUTE` 用 `OP_PAGE_PROGRAM_WITH_ECC (0x7)`
2. `SET_FEATURE` 值在 `FLASH_CMD` **之前**写入
3. 不写 `NAND_EBI2_ECC_BUF_CFG`（对齐 `qcom_nandc` qpic v2 行为）

验证：

```
原厂页读取：ECC failed: 0, ECC corrected: 0
自写自读：  0 字节差异
UBI 挂载：  成功，kernel/ubi_rootfs 卷名正确
rootfs：    "hsqs"（squashfs 魔数）
```

### 5.5 为什么是内核 bug

- 上游 master 已采用"先写 feature 再发命令"的顺序，并补了 QUAD 支持
- 只改顺序、其他参数不动，问题立即消失
- 同一颗 flash、同一块板，U-Boot 读写完全正常

结论：OpenWrt 6.18.39 内核树缺少上游修复，属于**驱动 bug + 版本没跟上**。

## 6. 2.5G 网口

### 6.1 两种硬件批次

| 批次 | PHY | MDIO | ID |
| --- | --- | --- | --- |
| A | QCA8081 | `0x0c` | `0x004dd101` |
| B | YT8821 | `0x07` | `0x4f51ea19` |

原厂脚本判断：`[ -d /sys/bus/mdio_bus/devices/90000.mdio:0c ]`。
本机是 **QCA8081**，不能照搬作者机器的 YT8821 配置。

### 6.2 需要的 DTS

```dts
&mdio {
	qca8081: ethernet-phy@c { reg = <0x0c>; };
};

&qcom_ppe {
	ethernet-ports {
		ppe_port1: port@1 {
			reg = <1>;
			phy-mode = "sgmii";
			managed = "in-band-status";      /* 关键 */
			phy-handle = <&qca8081>;
			pcs-handle = <&pcs0_ch0>;
			clocks = <&nsscc NSS_CC_PORT1_MAC_CLK>,
				 <&nsscc NSS_CC_PORT1_RX_CLK>,
				 <&nsscc NSS_CC_PORT1_TX_CLK>;
			clock-names = "mac", "rx", "tx";
			resets = <&nsscc NSS_CC_PORT1_MAC_CLK_ARES>,
				 <&nsscc NSS_CC_PORT1_RX_CLK_ARES>,
				 <&nsscc NSS_CC_PORT1_TX_CLK_ARES>;
			reset-names = "mac", "rx", "tx";
		};
	};
};
```

- 只配 `sgmii`：链路 up 但 **RX 恒为 0**
- 加 `managed = "in-band-status"`：RX/TX 正常
- `2500base-x`：当前 PCS 下链路不稳，不用
- 网线质量差会造成 10M/100M 抖动，别误判

### 6.3 结果

`eth1` 1000Mbps（PC 网口 1G），桥接进 `br-lan`，ping/SSH 正常。
换 2.5G 对端可上 2.5G（未实测）。

## 7. 安装

```sh
sh install-slot0.sh <kernel.itb> <sha> <root.squashfs> <sha>
# 输出 INSTALL_OK
```

### 7.1 sysupgrade 的坑

从 RAM 系统执行 sysupgrade 后，**kernel 卷不会更新**（只更新 rootfs）：

```
dd if=/dev/ubi0_0 bs=4096 count=1200 | grep -a -c eth1   # 0 = 旧内核
```

修复：

```sh
ubiupdatevol /dev/ubi0_0 /tmp/xiaomi_rd15-uImage.itb
sync && reboot
```

### 7.2 回退

U-Boot：

```
setenv flag_boot_rootfs 1
saveenv
reset
```

本机实测该标志未生效（仍启动槽 0），回退建议直接用 TFTP RAM 引导或重装。

## 8. 最终系统

| 项目 | 值 |
| --- | --- |
| LuCI | `http://192.168.31.1`，root/admin |
| 主题 | openwrt2020 |
| DHCP | 192.168.31.150–254，12h |
| 2.5G 口 | eth1，桥接 br-lan，1Gbps |
| Wi-Fi | 驱动正常，AP 未启用 |
| 配置备份 | `backups/config/rd15-openwrt-config-20261115.tar.gz` |

## 9. 复现步骤

```sh
# 构建
cd rd15-build
export PATH=$PWD/../rd15-openwrt/.deps/root/usr/bin:$PATH
make -j8

# 发布到 TFTP 根目录
cp bin/targets/qualcommbe/ipq53xx/*initramfs-uImage.itb \
   ../rd15-openwrt/out/rd15-r35705-20261114/

# RAM 启动
python3 .research/ram_boot.py --port /dev/ttyACM0 --wait \
  --file openwrt-qualcommbe-ipq53xx-xiaomi_rd15-initramfs-uImage.itb

# 验证 NAND
nanddump -l 0x800 /dev/mtd19      # ECC failed: 0
ubiattach -m 19 -d 0              # 成功
```

## 10. 已知限制 / 后续

- 2.5G 速率未实测（PC 只有 1G）
- Wi-Fi AP 未配置
- sysupgrade 脚本不更新 kernel 卷（需修）
- `flag_boot_rootfs` 切换未验证

## 11. 文件清单

| 文件 | 说明 |
| --- | --- |
| `patches/0001-spi-qpic-snand-ecc-program.patch` | 驱动修复（SET_FEATURE 顺序 + 0x7） |
| `patches/0002-ppe-port-init-unwind.patch` | PPE 错误路径 |
| `patches/0003-dts-2p5g-port.patch` | DTS 2.5G 端口 |
| `patches/0004-dts-ubi-bootargs.patch` | 启动参数 |
| `scripts/` | 安装、RAM 引导、串口工具 |
| `images/SHA256SUMS` | 镜像校验值（二进制见 Releases） |
| `docs/RD15-REPRODUCTION-AND-BUG.md` | 复现与 bug 说明 |

## 12. 上游贡献建议

1. **Linux 内核**：`spi-qpic-snand` 的 `SET_FEATURE` 顺序与
   `OP_PAGE_PROGRAM_WITH_ECC` 修复，backport 到 6.18 stable
2. **OpenWrt**：qualcommbe 目标下 RD15 设备支持（DTS + 2.5G 口）
3. **移植仓库**：2.5G 口补丁、docs、安装脚本修复（kernel 卷未更新）
