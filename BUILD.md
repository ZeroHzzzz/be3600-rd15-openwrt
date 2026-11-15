# 构建说明

Release 里的镜像就是按下面的步骤构建出来的。

## 源码

- 移植作者的 OpenWrt 树：
  `victorpivotto-cloud/openwrt-xiaomi-be3600-rd15` @ `d9c8a55a`
- OpenWrt 基础提交：`e46ea77ba4f431c72301c3d07220e454450b3070`
- 内核：6.18.39
- 目标：`qualcommbe` / `ipq53xx` / `xiaomi_rd15`

## 应用补丁

```sh
cd openwrt-tree

# DTS 补丁（相对 openwrt-tree 根目录）
patch -p1 < ../patches/0003-dts-2p5g-port.patch
patch -p1 < ../patches/0004-dts-ubi-bootargs.patch

# 内核补丁（放进 patches-6.18/，构建时按文件名顺序应用）
cp ../patches/0001-spi-qpic-snand-ecc-program.patch \
   ../patches/0002-ppe-port-init-unwind.patch \
   ../patches/0005-winbond-w25n01kw.patch \
   target/linux/qualcommbe/patches-6.18/
```

补丁编号和实际应用顺序无关，构建系统按文件名排序。

## 构建配置

在 `.config` 里追加 `configs/luci-and-phy.config` 的内容（LuCI、主题、
`cgi-io`；`CONFIG_MOTORCOMM_PHY` 只有 YT8821 批次才需要）。

LuCI 的 feed 需要先拉下来：

```sh
./scripts/feeds update luci packages
./scripts/feeds install -a -p luci
./scripts/feeds install -p packages cgi-io
```

默认主题用构建树里的 `files/` 目录：

```sh
mkdir -p files/etc/uci-defaults
cp ../files/etc/uci-defaults/90-luci-theme files/etc/uci-defaults/
```

## 编译

```sh
export PATH=$PWD/../rd15-openwrt/.deps/root/usr/bin:$PATH
make -j8
```

产物在 `bin/targets/qualcommbe/ipq53xx/`。

## 镜像

Release 里的文件名和构建产物对应关系：

| Release 文件 | 构建产物 |
| --- | --- |
| `rd15-initramfs-uImage.itb` | `openwrt-qualcommbe-ipq53xx-xiaomi_rd15-initramfs-uImage.itb` |
| `rd15-kernel-uImage.itb` | `build_dir/.../qualcommbe_ipq53xx/xiaomi_rd15-uImage.itb` |
| `rd15-root.squashfs` | `build_dir/.../qualcommbe_ipq53xx/root.squashfs` |


校验值见 `images/SHA256SUMS`。Release 只发布上面三个验证过的文件；
`sysupgrade` 和 `factory.ubi` 还在验证，暂不提供。

## 关于调试输出

发布镜像里没有调试打印。可以用下面的方法复核（内核是压缩的，不能直接 grep）：

```sh
# 在构建树里检查驱动源码
grep -n 'QPIC EXECSEEN\|QPIC PROBE MARKER\|QPIC SETFEATURE' \
    build_dir/*/linux-*/drivers/spi/spi-qpic-snand.c   # 应为空

# 或检查未压缩的内核
grep -a -c 'QPIC EXECSEEN' build_dir/*/linux-*/Image    # 应为 0
```

## 实测结论

- `OP_PAGE_PROGRAM_WITH_ECC (0x7)` 是必需的。用 `0x6` 编出的内核能加载
  squashfs，但 NAND 的 NVMEM（MAC）读失败、PPE 探测报
  `phylink -EINVAL` 并崩溃，系统进不了正常状态。
- `sysupgrade` 从**已安装系统**执行时，kernel 卷会被更新（实测写入 0x6 内核后
  重启确实跑了新内核）。从 **RAM 系统**执行时 kernel 卷不更新，只更新 rootfs，
  需要手动 `ubiupdatevol`。
- `rd15-factory.ubi` 可以用 `ubiformat` 写入并启动，但镜像里的内核 FIT 与
  `rd15-kernel-uImage.itb` 不是同一个（sha 不同），且 rootfs 卷名是 `rootfs`
  而不是 `ubi_rootfs`，启动后 PPE 起不来。**不要用 factory.ubi**，
  用 `rd15-initramfs` + `install-slot0.sh`。
- U-Boot 的槽位选择由 `flag_boot_rootfs`、`flag_last_success`、`bootargs`
  共同决定；原厂固件启动时会把这些变量改成槽 1。需要回到槽 0 时，在
  OpenWrt/RAM 里用 `fw_setenv`（`/etc/fw_env.config` 写
  `/dev/mtd13 0x0 0x10000 0x10000`）改回，或 U-Boot 里 `setenv`。

## 启动槽位（重要）

原厂 U-Boot 的 `bootmiwifi` 用 `miwifi_bootargs` 决定从哪个槽启动，而不是
`bootargs`。原厂固件启动时会把 `miwifi_bootargs`、`flag_boot_rootfs` 等改回
槽 1（`rootfs_1`），所以装好 OpenWrt 后如果自动启动进了原厂系统，需要手动引导。

在 U-Boot 里（串口，`bootdelay=15`）执行：

```
ubi part nand0,0
ubi read 0x47000000 kernel
bootm 0x47000000#config@mi04.1-c2
```

会直接从槽 0 的 UBI `kernel` 卷读出 FIT 并启动 OpenWrt。实测这条路径稳定。
把这三条设成 `bootcmd` 并 `saveenv` 有时会被原厂逻辑覆盖，所以建议保留串口。
