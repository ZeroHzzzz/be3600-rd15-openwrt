# 镜像

二进制作为 Release 附件发布（`v0.2.0`），这个目录只放 `SHA256SUMS`，
Release 里也会附一份同样的校验文件。

| 文件 | 大小 | 用途 |
| --- | --- | --- |
| `rd15-initramfs-uImage.itb` | 16 MB | TFTP RAM 引导，用于测试、恢复和安装 |
| `rd15-kernel-uImage.itb` | 4.5 MB | 内核 FIT，写入 kernel 卷 |
| `rd15-root.squashfs` | 12 MB | rootfs，写入 rootfs 卷 |

## 安装（验证过的路径）

1. `rd15-initramfs-uImage.itb` 做 RAM 引导
2. 在 RAM 系统里执行：

```sh
sh scripts/install-slot0.sh rd15-kernel-uImage.itb <kernel.sha256> \
                          rd15-root.squashfs <squashfs.sha256>
```

输出 `INSTALL_OK` 表示写入并回读校验通过。

## 装完之后

如果重启后自动进了原厂系统，是 U-Boot 的槽位选择被原厂逻辑改回槽 1 了。
在串口 U-Boot 里执行：

```
ubi part nand0,0
ubi read 0x47000000 kernel
bootm 0x47000000#config@mi04.1-c2
```

就会从槽 0 启动 OpenWrt。详见 `BUILD.md` 的「启动槽位」。

## 为什么没有 sysupgrade / factory

- `sysupgrade.bin` 只在从已安装系统执行时才会更新 kernel 卷；从 RAM 执行时
  只更新 rootfs，容易留下"新 rootfs + 旧内核"的不一致状态。
- `factory.ubi` 实测有两个问题：内部 kernel FIT 与 `rd15-kernel-uImage.itb`
  不是同一个，rootfs 卷名是 `rootfs` 而不是 `ubi_rootfs`，启动后 PPE 起不来。

这两条路径都还在验证，暂时不提供。需要的话可以按 `BUILD.md` 自行编译。
