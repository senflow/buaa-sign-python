# BUAA Sign Python

Python 业务核心 + macOS 原生状态栏应用，同时保留命令行。提供两个功能：

1. 查询今天的用户全部课程，包括已结束、正在进行和尚未开始的课程。
2. 查看当前时段内明确未签到的课程，按需完成签到。

使用 Python 3.11 或更新版本，仅依赖标准库，无需 pip 安装。原 Java 项目保持独立。

## macOS 状态栏应用

克隆仓库后，在项目目录构建本地应用 `dist/北航课表.app`（环境要求见下方「重新构建」）。每次点击菜单栏学士帽展开面板时，默认显示今日课表，**只查询今天的课程和签到状态**。整学期课表从项目 `.cache/` 读取，退出重启后继续使用，不因打开面板重新请求。没有定时轮询。

```sh
python3 macos/build_app.py
open dist/北航课表.app
```

- **首次使用周课表**：点击「加载学期课表」获取并建立本地缓存。没有缓存时，打开面板也只查询今天，不自动查询学期。
- **更新学期课表**：在周视图中手动点击右上角刷新图标时才重新获取整学期，全部成功后替换缓存。
- **刷新今日**：今日视图中点击右上角刷新图标时只更新今天；每次展开面板也自动执行此操作。已有学期缓存时仅合并今天，其他日期保留。
- **周课表 / 今日课表、上一周 / 下一周**：使用缓存切换，不请求接口。
- **签到**：点击按钮立即提交，确认结果后同步更新内存与本地缓存；不会自动签到。
- **太阳 / 月亮**：切换并保存深浅主题，不联网。
- **齿轮**：选择「校内直连 / 校外 WebVPN」，或打开账号设置；缺失账号密码时弹窗输入。切换网络只保存设置，下一次刷新或重新打开面板时登录。

界面参考 Tokei 的系统字体与字号层级：标题 15–16 pt，课程正文 11–13 pt，辅助信息 10 pt。今日面板宽 440 pt，高度按课程数量自适应，超过上限时滚动；周视图无周末课程时为 580×600 pt，周六、周日分别在有课时显示，每增加一天宽度增加 80 pt。窗口高度受屏幕可用空间限制。界面仅保留课程、状态、更新时间和必要操作，常规刷新成功不再显示重复横幅。

缓存按账号、学期和配置的日期范围隔离，不包含密码或会话令牌，文件权限为仅当前用户读写，并已排除 Git 跟踪。缓存损坏或缺失不会触发学期自动查询。学期更新失败保留原完整缓存；今日查询失败显示错误并保留旧状态。周视图底部单独显示学期缓存时间，今日更新不会把它改成最新。

`config.json` 的 `term` 可指定学期，例如 `202620271`。未设置时按日期推定：9–12 月为本学年第一学期，1 月为上一年开始学年的第一学期，2–8 月为第二学期。实际校历不同时请明确配置。

手动学期加载先查询课程目录和课程安排，再查询实际有课的日期。目录为空的账号则按日期范围兼容查询，最多 4 个并发请求。默认第一学期 9 月 1 日至次年 1 月 31 日，第二学期 2 月 1 日至 8 月 31 日；可用 `semester_start`、`semester_end`（YYYY-MM-DD）指定范围。

### 重新构建

```sh
python3 macos/build_app.py
```

要求 macOS 13+、Apple Command Line Tools（Swift）和 Python 3.11+。原生 SwiftUI/AppKit 前端通过标准输入输出与 Python 后台进程交换 JSON，未开放 HTTP 端口。构建包包含 Python 业务源码，不包含账号配置；此包是供本机使用的构建，记录了本机 Python 和项目配置的路径。移动项目、更换 Python 或在另一台电脑运行时，请重新构建。

应用已做本地 ad-hoc 签名，不是 Apple 公证发行版。原 Java 和 Tokei 项目没有修改。

### 本地验证

- 79 项 Python 测试通过，包括学期日期去重、完整数据替换、失败保留缓存、单课签到状态、账号切换及 WebVPN 网络适配。WebVPN 测试包括完整模拟网关认证/查询/签到链路，以及使用本地自签名 HTTPS 服务验证证书拒绝（该测试需要系统 `openssl` 命令）。
- Swift release 构建与应用签名校验通过。
- `sh macos/Tests/check-schedule-layout.sh` 验证周末独立隐藏、跨午夜、切周及无效课时，使用 Command Line Tools 即可执行。
- `verification/compact-*.png` 为紧凑版界面截图，覆盖今日、周视图、周末有课、空课表、课程较多和详情状态，均使用示例数据。
- `verification/week-panel.png` 为原生界面截图，使用明确的示例课表，不是真实账号数据。
- 本次只读实测：202620271 学期成功获取 204 节课程安排；没有执行真实签到。

