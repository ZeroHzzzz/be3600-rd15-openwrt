# 小米 BE3600 2.5G (RD15) OpenWrt 移植记录

把 OpenWrt 装进小米 BE3600 2.5G（代号 RD15，IPQ5332）时，移植镜像能启动，
但 NAND 读写是坏的：原厂 UBI 挂不上、写进去的数据读不回来、2.5G 网口也不工作。
这个仓库记录了问题的现象、根因、修复方式，以及适用于哪些机器。

## 遇到的问题

**1. NAND 读写全错**

- `ubiattach` 失败：`vtbl_check: bad CRC`、`ECC failed: 2293`
- 内核写入页再读回，内容不一致
- 但同一块 flash，原厂固件和 U-Boot 读写都完全正常

**2. 2.5G 网口不可用**

- 设备树里没有对应的 PPE 端口，系统里看不到 `eth1`

## 原因

### NAND：驱动写 feature 寄存器的时序错了

`spi-qpic-snand` 驱动处理 `SPINAND_SET_FEATURE` 时，先把 BAM 命令描述符
提交给控制器，之后才把 feature 值写进 `NAND_FLASH_FEATURES` 寄存器。
命令执行时读到的是旧值，导致 spi-nand 核心**关闭芯片片内 ECC 的操作从未生效**。

片内 ECC 和主机 ECC 同时工作，解码结果互相冲突——这就是"写进去的页 U-Boot
能读、Linux 自己读不回来"的原因。

另外该驱动用 `OP_PROGRAM_PAGE` 提交写命令，QPIC 不会为它生成 ECC
（OOB 全是 `0xff`），需要改成 `OP_PAGE_PROGRAM_WITH_ECC`。

### 2.5G：DTS 缺端口，且 QCA8081 需要 in-band 自协商

- DTS 里只描述了 PPE `port@2`（千兆交换芯片），没有 `port@1`
- 这款机器有两个 PHY 批次：**QCA8081（MDIO 0x0c）** 和 YT8821（MDIO 0x07）
- QCA8081 走的是 in-band SGMII 自协商；只写 `phy-mode = "sgmii"`
  会出现"链路 up 但收不到包"（RX 恒为 0）

## 结论与修复

| 问题 | 修复 |
| --- | --- |
| 片内 ECC 未关闭 | `SET_FEATURE` 的值在 `FLASH_CMD` 之前写入 |
| 写入无 ECC | 写命令改用 `OP_PAGE_PROGRAM_WITH_ECC (0x7)` |
| 驱动写 `ECC_BUF_CFG` | 移除，对齐原厂 `qcom_nandc` 的 qpic v2 行为 |
| 2.5G 无端口 | DTS 增加 `port@1`（QCA8081 + `pcs0_ch0` + PORT1 时钟/复位） |
| 2.5G RX=0 | `port@1` 加 `managed = "in-band-status"` |

修复后验证结果：

- 原厂页读取：`ECC failed: 0`、`ECC corrected: 0`
- 自写自读：0 字节差异
- UBI 自动挂载，`kernel` / `ubi_rootfs` 卷名正确，squashfs 魔数正常
- `eth1` 1000Mbps（PC 侧 1G），桥接进 LAN，ping/SSH 正常

## 适用机器

**适用：**

- 小米 BE3600 2.5G，型号 `xiaomi,rd15`（IPQ5332，AP-MI04.1-C2 参考板）
- 闪存为 **Winbond W25N01KWZEIG**（2048 B page / 64 B OOB / 4-bit ECC per 512 B）
- 2.5G PHY 为 **QCA8081**（MDIO `0x0c`，ID `0x004dd101`）

**需自行核对：**

- 同型号不同批次的 2.5G PHY 可能是 **YT8821**（MDIO `0x07`）。
  本仓库的 DTS 只对 QCA8081 做了验证；YT8821 需要改 `phy-handle` 并重新测试。
- 闪存批次也可能是 GigaDevice GD5F1GM7REYIG（128 B OOB，8-bit ECC）。
  此时 `nand-ecc-strength` 等参数必须按实际芯片调整，不能直接套用。
- 其它 IPQ5332 板子可以参考思路，但 DTS、PHY 地址、时钟/复位都要按自己的硬件改。

## 仓库内容

```
docs/     问题现象、根因分析、复现步骤
patches/  内核驱动修复、PPE 补丁、DTS 补丁
scripts/  install-slot0.sh、ram_boot.py、serial_console.py
images/   镜像校验值（二进制在 Releases）
```

## 复现步骤

```sh
# 1. 构建移植作者的 OpenWrt 树
cd rd15-build
export PATH=$PWD/../rd15-openwrt/.deps/root/usr/bin:$PATH
make -j8

# 2. 应用补丁（patches/0001 ~ 0004）

# 3. RAM 引导测试，不写 flash
python3 scripts/ram_boot.py --port /dev/ttyACM0 --wait \
  --file openwrt-qualcommbe-ipq53xx-xiaomi_rd15-initramfs-uImage.itb

# 4. 安装到槽 0
sh scripts/install-slot0.sh <kernel.itb> <sha256> <root.squashfs> <sha256>
```

验证 NAND：

```sh
nanddump -l 0x800 /dev/mtd19   # 期望 ECC failed: 0
ubiattach -m 19 -d 0           # 期望成功
```

## 安装时的一个坑

从 RAM 系统执行 `sysupgrade` 后，**kernel 卷不会更新**（只更新了 rootfs）。
如果发现新内核特性没生效，手动写一次：

```sh
ubiupdatevol /dev/ubi0_0 xiaomi_rd15-uImage.itb
sync && reboot
```

## 致谢

- 移植基础：[victorpivotto-cloud/openwrt-xiaomi-be3600-rd15](https://github.com/victorpivotto-cloud/openwrt-xiaomi-be3600-rd15)
- 驱动：Linux `drivers/spi/spi-qpic-snand.c`
- PHY：Linux `drivers/net/phy/qcom/qca808x.c`

## 免责声明

改机有风险。操作前请备份 `APPSBL`、`APPSBLENV`、`ART` 分区，并确保串口可用。
本资料只记录实测过程，不构成任何保证。
