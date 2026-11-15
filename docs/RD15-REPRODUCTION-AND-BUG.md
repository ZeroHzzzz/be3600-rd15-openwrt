# RD15 设备信息与排障记录

这台机器是小米 BE3600 2.5G（RD15），刷 OpenWrt 时先后遇到 NAND 读写错误和
2.5G 网口不可用。下面是我们查到的硬件数据、排查方法和最终结论。

文中 MAC 地址已做脱敏。`ART` 分区是每台机器独有的校准数据，不要复制或外传。

## 设备信息

| 项目 | 实测值 | 获取方式 |
| --- | --- | --- |
| 型号 | 小米 BE3600 2.5G，代号 RD15 | `cat /tmp/sysinfo/board_name` → `xiaomi,rd15` |
| SoC | Qualcomm IPQ5332，4×Cortex-A53，256 MiB DDR | 原厂 `dmesg`、`bdinfo` |
| 原厂固件 | MIWIFI 1.0.87（OpenWrt 18.06，内核 5.4.213，armv7l） | `cat /etc/openwrt_release` |
| 参考板 | AP-MI04.1-C2 | 原厂 `/tmp/sysinfo/board_name` |
| 闪存 | Winbond W25N01KWZEIG，128 MiB SPI-NAND | `dmesg`：Manufacturer ID `0xef`，Chip ID `0xbe` |
| 闪存参数 | page 2048 B，OOB 64 B，erase 128 KiB，SLC | `dmesg` / U-Boot `nand info` |
| 原厂 ECC | 4-bit / 512 B，bus-width 8 | 原厂 DTB `/soc/nand@79b0000/nandcs@0` |
| NAND 控制器 | QPIC `79b0000.spi` | `dmesg` |
| U-Boot | 2016.01，`bootcmd=bootmiwifi`，`ethprime=eth1` | 串口 `version`、`printenv` |
| 串口 | 115200 8N1，1.8 V 逻辑，CH343G → `/dev/ttyACM0` | 实测 |
| 2.5G PHY | QCA8081，MDIO `0x0c`，ID `0x004dd101` | `/sys/class/mdio_bus/.../phy_id` |
| 交换芯片 | Motorcomm YT9215S（LAN1-3），MDIO `0x1d` | `dmesg` |
| MAC | `90:fb:5d:1c:xx:xx`（脱敏） | 原厂 `nvram`、`ip link` |

### 分区

| mtd | 名称 | 说明 |
| --- | --- | --- |
| 2 | `0:MIBIB` | 分区表，不要写 |
| 13 | `0:APPSBLENV` | U-Boot 环境（含槽位标志） |
| 14/15 | `0:APPSBL` / `_1` | U-Boot，不要写 |
| 17 | `0:ART` | Wi-Fi 校准和 MAC，不要写、不要分享 |
| 19 | `rootfs` | 槽 0，42 MiB，UBI |
| 20 | `rootfs_1` | 槽 1，42 MiB，UBI |
| 22 | `crash` | 测试用，实验中在这上面做过读写 |

### 2.5G PHY 有两个批次

- 移植作者的机器：YT8821，MDIO `0x07`，ID `0x4f51ea19`
- 这台机器：QCA8081，MDIO `0x0c`，ID `0x004dd101`

原厂固件靠这个判断用哪个驱动：

```sh
PHY_TYPE=$( [ -d /sys/bus/mdio_bus/devices/90000.mdio:0c ] && echo "qca8081" || echo "yt8821")
```

同型号不同批次 PHY 不一样，DTS 里的 PHY 地址不能照搬别人的。

## 排查方法

1. **串口**：1.8 V USB-TTL，115200 8N1，只接 GND、路由 TX、路由 RX，不接 VCC。
   原厂默认 `uart_en=0`，先通过 SSH 设置：
   `nvram set uart_en=1; nvram set boot_wait=on; nvram set bootdelay=15; nvram commit`。
2. **TFTP + RAM 引导**：PC 静态 `192.168.31.100/24`，用 dnsmasq 提供 TFTP。
   U-Boot 里 `tftpboot 0x47000000 <initramfs.itb>`，再
   `bootm 0x47000000#config@mi04.1-c2`。网线要接 LAN 口，U-Boot 的 eth0 在交换机上。
3. **原厂 DTB**：从原厂固件的 FIT 里取出 `fdt@1`，用 `dtc -I dtb -O dts` 查看。
4. **MDIO 探测**：在 `&mdio` 下加 `ethernet-phy@<addr>` 节点，RAM 启动后读
   `/sys/class/mdio_bus/<bus>/<bus>:<addr>/phy_id` 和 `driver` 链接；
   没有响应的地址会打印 `MDIO device at address N is missing`。
5. **QPIC 命令追踪**：在驱动里临时加 `dev_info`，打印 `qcom_spi_exec_op` 的
   opcode、地址、长度，以及 `qcom_spi_program_ecc` 的 cfg0/cfg1/ecc_bch_cfg。
   注意计数器会被启动阶段的 BBM 扫描用完，最好开机后清空 dmesg 再复现。
6. **和 U-Boot 对照**：U-Boot 里 `nand read` + `crc32` 读内核写的页；
   再反过来用 U-Boot 写一页、Linux 读 OOB，交叉验证 ECC 布局。
