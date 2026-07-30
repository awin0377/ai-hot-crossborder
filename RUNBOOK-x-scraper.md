# X 截流采集系统 Runbook（端云异构）

> 边缘侦察（MacBook M1 Pro）+ 云端中枢（Hostinger VPS）协同的零 API 成本 X 截流管线。
> 采集 → 提纯 → 伪装 → 投递 → LLM 清洗 → UTM 归因 → 真人转化记账，全链路已实测闭环。

## 1. 核心战术思想
- **边缘侦察节点（MacBook）**：用真实物理环境 + AdsPower 本地原生指纹，零 API 成本突破 X 反爬。
- **云端算力中枢（Hostinger VPS）**：24h 后台大本营，读边缘投递的数据，调 Grok/豆包做语义清洗与文案匹配。

## 2. 链路闭环
```
[Mac] crontab → x_scraper_runner.sh (caffeinate 防休眠 + mkdir 单实例锁)
      → x_scraper_mvp.py：AdsPower(50325) 唤醒 → Playwright CDP 劫持
      → 提纯 [data-testid="tweetText"] 纯正文（剔时间戳/点赞数噪声）
      → 本地去噪（无 "chatgpt" 关键词丢弃）
      → 伪装 4 字段 {isRetweet, text, author.userName, url}
      → scp 免密投递 mac_inbox.json
[VPS] generate_content_for_n8n.py（已切断 Apify，改读 mac_inbox.json）
      → Grok-3 主 / 豆包降级：翻译 + 软噪声过滤 + 话术匹配
      → 注入 UTM 归因链接（见 §4）
      → 推入自动发送队列
[转化] 真人点击 /go/chatgpt → 网站 recordClick → Upstash Redis 记账 chatgpt|x_reply
      → sync_clicks.mjs 拉真人数据 → 面板显示
```

## 3. 关键文件
| 位置 | 文件 | 职责 |
|------|------|------|
| Mac | /Users/mac/Downloads/x_scraper_mvp.py | 抓取+提纯+伪装+scp 投递 |
| Mac | /Users/mac/Downloads/x_scraper_runner.sh | crontab 包装：防休眠+锁+异常告警 |
| Mac | /Users/mac/Downloads/x_scraper.log | 运行日志 |
| VPS | generate_content_for_n8n.py | 主脑：读本地弹药+LLM清洗+UTM话术 |
| VPS | mac_inbox.json | 边缘投递的弹药（gitignore） |
| Mac | /Volumes/awin/Projects/remotion-gamsgo/scripts/sync_clicks.mjs | 拉真人转化数据 |

## 4. UTM 归因（真金白银那条线）
- 追踪链接必须走短链路由才记账：`https://getaipremium.com/go/chatgpt?utm_source=x&utm_medium=reply&utm_campaign=x_reply&utm_content=<推文作者名>`
- 打首页 `/?utm_...` **不记账**（不触发 recordClick）——这是早期踩过的坑。
- Redis 数据模型（现行）：真人合格流量写 `clicks:human:total` 和 `clicks:human:day:<date>`（field=`slug|campaign`）；机器人写 `clicks:bots:<date>`；无归因写 `clicks:unattributed:<date>`。旧的 `clicks:total`/`clicks:day` 已废弃。

## 5. 排期
- crontab：`*/30 21-23,0-11 * * *`（北京时间 21:00–次日12:00，对齐北美白天）。
- 物理铁律：**Mac 必须插电**。电池模式系统仍会休眠（pmset 电池 sleep=1），一断电即全停。合盖可以，断电不行。

## 6. 异常防线（Exception-Driven，正常静默）
仅三种致命情况通过 terminal-notifier 弹 Mac 桌面告警：
1. scp 投递失败（VPS 宕机/网络阻断）
2. AdsPower 死锁（锁僵持 >30min）
3. 连续 4 轮提纯为 0（DOM 选择器失效）

## 7. 运维 SOP
```bash
# 手动抓一轮
/Users/mac/Downloads/x_scraper_runner.sh
# 看抓取日志
tail -40 /Users/mac/Downloads/x_scraper.log
# 暂停采集：crontab -e 给 x_scraper_runner.sh 那行加 #
# 看真金白银战绩（核心口径=真人合格点击）
cd /Volumes/awin/Projects/remotion-gamsgo && node scripts/sync_clicks.mjs --days 7
```

## 8. 备份
主脑分步备份：`generate_content_for_n8n.py.bak.apify`（切 Apify 前）、`.bak.utm`（加 UTM 前）；面板脚本 `sync_clicks.mjs.bak.*`。均在各自目录、不入库。