## 快速开始

```sh
git clone https://github.com/senflow/buaa-sign-python.git
cd buaa-sign-python
python3 -m buaa_sign
```

不带参数时显示两个功能的菜单。按提示输入学号和统一认证密码；密码输入不回显，也不会自动写入磁盘。课程日期按北京时间确定，无需输入学期编号。

### 功能一：今天全部课程

```sh
python3 -m buaa_sign courses
```

查询北京时间今天的完整课表，显示课程名称、上课时间、教师、教室和签到状态。包括已结束、正在进行和尚未开始的课程，不限于当前可签到的课程，不提交签到。

### 功能二：查看当前课程并签到

先只查看：

```sh
python3 -m buaa_sign sign --dry-run
```

查看后交互确认并签到：

```sh
python3 -m buaa_sign sign
```

已决定为当前列出的全部候选课程签到时：

```sh
python3 -m buaa_sign sign --yes
```

时间统一按北京时间计算，候选条件为：`上课前 10 分钟 ≤ 当前时间 < 下课时间`，且服务端 `signStatus=0`。已经签到或状态未知的课程不会提交。该时间窗口沿用原项目的规则，并不证明老师已开放签到，最终以服务器响应为准。

提交前再次读取课表状态，获取服务器时间戳，然后为每个符合条件的课程提交一次。只有明确的成功标记，或后续课表查询确认已签到，才输出成功。请求响应丢失时会查询状态，不自动重试签到；仍无法确认则显示“待确认”。多次同时启动仍可能形成并发提交，因此请保持单个操作实例。

## 账号配置（可选）

优先读取项目目录 `config.json`；学号或密码缺失、为空时，仅提示输入缺少的字段。不再从环境变量读取账号密码。推荐仅保存学号，每次交互输入密码。

```sh
# 首次使用本地配置时，从空白示例创建；已有配置可直接编辑。
cp config.example.json config.json
chmod 600 config.json
```

编辑项目目录的 `config.json`：

```json
{
  "student_number": "你的学号",
  "password": "",
  "timeout": 15
}
```

`password` 留空时会提示输入。也支持填写密码，但那是明文保存，文件已列入 `.gitignore`。不会读取原 Java 项目的账号文件。

指定其他配置文件时，将全局参数放在子命令前：

```sh
python3 -m buaa_sign --config /绝对路径/config.json courses
```

配置不存在或格式错误会明确报错。非交互环境必须提前提供账号，签到还必须使用 `--yes`，或使用 `--dry-run` 只查询。

## 接口与实现依据

原项目：https://github.com/IceC1eam/BUAAAutoSign

