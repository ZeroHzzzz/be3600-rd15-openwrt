# 小米 BE3600 2.5G (RD15) OpenWrt

这台是小米 BE3600 2.5G（RD15，IPQ5332）。移植版 OpenWrt 能启动，但 NAND
读写是坏的，2.5G 口也用不了。折腾了一圈，两个问题都解决了，过程和产物放在这里。

## 遇到的问题

NAND：原厂 UBI 挂不上（`bad CRC`、`ECC failed 2293`），内核写进去的页读回来
sha 不对。但同一块 flash，原厂固件和 U-Boot 读写都完全正常。

2.5G：系统里没有 `eth1`，设备树里根本没描述这个端口。

## 原因

NAND 是 `spi-qpic-snand` 驱动的问题。处理 `SPINAND_SET_FEATURE` 时，它先把
BAM 命令描述符排进去，之后才写 feature 寄存器，命令执行时读到的还是旧值。
结果 spi-nand 核心关闭芯片**片内 ECC** 的操作没生效，片内 ECC 和主机 ECC
同时解码，互相冲突。另外写命令用的是 `OP_PROGRAM_PAGE`，QPIC 不会为它生成
ECC，需要换成 `OP_PAGE_PROGRAM_WITH_ECC`。

2.5G 是 DTS 只描述了千兆交换芯片的 `port@2`，没有 `port@1`。补上之后还有
一个坑：这颗 QCA8081 要走 in-band SGMII 自协商，只写 `phy-mode = "sgmii"`
会链路 up 但收不到包，必须加 `managed = "in-band-status"`。

## 修复之后

- NAND 读写正常：原厂页 `ECC failed: 0`，自写自读 0 字节差异
- UBI 能挂载，配置能持久化，重启不丢
- 2.5G 口以 1000Mbps 工作（PC 网口只有 1G；换 2.5G 对端应该能更高，没测）
- LAN1-3、Wi-Fi 驱动正常，Wi-Fi AP 还没配

## 文件怎么用

镜像在 [Releases](https://github.com/ZeroHzzzz/be3600-rd15-openwrt/releases)：

| 文件 | 用途 |
| --- | --- |
| `rd15-initramfs-uImage.itb` | TFTP RAM 引导，测试 / 恢复 / 安装 |
| `rd15-kernel-uImage.itb` + `rd15-root.squashfs` | 写进槽 0 |
| `rd15-sysupgrade.bin` | 从运行中的 OpenWrt 升级 |
| `rd15-factory.ubi` | 完整 UBI，`ubiformat` 用，未实测 |

验证过的安装路线是 RAM 引导后跑 `scripts/install-slot0.sh`，把内核和 rootfs
写进槽 0，输出 `INSTALL_OK` 就算成功。sysupgrade 有个坑：从 RAM 系统执行时
kernel 卷不会更新，需要手动 `ubiupdatevol` 一次，细节在 `images/README.md`。

想自己编译的话，用 `patches/` 套到移植作者的树上，补丁说明在
[patches/README.md](patches/README.md)。

## 适用机器

适用于小米 BE3600 2.5G、Winbond W25N01KWZEIG 闪存、QCA8081 2.5G PHY 的批次。

同型号还有 YT8821 PHY（MDIO `0x07`）和 GD5F 闪存（8-bit ECC）的批次，参数
不一样，不能直接套用。其它 IPQ5332 板子可以参考思路，但 DTS、PHY 地址、
时钟复位都得按自己的硬件改。

## 文档

- [解锁原厂 SSH](docs/SSH-UNLOCK.md)：刷机前要先开 SSH，文档里有原理
- [过程和结论](docs/REPORT-BE3600-RD15-JOURNEY.md)
- [设备数据和复现方法](docs/RD15-REPRODUCTION-AND-BUG.md)

改机有风险。操作前备份 `APPSBL`、`APPSBLENV`、`ART` 分区，并确保串口可用。
