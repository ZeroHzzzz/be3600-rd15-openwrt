# 解锁原厂 SSH

原厂固件默认不开 SSH。刷机前先用 web 后台的管理密码解锁，再算出 root 的
初始密码。

## 原理

小米原厂的 web 后台登录不是明文提交密码，页面里带一个 `key`：

```text
account_hash = sha256(web密码 + key)
nonce        = "0_<deviceId>_<时间戳>_<随机数>"
password     = sha256(nonce + account_hash)
```

把这个 `password` 和 `nonce` POST 到 `/api/xqsystem/login`，换回一个 `stok`
token。

拿到 token 之后，后台的 `set_macfilter_rules` 接口有个问题：它的 `name`
参数会被原样拼进 shell 命令，没有转义。所以在 `name` 里放换行加命令，就能以
root 身份执行。我们用它建 dropbear 的 host key 并启动 `dropbear -p 22`。

root 的初始密码是原厂自己的规则：`md5(设备SN + salt)` 取前 8 位。

原厂的 dropbear 不会随系统自启，重启后就没了，所以还要装一个持久化：
把启动脚本和 host key 放到 `/data/xmir_ssh`，再往 crontab 里加一条每分钟
检查。

## 依赖

- Python 3.8+
- `pip install -r requirements.txt`（requests、pexpect）
- 系统里有 `ssh` 客户端（第三/四步要用）

## 步骤

### 1. 解锁

```sh
python3 scripts/rd15_ssh.py unlock --ip 192.168.31.1
```

按提示输入 web 管理密码。脚本会登录后台、注入命令、启动 22 端口。

也可以用 [xmir-patcher](https://github.com/openwrt-xiaomi/xmir-patcher)，
效果一样，二选一。

### 2. 算 root 密码

```sh
python3 scripts/rd15_ssh.py password --ip 192.168.31.1
```

输出 8 位密码，然后：

```sh
ssh root@192.168.31.1
```

如果设备已经不在网里，可以手动给 SN：

```sh
python3 scripts/rd15_ssh.py password --sn <设备SN>
```

### 3. 让 SSH 重启后还在

```sh
python3 scripts/rd15_ssh.py persist --reboot
```

`--reboot` 会装完配置后重启一次，并等 SSH 自动恢复。不想重启就去掉这个参数。

脚本默认用「SN 算出来的初始密码」登录；如果已经改过 root 密码，可以设置
环境变量：

```sh
RD15_ROOT_PASSWORD='当前密码' python3 scripts/rd15_ssh.py persist
```

### 4. 为刷机打开串口

如果后面要用串口（刷机、恢复都建议有），在 SSH 里执行：

```sh
nvram set uart_en=1
nvram set boot_wait=on
nvram set bootdelay=15
nvram commit
```

## 说明

- 解锁只对当前固件有效，系统升级后可能要重做
- 只对自己的设备操作
