# 小米 BE3600 2.5G (RD15) OpenWrt

小米 BE3600 2.5G（RD15，IPQ5332）刷 OpenWrt 时，移植镜像能启动，但 NAND
读写全错：原厂 UBI 挂不上，写进去的数据读不回来；2.5G 口也不工作。

## 原因和结论

- **NAND**：`spi-qpic-snand` 写 `SET_FEATURE` 的顺序错了，芯片片内 ECC
  没有被关掉，和主机 ECC 冲突；写命令也没用带 ECC 的 `OP_PAGE_PROGRAM_WITH_ECC`
- **2.5G**：DTS 缺 `port@1`，而且这颗 QCA8081 需要 `in-band-status`，
  否则链路 up 但收不到包

改完之后读写正常（`ECC failed: 0`，自写自读一致），UBI 能挂载，2.5G 口在
1000Mbps 下工作（PC 侧只有 1G）。

## 文档

- [过程和结论](docs/REPORT-BE3600-RD15-JOURNEY.md)
- [设备数据和复现方法](docs/RD15-REPRODUCTION-AND-BUG.md)
- [解锁原厂 SSH](docs/SSH-UNLOCK.md)
- [补丁说明](patches/README.md)

## 下载

安装镜像放在 [Releases](https://github.com/ZeroHzzzz/be3600-rd15-openwrt/releases)：

- `rd15-initramfs-uImage.itb`：RAM 引导 / 恢复
- `rd15-kernel-uImage.itb` + `rd15-root.squashfs`：写入槽 0
- `rd15-sysupgrade.bin`：升级用（注意 kernel 卷不会更新，见文档）

校验值在 `images/SHA256SUMS`。脚本依赖 Python 3.8+，先
`pip install -r requirements.txt`。

### 这些文件怎么用

- **只想装上用**：先按 [解锁原厂 SSH](docs/SSH-UNLOCK.md) 打开原厂 SSH；
  下载 `rd15-initramfs-uImage.itb`，用 TFTP 做 RAM 引导；
  然后在跑起来的环境里执行 `scripts/install-slot0.sh`，把
  `rd15-kernel-uImage.itb` 和 `rd15-root.squashfs` 写进槽 0。这是验证过的路径。
- **已经在跑 OpenWrt**：用 `rd15-sysupgrade.bin` 升级。注意从 RAM 系统执行时
  kernel 卷不会更新，需要再手动 `ubiupdatevol` 一次（见文档）。
- **想自己编**：把 `patches/` 套到移植作者的树上再 `make`，见
  [补丁说明](patches/README.md)。

补丁和现成镜像是两回事：镜像可以直接用，补丁是给"想按自己的配置重新构建"
的人用的。

## 适用机器

适用于小米 BE3600 2.5G、Winbond W25N01KWZEIG 闪存、QCA8081 2.5G PHY 的批次。

同型号还有 YT8821 PHY 和 GD5F 闪存（8-bit ECC）的批次，参数不一样，不能直接
套用。其它 IPQ5332 板子可以参考思路，但 DTS、PHY 地址、时钟复位都要按自己的
硬件改。

改机有风险。操作前备份 `APPSBL`、`APPSBLENV`、`ART` 分区，并确保串口可用。
