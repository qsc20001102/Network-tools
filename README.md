# Network-tools

一个基于 Tkinter 的 Windows 网络调试工具，重构版命名为 **NetPilot**。

## 功能

- 网卡配置：读取网卡、IPv4/IPv6、网关、DNS、DHCP、链路速率、接口索引、DHCP 服务器与租约时间。
- 配置模板：保存常用网卡配置、套用模板到表单、删除模板。
- Ping 探测：支持持续/指定次数、间隔、超时、包大小、TTL、禁止分片、本地源 IP 下拉、CIDR/范围/列表批量探活、目标导入、CSV 导出、实时丢包率/平均延迟/抖动/质量统计。
- 端口扫描：支持单端口测试、端口列表/范围、常用端口预设、批量主机/CIDR/IP 段扫描、并发/超时控制、只显示开放端口、服务名识别、可选 Banner 探测、开放端口复制与 CSV 导出。
- 路由追踪：支持设置最大跳数和单跳超时时间。

## 运行

```powershell
python main.py
```

修改网卡配置需要以管理员权限运行程序。

## 打包

直接执行：

```powershell
.\打包.bat
```

打包输出：

```text
dist/NetworkTool.exe
```

配置模板运行时会保存到程序同级目录的 `network_profiles.json`。
