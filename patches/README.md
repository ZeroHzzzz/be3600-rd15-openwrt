# 补丁说明

以下补丁都基于移植作者的 OpenWrt 树（qualcommbe 目标，Linux 6.18.39）。

## 怎么用

补丁不是独立程序，要套在移植作者的树
（`victorpivotto-cloud/openwrt-xiaomi-be3600-rd15`）上：

```sh
# 0003、0004 改 DTS，在 openwrt-tree 根目录打
cd openwrt-tree
patch -p1 < ../patches/0003-dts-2p5g-port.patch
patch -p1 < ../patches/0004-dts-ubi-bootargs.patch

# 0001、0002 是内核补丁，放进 patches-6.18/ 由构建系统自动应用
cp ../patches/0001-spi-qpic-snand-ecc-program.patch \
   ../patches/0002-ppe-port-init-unwind.patch \
   target/linux/qualcommbe/patches-6.18/

# 然后照常 make
```

也可以直接用 Release 里的镜像，不需要打补丁。

## 0001-spi-qpic-snand-ecc-program.patch

改 `drivers/spi/spi-qpic-snand.c`：

- `SPINAND_SET_FEATURE` 的 feature 值改在 `FLASH_CMD` 之前写入
- 写命令用 `OP_PAGE_PROGRAM_WITH_ECC (0x7)`
- 去掉 `NAND_EBI2_ECC_BUF_CFG` 的写入

和上游的关系：Linux 6.18.y 已经有"先写 feature"和去掉 `ECC_BUF_CFG` 的改动，
但写命令仍然是 `0x6`。这里的 `0x7` 是这台机器上验证过的组合；"只同步 6.18.y、
保留 `0x6`"还没有单独测过。

## 0002-ppe-port-init-unwind.patch

`ppe_port.c` 里 `ppe_port_mac_init()` 的失败路径有问题：`edma_port_setup()`
失败时 `i` 会先减到 -1，后面的清理循环再按负数下标访问越界。2.5G 口初始化
失败时会走到这里。

## 0003-dts-2p5g-port.patch

`ipq5332-xiaomi-rd15.dts`：

- `&mdio` 增加 `ethernet-phy@c`（本机的 QCA8081），另加 `ethernet-phy@7`
  供 YT8821 批次探测
- `&qcom_ppe` 增加 `port@1`：`sgmii` + `managed = "in-band-status"` +
  `pcs0_ch0` + PORT1 的时钟和复位

QCA8081 不加 `in-band-status` 会出现链路 up 但 RX 恒为 0。

## 0004-dts-ubi-bootargs.patch

`bootargs` 里加 `ubi.mtd=rootfs`，安装好的系统启动时能自动挂上 ubi0。
只影响启动参数，不动 flash。