本项目结合维护中的 [buaa-api 的 iClass 实现](https://github.com/fontlos/buaa-api/tree/1a6e1351e31ad3433f1a219ec28e56e7526a4fb2/src/api/class)核对接口。相较旧 Java 项目，使用新的登录路径、查询端口、签到路径和服务器时间戳。此来源是第三方客户端源码，不是学校官方接口承诺。

| 用途 | 地址 |
|---|---|
| 统一认证 | `https://sso.buaa.edu.cn/login` |
| iClass 登录 | `https://iclass.buaa.edu.cn:8346/eschool/app/user/login_buaa.do` |
| 学期全部课程 | `https://iclass.buaa.edu.cn:8347/app/choosecourse/get_myall_course.action` |
| 当天课表 | `https://iclass.buaa.edu.cn:8347/app/course/get_stu_course_sched.action` |
| 服务器时间 | `http://iclass.buaa.edu.cn:8081/eschool/app/common/get_timestamp.action` |
| 签到 | `http://iclass.buaa.edu.cn:8081/eschool/app/course/stu_scan_sign.action` |

使用 CookieJar 管理 SSO Cookie，解析 HTML 隐藏表单字段，跟随有限次数的学校认证跳转，提取 `loginName` 后取得用户 ID。按当前参考实现将 `loginName` 用于后续 `Sessionid` 请求头，用户 ID 放入请求参数。凭据和会话仅保存在当前进程。

支持直连和北航 `d.buaa.edu.cn` WebVPN 两种模式。Python 会使用系统或环境代理配置；`timeout` 为网络操作超时秒数。直连的服务器时间和签到接口使用 HTTP，WebVPN 模式的本机到网关连接使用 HTTPS，并验证证书；网关到 iClass 的协议保持接口原定义。

### 校外 WebVPN

桌面端选择齿轮菜单中的「校外 WebVPN」，然后刷新。配置保存在原来的 `config.json` 中，默认仍为 `direct`；也可以手动添加 `"network": "webvpn"`。网络切换后会重新认证，不复用之前的业务会话。

命令行可临时覆盖配置（全局选项放在子命令前）：

```sh
python3 -m buaa_sign --network webvpn courses
python3 -m buaa_sign --network webvpn sign --dry-run
```

WebVPN 使用现有统一认证账号密码，通过学校网关登录，再进入 iClass。网址转换只支持已列明的学校服务及端口，固定主机映射不需要额外加密依赖；网关 Cookie 只留在内存，并为并发查询复制独立会话。实现参考了 [BUAASignTool e85be13 的 WebVPN 协议](https://github.com/Fucov/BUAASignTool/blob/e85be13af213e768c4833b44fdebf34a84a8b059/iclass_client.py)。

WebVPN 使用 `8347/app/user/login.action` 返回的 `sessionId`，查询使用 GET；时间戳与签到使用 `8081/app/...`，签到用户 ID 放在表单体。原有直连的 `8346/eschool/...`、`8081/eschool/...` 与 `loginName` 会话约定保持不变。课表目录、课程详情和每日课表遇到连接失败时最多尝试 3 次，间隔 0.5 秒、1 秒；认证错误、证书错误和数据格式错误不重试。学期逐日查询最终失败时报告日期并保留原缓存。不会在失败后自动切换接口或重放签到；通用成功响应仍需查询考勤确认。

当前不支持验证码、扫码或其他交互认证。遇到此类要求会明确停止，可切回直连并使用官方客户端 VPN（以学校实际资源权限为准）。外部浏览器的登录 Cookie 不会自动导入应用。

2026-09-24 使用真实账号通过 WebVPN 完成登录并查询到今日 2 节课程，证书校验保持启用。已覆盖网关编码自身地址、票据交换和 Cookie 传递的回归测试；编码回调请求保留原路径，不提前改写为门户直连地址。自动化测试使用模拟账号；未执行真实签到，也未另行切换校外网络验证。

## 验证

```sh
python3 -m unittest discover -v
```

测试使用模拟响应与本地 HTTP 服务，不向学校提交登录或签到。覆盖认证跳转、表单编码与 Cookie、课程查询、时间边界、状态过滤、签到前复查、服务器时间戳、失败状态、响应丢失、只读命令、取消与 CLI 错误处理。

2026-09-14 本机验证：Python 3.13.3 下 26 项测试全部通过；命令帮助正常。另用新客户端真实 GET 访问 SSO 登录页，HTTP 200、execution 表单字段解析成功、CookieJar 收到 4 个 Cookie；未提交账号密码或签到请求。

开发时未使用真实账号，因此**通过测试不代表真实账号登录、课程查询和签到已经验证可用**。首次实测建议先执行 `courses` 和 `sign --dry-run`，确认课表正确后再执行 `sign`，并核对 iClass 中的考勤记录。

退出码：0 为命令正常完成（包括无课、取消、跳过）；1 为错误、签到失败或结果待确认；2 为参数用法错误；130 为用户中断。

## 文件结构

```text
buaa_sign/client.py   HTTP、认证、课程和签到逻辑
buaa_sign/cli.py      两个命令、配置与交互
tests/               客户端、命令行、WebVPN 与桌面桥接测试
config.example.json  可选配置示例
```

## 登录失败提示

旧版“登录未完成：请检查学号密码”仅代表未取得 `loginName`，不代表学校确认密码错误。现已区分明确的账号密码错误、认证仍停留在表单、账号验证提示及 iClass 跳转失败，并在认证落地页没有直接返回凭据时请求个人中心入口。该修正通过模拟测试，尚需真实账号验证。

如更新后仍失败，请提供新的完整错误文字，不要提供密码或 Cookie。账号密码优先读取项目目录的 `config.json`；在学校网页完成额外验证也不保证当前 Python 进程自动获得网页会话。

### 界面性能

课程起止时间在 JSON 解码时一次性解析，日期格式器复用；当前周的筛选结果只在课程数据或所选周变化时重算。视图切换不重新解析整学期日期，也不发网络请求。
