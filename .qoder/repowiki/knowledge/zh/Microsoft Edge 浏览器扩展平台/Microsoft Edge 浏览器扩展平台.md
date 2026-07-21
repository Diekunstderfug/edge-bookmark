---
kind: external_dependency
name: Microsoft Edge 浏览器扩展平台
slug: microsoft-edge
category: external_dependency
category_hints:
    - client_constraint
    - vendor_identity
scope:
    - '**'
---

### Microsoft Edge 浏览器扩展平台
- **角色**: 书签执行器和用户界面载体，基于 Chrome Extension Manifest V3
- **集成点**: `extension/` 目录下的 MV3 扩展代码，无构建步骤
- **权限要求**: bookmarks, storage, offscreen, alarms 等浏览器 API
- **数据源**: 默认读取 `~/Library/Application Support/Microsoft Edge/Default/Bookmarks` 文件
- **执行机制**: 通过 `chrome.bookmarks` API 直接操作书签树，不直接编辑文件
- **最小版本**: 要求 Chrome/Edge 116+
- **限制**: 扩展仅作为执行器，不包含规划逻辑；需要与 Python CLI 配合使用