7. **原厂内核**：UBI 的 `kernel` 卷是 LZMA 压缩的裸 ARM Image，可以用 Ghidra
   （ARM:LE:32:v7，base `0x40008000`）分析。原厂没开 `CONFIG_KALLSYMS`，
   符号恢复比较麻烦。

## NAND：问题、根因、修复

### 现象

- `ubiattach` 失败：`vtbl_check: bad CRC`、`ECC failed: 2293`
- 内核写入页再读回，sha 不一致
- 同一块 flash，原厂固件和 U-Boot 读写都正常

### 根因

`spi-qpic-snand` 处理 `SPINAND_SET_FEATURE` 时，先把 FLASH_CMD/EXEC 描述符
排进 BAM，之后才把 feature 值写进 `NAND_FLASH_FEATURES`。命令执行时用的是
旧值，spi-nand 核心关闭**芯片片内 ECC** 的操作没有真正生效。

片内 ECC 和主机 ECC 同时参与解码，结果互相冲突，于是写进去的页 U-Boot 能读、
Linux 自己读不回来。

### 为什么判断是驱动 bug

- 上游 master 已经改成"先写 feature 再发命令"；
- 只调换这一步的顺序，其他参数不动，读写立刻正常；
- 同一块板、同一颗 flash，U-Boot 的读写完全正常。

OpenWrt 6.18.39 这棵树里的驱动还是旧实现，属于缺少上游修复，不是硬件问题。

### 改动

1. `SPINAND_PROGRAM_EXECUTE` 用 `OP_PAGE_PROGRAM_WITH_ECC (0x7)`，
   否则 QPIC 不生成 ECC，OOB 全是 `0xff`
2. `SET_FEATURE` 的值在 `FLASH_CMD` 之前写入
3. 不写 `NAND_EBI2_ECC_BUF_CFG`，和原厂 `qcom_nandc` 的 qpic v2 行为一致

补丁在 `patches/0001-spi-qpic-snand-ecc-program.patch`。

### 验证

- 原厂页读取：`ECC failed: 0`、`ECC corrected: 0`
- 自写自读：0 字节差异
- UBI 挂载成功，卷名 `kernel` / `ubi_rootfs`，rootfs 魔数 `hsqs`
- U-Boot 读内核写的页：`2048 bytes read: OK`，crc 一致

## 2.5G 网口

### DTS 配置

```dts
&mdio {
	yt8821: ethernet-phy@7 { reg = <7>; };      /* 另一批次，探测用 */
	qca8081: ethernet-phy@c { reg = <0x0c>; };  /* 本机 */
};

&qcom_ppe {
	ethernet-ports {
		ppe_port1: port@1 {
			reg = <1>;
			phy-mode = "sgmii";
			managed = "in-band-status";   /* 关键 */
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

几个实际踩到的点：

- 只写 `phy-mode = "sgmii"` 时链路能 up，但 RX 一直是 0，加
  `managed = "in-band-status"` 才正常收发
- `2500base-x` 在这块 PCS 上链路不稳，没有采用
- 网线接触不良会表现为 10M/100M 来回跳，容易误判成驱动问题

### 内核 FIT 要单独更新

从 RAM 系统执行 `sysupgrade` 后，kernel 卷不会更新，启动后没有 `port@1`
（也就没有 `eth1`）。需要手动写一次：

```sh
ubiupdatevol /dev/ubi0_0 xiaomi_rd15-uImage.itb
sync && reboot
```

确认内核卷里有新内容：

```sh
dd if=/dev/ubi0_0 bs=4096 count=1200 | grep -a -c eth1   # 应为 1
```

## 复现步骤

```sh
# 构建
cd rd15-build
export PATH=$PWD/../rd15-openwrt/.deps/root/usr/bin:$PATH
make -j8

# 放进 TFTP 根目录
cp bin/targets/qualcommbe/ipq53xx/*initramfs-uImage.itb \
   ../rd15-openwrt/out/rd15-r35705-20261114/

# RAM 启动（RAM 系统里 reboot 不生效，用 sysrq）
ssh root@192.168.31.1 'echo b > /proc/sysrq-trigger'
python3 scripts/ram_boot.py --port /dev/ttyACM0 --wait \
  --file openwrt-qualcommbe-ipq53xx-xiaomi_rd15-initramfs-uImage.itb

# 验证 NAND
nanddump -l 0x800 /dev/mtd19      # 期望 ECC failed: 0
ubiattach -m 19 -d 0              # 期望成功

# 验证自写自读
flash_erase /dev/mtd22 0 1
dd if=/dev/zero bs=2048 count=1 | tr '\000' '\252' > /tmp/p
dd if=/tmp/p of=/dev/mtd22 bs=2048 count=1
dd if=/dev/mtd22 bs=2048 count=1 | cmp - /tmp/p && echo OK
```

安装到槽 0：

```sh
sh scripts/install-slot0.sh <kernel.itb> <kernel.sha256> \
                            <root.squashfs> <squashfs.sha256>
```

输出 `INSTALL_OK` 表示写入并回读校验通过。

## 现状

- 槽 0 跑 OpenWrt（r0+35705，6.18.39），NAND 修复已包含
- 槽 1 原厂固件保持未动；`flag_boot_rootfs` 的切换在这台机器上没验证成功
- 2.5G 口 `eth1` 工作，1000Mbps（PC 侧只有 1G），桥接进 LAN
- Wi-Fi 驱动正常，AP 尚未启用
