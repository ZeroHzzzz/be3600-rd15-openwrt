# 镜像

二进制放在 GitHub Releases，这个目录只放校验值。

| 文件 | 大小 | 用途 |
| --- | --- | --- |
| `rd15-initramfs-uImage.itb` | 16 MB | TFTP RAM 引导，用来测试、恢复或安装 |
| `rd15-kernel-uImage.itb` | 4.5 MB | 内核 FIT，写进 kernel 卷 |
| `rd15-root.squashfs` | 12 MB | rootfs，写进 rootfs 卷 |
| `rd15-sysupgrade.bin` | 16 MB | 从正在运行的 OpenWrt 升级 |
| `rd15-factory.ubi` | 17 MB | 完整 UBI 镜像（kernel + rootfs），**不推荐**，见下 |

## 装到槽 0（验证过的路径）

1. 用 `rd15-initramfs-uImage.itb` 做 RAM 引导
2. 在上面执行：

```sh
sh scripts/install-slot0.sh rd15-kernel-uImage.itb <kernel.sha256> \
                          rd15-root.squashfs <squashfs.sha256>
```

输出 `INSTALL_OK` 表示写入并回读校验通过。

## sysupgrade

`rd15-sysupgrade.bin` 可以直接 `sysupgrade`。但从 RAM 系统执行时，kernel 卷
不会更新（只有 rootfs 变了），新内核特性不会生效。确认方法：

```sh
dd if=/dev/ubi0_0 bs=4096 count=1200 | grep -a -c eth1   # 0 表示还是旧内核
```

是旧的话手动写一次：

```sh
ubiupdatevol /dev/ubi0_0 rd15-kernel-uImage.itb
sync && reboot
```

## factory.ubi（不推荐）

`rd15-factory.ubi` 可以用 `ubiformat /dev/mtd19 -f rd15-factory.ubi` 写入并启动，
但实测有两个问题：

- 镜像里的内核 FIT 与 `rd15-kernel-uImage.itb` 不是同一个（sha 不同）
- rootfs 卷名是 `rootfs`，不是系统使用的 `ubi_rootfs`

启动后 PPE 起不来（没有 `eth0`/`eth1`）。恢复时要把卷名改回 `ubi_rootfs`
再重装，或者直接用 `rd15-initramfs` + `install-slot0.sh`。
