# 小米 BE3600 2.5G (RD15) OpenWrt 移植与排障资料

> 本仓库记录一台 **小米 BE3600 2.5G（RD15，IPQ5332）** 从"NAND 读写全坏、
> OpenWrt 装不进去"到"稳定运行 + 2.5G 网口可用"的完整过程，并提供可复现的
> 补丁、脚本与镜像校验值。
>
> 硬件实测：Winbond W25N01KWZEIG（64 B OOB，4-bit/512 ECC）、
> QCA8081 2.5G PHY（MDIO `0x0c`）、YT9215S 千兆交换芯片。

## 状态

| 项目 | 状态 |
| --- | --- |
| NAND 读写 | ✅ 已修复（`ECC failed: 0`，自写自读一致） |
| UBI 挂载 / 持久化 | ✅ 正常 |
| 2.5G 网口（eth1） | ✅ 可用（实测 1Gbps，PC 侧 1G 上限） |
| LAN1-3 | ✅ 正常 |
| LuCI | ✅ `http://192.168.31.1` |
| Wi-Fi AP | 驱动正常，未启用 |

## 仓库结构

```
docs/     全过程记录、复现指南、逐条实验证据
patches/  内核驱动修复、PPE 补丁、DTS 补丁
scripts/  install-slot0.sh、ram_boot.py、serial_console.py
images/   镜像校验值（二进制走 Releases）
```

## 核心结论

### 1. NAND 读写的根因

`spi-qpic-snand` 处理 `SPINAND_SET_FEATURE` 时**先提交 BAM 命令描述符，
之后才写 `NAND_FLASH_FEATURES`**。命令执行时读到旧值，导致芯片**片内 ECC**
从未被关闭，与主机 ECC 冲突：写进去的页 U-Boot 能读、Linux 读不回。

修复：

1. `SET_FEATURE` 的 feature 值在 `FLASH_CMD` 之前写入
2. `SPINAND_PROGRAM_EXECUTE` 使用 `OP_PAGE_PROGRAM_WITH_ECC (0x7)`
3. 不写 `NAND_EBI2_ECC_BUF_CFG`（对齐 `qcom_nandc` qpic v2）

> 注意：Linux 6.18.y 稳定版已包含第 1 项修复；本仓库的补丁是"我们验证过的
> 版本"。详见 `patches/README.md`。

### 2. 2.5G 网口

本机是 **QCA8081（MDIO 0x0c）** 批次，不是 YT8821（0x07）。需要：

- DTS `port@1`：`phy-mode = "sgmii"` + **`managed = "in-band-status"`**
- `pcs-handle = <&pcs0_ch0>` + PORT1 时钟/复位
- 只配 `sgmii` 会出现"链路 up 但 RX=0"

### 3. 安装注意

从 RAM 系统 `sysupgrade` 后 **kernel 卷不会更新**，需手动：

```sh
ubiupdatevol /dev/ubi0_0 xiaomi_rd15-uImage.itb
```

## 快速开始

```sh
# 1. 拿到移植作者的 OpenWrt 树并构建（见 docs/）
# 2. 应用本仓库补丁
#    patches/0001-*  内核驱动
#    patches/0002-*  PPE 错误路径
#    patches/0003-*  DTS 2.5G 端口
# 3. RAM 引导测试（不写 flash）
python3 scripts/ram_boot.py --port /dev/ttyACM0 --wait \
  --file openwrt-qualcommbe-ipq53xx-xiaomi_rd15-initramfs-uImage.itb
# 4. 安装到槽 0
sh scripts/install-slot0.sh <kernel.itb> <sha256> <root.squashfs> <sha256>
```

## 文档

- [全过程记录](docs/REPORT-BE3600-RD15-JOURNEY.md)
- [复现与 bug 说明](docs/RD15-REPRODUCTION-AND-BUG.md)
- [逐条实验证据](docs/RE-FINDINGS-20261114.md)
- [阶段结论](docs/SESSION-RESULT-20261114.md)

## 上游与致谢

- 移植基础：[victorpivotto-cloud/openwrt-xiaomi-be3600-rd15](https://github.com/victorpivotto-cloud/openwrt-xiaomi-be3600-rd15)
- 驱动：Linux `drivers/spi/spi-qpic-snand.c`
- PHY：Linux `drivers/net/phy/qcom/qca808x.c`

## 许可

- 补丁：GPL-2.0（与内核一致）
- 文档：CC BY-SA 4.0

## 免责声明

改机有风险：写错分区可能变砖。本资料仅记录实测过程，不构成保证。
操作前请备份 `APPSBLENV`、`APPSBL`、`ART` 分区，并确保串口可用。
