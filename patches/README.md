# 补丁说明

所有补丁相对 **移植作者的 openwrt 树（qualcommbe / Linux 6.18.39）**。

## 0001-spi-qpic-snand-ecc-program.patch

`drivers/spi/spi-qpic-snand.c`：

1. `SPINAND_SET_FEATURE`：feature 值在 `FLASH_CMD` 之前写入
   `NAND_FLASH_FEATURES`（根因修复）
2. `SPINAND_PROGRAM_EXECUTE`：`OP_PROGRAM_PAGE` → `OP_PAGE_PROGRAM_WITH_ECC (0x7)`
3. 移除 3 处 `NAND_EBI2_ECC_BUF_CFG` 写入

### 与上游的关系（重要）

- Linux **6.18.y 稳定版已包含第 1 项修复**，且不写 `ECC_BUF_CFG`；
  但它仍使用 `OP_PROGRAM_PAGE (0x6)`。
- 本补丁中的 `0x7` 是我们在这台机器上验证可用的组合；
  **尚未单独验证**"仅同步 6.18.y + 保留 0x6"是否也正常。
- 因此向上游提交时，建议：
  1. 优先让目标树同步 6.18.y 的驱动改动（第 1、3 项）
  2. 若 0x6 仍不生成 ECC，再把 0x7 作为独立修复提交，
     并附上 QPIC 寄存器/cfg1 的证据

## 0002-ppe-port-init-unwind.patch

`drivers/net/ethernet/qualcomm/ppe/ppe_port.c`：

修复 `ppe_port_mac_init()` 失败路径的越界访问（`i--` 到 -1）。
2.5G 口（PPE port1）初始化失败时会触发，属预防性修复。

## 0003-dts-2p5g-port.patch

`target/linux/qualcommbe/dts/ipq5332-xiaomi-rd15.dts`：

- `&mdio` 下增加 `ethernet-phy@c`（QCA8081）与 `ethernet-phy@7`（YT8821 探测）
- `&qcom_ppe` 增加 `port@1`：
  `phy-mode = "sgmii"` + **`managed = "in-band-status"`** +
  `pcs-handle = <&pcs0_ch0>` + PORT1 时钟/复位

注意：QCA8081 必须用 `in-band-status`，否则 RX 恒为 0。
不同批次（YT8821）需另测。

## 0004-dts-ubi-bootargs.patch

在 `bootargs-append` 中加入 `ubi.mtd=rootfs`，让内核自动挂载
`ubi0`（安装系统需要）。仅影响启动参数，不影响 flash 内容。
