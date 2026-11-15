# 镜像

二进制在 GitHub Releases，这个目录只放校验值。

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

## 为什么没有 sysupgrade / factory

- `sysupgrade.bin` 只在从已安装系统执行时才会更新 kernel 卷；从 RAM 执行时
  只更新 rootfs，容易留下"新 rootfs + 旧内核"的不一致状态。
- `factory.ubi` 实测有两个问题：内部 kernel FIT 与 `rd15-kernel-uImage.itb`
  不是同一个，rootfs 卷名是 `rootfs` 而不是 `ubi_rootfs`，启动后 PPE 起不来。

这两条路径都还在验证，暂时不提供。需要的话可以按 `BUILD.md` 自行编译。
