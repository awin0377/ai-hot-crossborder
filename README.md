# AI HOT 跨境出海专能版晨报

每日自动拉取 AI HOT 日报数据，按跨境出海业务场景过滤分类，生成单文件 HTML 仪表盘。

## 自动化流程

```
GitHub Actions Cron (每天北京时间 08:00)
  → 调用 aihot API 拉取日报 + 精选条目
  → 按跨境出海关键词过滤分类 (5个版块)
  → 渲染生成 index.html
  → 自动 commit & push
  → GitHub Pages 实时更新
```

## 五个版块

| 版块 | 方向 |
|------|------|
| B2B获客工具 | 智能外贸搜客、Agent邮件群发、自动化CRM |
| SEO内容工厂 | 自动化内容生成、关键词量产、商品描述优化 |
| 视频AI分发 | Remotion/HeyGen类自动化视频、TikTok/YouTube分发 |
| 广告多语言 | Meta/Google AI投流优化、多语言文案、智能客服 |
| 行业趋势 | 跨境电商平台AI政策、海外支付/物流AI应用 |

## 本地运行

```bash
python3 generate_report.py
# 输出: index.html
```

## 数据源

- [AI HOT](https://aihot.virxact.com) 日报 API
- 过滤标准：跨境出海 / 外贸B2B / 独立站 / 海外营销强相关
