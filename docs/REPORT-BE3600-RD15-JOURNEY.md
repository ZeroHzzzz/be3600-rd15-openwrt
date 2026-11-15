# 小米 BE3600 2.5G (RD15) 刷 OpenWrt 记录

这台小米 BE3600 2.5G（代号 RD15，IPQ5332）刷移植版 OpenWrt 时，镜像能启动，
但 NAND 读写全错：原厂 UBI 挂不上，内核写进去的数据读不回来；2.5G 网口也不工作。
下面是排查过程和最后的结论。

## 机器和固件

| 项目 | 实测 |
| --- | --- |
| 型号 | 小米 BE3600 2.5G（`xiaomi,rd15`） |
| SoC | Qualcomm IPQ5332，4×Cortex-A53，256 MiB DDR |
| 原厂固件 | MIWIFI 1.0.87，OpenWrt 18.06，内核 5.4.213 |
| 闪存 | Winbond W25N01KWZEIG，128 MiB，page 2048 B / OOB 64 B |
| 原厂 ECC | 4-bit / 512 B |
| U-Boot | 2016.01，`bootcmd=bootmiwifi` |
| 串口 | 115200 8N1，1.8 V |
| 2.5G PHY | QCA8081，MDIO `0x0c` |
| 千兆交换 | Motorcomm YT9215S，MDIO `0x1d` |

## NAND 读写

### 现象

`ubiattach` 报 `vtbl_check: bad CRC`、`ECC failed: 2293`。内核写入一页再读回，
sha 对不上；U-Boot 读内核写的那页也报 `ecc failure`。但同一块 flash，原厂固件
和 U-Boot 自己读写都完全正常。

### 排查

一开始怀疑 ECC 参数：对照原厂 DTB 确认是 4-bit / 512 B、bus-width 8，
和驱动一致；OOB 里 ECC 的分布也和 U-Boot 对得上。又试了 ECC 强度、OOB 布局、
`ECC_PARITY_RS`、`AUTO_STATUS_EN`、quad 读这些方向，都没有改善。

转折点在写路径：驱动原来用 `OP_PROGRAM_PAGE` 提交写命令，QPIC 不会为它生成
ECC，写出来的页 OOB 全是 `0xff`。改成 `OP_PAGE_PROGRAM_WITH_ECC (0x7)` 之后
OOB 里才有 ECC，而且 U-Boot 能正确读出内核写入的页——这说明 flash 上的数据
本身是对的，问题在读的时候。

### 根因

`spi-qpic-snand` 处理 `SPINAND_SET_FEATURE` 时，先把 FLASH_CMD/EXEC 描述符
排进 BAM 队列，之后才把 feature 值写进 `NAND_FLASH_FEATURES` 寄存器。BAM 是
批量执行的，命令跑的时候读到的还是旧值，于是 spi-nand 核心关闭**芯片片内 ECC**
的操作没有真正生效。

片内 ECC 和主机 ECC 同时参与解码，结果互相冲突。这就是"写进去的页 U-Boot 能读、
Linux 自己读不回来"的原因。

上游 master 已经改成"先写 feature 再发命令"，并且不再写 `ECC_BUF_CFG`。
OpenWrt 6.18.39 这棵树里的驱动还是旧实现，属于缺少上游修复，不是硬件问题。

### 修复

驱动改三处：

1. `SPINAND_PROGRAM_EXECUTE` 用 `OP_PAGE_PROGRAM_WITH_ECC (0x7)`
2. `SET_FEATURE` 的值在 `FLASH_CMD` 之前写入
3. 去掉 `NAND_EBI2_ECC_BUF_CFG` 的写入，和原厂 `qcom_nandc` 的 qpic v2 行为一致

补丁在 `patches/0001-spi-qpic-snand-ecc-program.patch`。

验证结果：

```
原厂页读取：ECC failed: 0, ECC corrected: 0
自写自读：  0 字节差异
UBI 挂载：  成功，卷名 kernel / ubi_rootfs
rootfs：    hsqs（squashfs 魔数）
```

## 2.5G 网口

这个型号的 2.5G PHY 有两个批次：移植作者那台是 YT8821（MDIO `0x07`），
这台是 QCA8081（MDIO `0x0c`，ID `0x004dd101`）。原厂固件就是靠
`90000.mdio:0c` 是否存在来判断的，所以不能照搬别人 DTS 里的 PHY 地址。

原版 DTS 只描述了 PPE `port@2`（接千兆交换芯片），没有 `port@1`，所以系统里
根本没有 `eth1`。补上 `port@1` 之后还有一点：QCA8081 走 in-band SGMII 自协商，
只写 `phy-mode = "sgmii"` 会出现链路 up、但收不到包（RX 一直是 0）。

可用的配置是：

```dts
&mdio {
	qca8081: ethernet-phy@c { reg = <0x0c>; };
};

&qcom_ppe {
	ethernet-ports {
		ppe_port1: port@1 {
			reg = <1>;
			phy-mode = "sgmii";
			managed = "in-band-status";
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

中间试过 `2500base-x`，在这块 PCS 上链路会反复起来又掉，没有采用。另外网线
接触不良时也会出现 10M/100M 来回跳，很容易误判成驱动问题。

改完之后 `eth1` 以 1000Mbps 工作（PC 网口只有 1G），桥接进 `br-lan`，
ping 和 SSH 都正常。

## 安装

用 `install-slot0.sh` 把内核和 rootfs 写进槽 0，输出 `INSTALL_OK` 就表示
写入并回读校验通过。

有个坑：从 RAM 系统执行 `sysupgrade` 之后，kernel 卷不会更新（只更新了
rootfs）。如果发现新加的内核特性没生效，先确认一下：

```sh
dd if=/dev/ubi0_0 bs=4096 count=1200 | grep -a -c eth1   # 0 = 旧内核
```

确实是旧的，就手动写一次：

```sh
ubiupdatevol /dev/ubi0_0 xiaomi_rd15-uImage.itb
sync && reboot
```

回退方面，槽 1 的原厂固件一直没动过。U-Boot 里 `setenv flag_boot_rootfs 1`
的切换在这台机器上没成功（仍然启动槽 0），所以回退还是用 TFTP 引导 RAM
镜像，或者重新安装。

## 装好之后

槽 0 跑 OpenWrt r0+35705（6.18.39），LuCI 在 `http://192.168.31.1`，
DHCP 池是 192.168.31.150–254，2.5G 口桥接进 LAN。Wi-Fi 驱动正常，
AP 暂时没开。
