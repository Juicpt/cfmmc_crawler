# CFMMC Crawler

批量下载中国期货市场监控中心（CFMMC）结算单（日报、月报）的 Python 脚本。

本项目是基于上游仓库 fork 并持续维护的版本：
- 上游：<https://github.com/jicewarwick/cfmmc_crawler>

## 功能概览

- 支持多账户批量下载（`config.json` 中配置 `accounts`）
- 自动登录并处理验证码（离线 OCR 识别）
- 支持下载：
  - 日报：逐日、逐笔
  - 月报：逐日、逐笔
- 支持按日期区间批量下载
- 已下载文件自动跳过，避免重复下载

## 快速开始（推荐）

### 1) 安装 uv

参考官方文档：<https://docs.astral.sh/uv/>

### 2) 安装依赖

在项目根目录执行：

```bash
uv sync
```

### 3) 准备配置文件

复制模板：

- Linux/macOS

```bash
cp config_example.json config.json
```

- Windows CMD

```bat
copy config_example.json config.json
```

然后编辑 `config.json`（见下文“配置说明”）。

### 4) 运行

- 默认模式（不带日期参数）：仅下载**当天日报**（不下载月报）

```bash
uv run python cfmmc_crawler.py
```

- 区间模式（带起止日期）：下载**区间内日报 + 月报**

```bash
uv run python cfmmc_crawler.py --start-date 20190603 --end-date 20190611
```

## 配置说明

`config.json` 模板如下：

```json
{
  "output_dir": "./data",
  "accounts": [
    {
      "account_no": "******",
      "password": "******"
    }
  ]
}
```

字段说明：

- `output_dir`：下载文件输出目录
- `accounts`：账户列表，可配置多个
  - `account_no`：期货监控中心账号
  - `password`：查询密码

可选字段：

- `non_trading_days`：非交易日列表，示例：

```json
"non_trading_days": ["2025-02-23", "2025-10-01"]
```

说明：程序会优先尝试在线获取交易日数据；在线获取失败时，使用 `non_trading_days` 作为回退数据源。

## 命令行参数

- `--start-date YYYYMMDD`
- `--end-date YYYYMMDD`

注意：

- 两个参数必须同时提供
- 日期格式必须为 `YYYYMMDD`

## 输出目录结构

下载结果保存到：

```text
output_dir/
  account_no/
    日报/
      逐日/
        account_no_YYYY-MM-DD.xls
      逐笔/
        account_no_YYYY-MM-DD.xls
    月报/
      逐日/
        account_no_YYYY-MM.xls
      逐笔/
        account_no_YYYY-MM.xls
```

下载行为说明：

- 程序会先检查目标文件；若对应 `.xls` 已存在且文件大小大于 0，则视为已下载并自动跳过。
- 下载时会先写入同目录下的临时 `.part` 文件，写入完成后再原子替换为最终 `.xls` 文件，避免中断后留下不完整文件被误判为已下载。

## 常见问题

- **验证码识别失败怎么办？**  
  脚本会自动重试登录流程；如持续失败，请稍后重试。

- **为什么只下载了日报，没有月报？**  
  未传 `--start-date/--end-date` 时，默认只下载当天日报。

- **报错提示 `--start-date 与 --end-date 必须同时提供`**  
  请同时传入起止日期，或都不传。

## 交易日与可下载区间限制

- 程序会优先从 `https://investorservice.cfmmc.com/script/tradeDateList.js` 获取非交易日（`disabledDates`）。
- 当在线获取失败时，才会回退使用 `config.json` 中的 `non_trading_days`。
- 如果在线获取失败且未配置 `non_trading_days`，程序会直接报错退出。
- 实际下载日期并不等于你传入的完整区间，而是“工作日且不在非交易日列表内”的子集。
- 若你传入的区间没有可用交易日（如周末区间、节假日区间），当前实现会显式报错提示“给定区间内无可下载交易日”。
- 若 `start_date > end_date`，当前实现会显式报错提示 `--start-date 不能晚于 --end-date`。

## 主要依赖

- beautifulsoup4
- ddddocr
- lxml
- numpy
- onnxruntime
- pillow
- requests

## 致谢

- 参考项目：<https://github.com/sfl666/cfmmc_spider>
