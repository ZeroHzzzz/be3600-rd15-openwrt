# 小米 BE3600 2.5G (RD15) OpenWrt 移植

本仓库是 BE3600 2.5G（RD15）OpenWrt 移植镜像。记录安装时遇到的两个问题——
NAND 读写错误和 2.5G 网口不可用——的原因、修复和验证结果，并附带补丁、
脚本和镜像。

## 设备

| 项目 | 规格 |
| --- | --- |
| 型号 | 小米 BE3600 2.5G，型号代号 `RD15`（设备树 `xiaomi,rd15`） |
| SoC | Qualcomm IPQ5332，4×Cortex-A53 |
| 内存 | 256 MiB DDR |
| 闪存 | Winbond W25N01KWZEIG，128 MiB SPI-NAND |
| 闪存参数 | 2048 B page / 64 B OOB / 128 KiB erase，SLC |
| 原厂 ECC | 4-bit / 512 B |
| 2.5G PHY | QCA8081，MDIO 地址 `0x0c`，ID `0x004dd101` |
| 千兆交换芯片 | Motorcomm YT9215S，MDIO `0x1d`，接 LAN1-3 |
| U-Boot | 2016.01，`bootcmd=bootmiwifi` |
| 串口 | 115200 8N1，1.8 V 逻辑 |
| 测试固件 | 原厂 MIWIFI 1.0.87（OpenWrt 18.06，Linux 5.4.213） |
| 移植系统 | OpenWrt r0+35705，Linux 6.18.39 |

## 问题

**NAND 读写错误。** 原厂 UBI 无法挂载（`vtbl_check: bad CRC`、
`ECC failed: 2293`），内核写入的页读回后哈希不一致。同一块闪存上，原厂
固件和 U-Boot 的读写均正常。

**2.5G 网口不可用。** 系统中没有 `eth1`，设备树未描述对应的 PPE 端口。

## 原因

**NAND**：`spi-qpic-snand` 在 `SPINAND_SET_FEATURE` 流程中先提交 BAM 命令
描述符、后写 `NAND_FLASH_FEATURES` 寄存器，命令执行时读到旧值，导致 spi-nand
核心关闭芯片片内 ECC 的操作未生效。片内 ECC 与主机 ECC 同时参与解码，结果
冲突。此外写命令使用 `OP_PROGRAM_PAGE`，QPIC 不为其生成 ECC，需改为
`OP_PAGE_PROGRAM_WITH_ECC`。

**2.5G**：DTS 只描述了千兆交换芯片所用的 PPE `port@2`，缺少 `port@1`。
补齐后还需注意该批次 QCA8081 使用 in-band SGMII 自协商，仅配置
`phy-mode = "sgmii"` 会出现链路建立但 RX 无数据的情况，必须同时设置
`managed = "in-band-status"`。

## 修复

驱动侧修改三处，DTS 增加 2.5G 端口，具体见 `patches/`：

| 位置 | 修改 |
| --- | --- |
| `qcom_spi_send_cmdaddr()` | `SET_FEATURE` 的值在 `FLASH_CMD` 之前写入 |
| `qcom_spi_cmd_mapping()` | 写命令改用 `OP_PAGE_PROGRAM_WITH_ECC (0x7)` |
| 编程路径 | 移除 `NAND_EBI2_ECC_BUF_CFG` 写入 |
| `ipq5332-xiaomi-rd15.dts` | 增加 `port@1`（QCA8081、in-band SGMII、`pcs0_ch0`） |

验证结果：

| 项目 | 结果 |
| --- | --- |
| 原厂页读取 | `ECC failed: 0`，`ECC corrected: 0` |
| 自写自读 | 0 字节差异 |
| UBI 挂载 | 成功，卷 `kernel` / `ubi_rootfs`，rootfs 为 squashfs |
| 2.5G 链路 | 1000 Mbps（对端为 1G 网口），桥接 LAN，ping/SSH 正常 |

## 适用范围

适用于小米 BE3600 2.5G、Winbond W25N01KWZEIG 闪存、QCA8081 2.5G PHY 的批次。

同型号存在其他硬件批次：2.5G PHY 可能是 YT8821（MDIO `0x07`），闪存可能是
GigaDevice GD5F1GM7REYIG（128 B OOB，8-bit ECC）。这些批次的 PHY 地址、ECC
参数和 DTS 均不相同，不能直接套用本仓库配置。其他 IPQ5332 平台可参考排查
思路，但 DTS、时钟、复位需按实际硬件调整。

## 镜像与安装

镜像发布在 [Releases](https://github.com/ZeroHzzzz/be3600-rd15-openwrt/releases)：

| 文件 | 用途 |
| --- | --- |
| `rd15-initramfs-uImage.itb` | TFTP RAM 引导，用于测试、恢复和安装 |
| `rd15-kernel-uImage.itb` | 内核 FIT，写入 kernel 卷 |
| `rd15-root.squashfs` | rootfs，写入 rootfs 卷 |
| `rd15-sysupgrade.bin` | 从运行中的 OpenWrt 升级 |
| `rd15-factory.ubi` | 完整 UBI 镜像，供 `ubiformat` 使用，未实测 |

验证过的安装流程：TFTP 引导 initramfs，执行 `scripts/install-slot0.sh` 将
内核和 rootfs 写入槽 0，输出 `INSTALL_OK` 表示写入并回读校验通过。

从 RAM 系统执行 `sysupgrade` 时 kernel 卷不会更新，需要手动
`ubiupdatevol /dev/ubi0_0 <kernel>`，详见 `images/README.md`。

自行编译时，将 `patches/` 应用到移植作者的 OpenWrt 树，说明见
[patches/README.md](patches/README.md)。

## 文档

- [解锁原厂 SSH](docs/SSH-UNLOCK.md)：刷机前置步骤，含登录与命令注入原理
- [过程和结论](docs/REPORT-BE3600-RD15-JOURNEY.md)
- [设备数据与复现方法](docs/RD15-REPRODUCTION-AND-BUG.md)
- [构建说明](BUILD.md)：源码版本、补丁顺序、配置和产物对应关系

## 许可证

- `patches/`：GPL-2.0（与所修改的内核代码一致）
- `docs/`、`README.md`：CC BY-SA 4.0
- `scripts/`：MIT

详见 [LICENSE](LICENSE)。

## 致谢

- 移植基础：[victorpivotto-cloud/openwrt-xiaomi-be3600-rd15](https://github.com/victorpivotto-cloud/openwrt-xiaomi-be3600-rd15)
- Linux 内核：`drivers/spi/spi-qpic-snand.c`、`drivers/net/phy/qcom/qca808x.c`、`drivers/net/ethernet/qualcomm/ppe`
- SSH 解锁思路参考：[xmir-patcher](https://github.com/openwrt-xiaomi/xmir-patcher)

## 注意事项

刷机有风险。操作前备份 `APPSBL`、`APPSBLENV`、`ART` 分区，并确保串口可用。
