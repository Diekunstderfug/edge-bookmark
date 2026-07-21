---
kind: external_dependency
name: OpenAI 兼容 API 服务
slug: openai
category: external_dependency
category_hints:
    - vendor_identity
    - sdk_real_api
scope:
    - '**'
---

### OpenAI 兼容 API 服务
- **角色**: AI 规划器核心依赖，用于生成书签整理方案
- **使用模式**: 通过官方 `openai` Python SDK 调用，支持 responses 和 chat.completions 两种 API 风格
- **兼容性处理**: 自动回退链 `responses/json_schema → chat.completions/json_schema → chat.completions/json_object → chat.completions/plain_json`
- **配置方式**: 环境变量 `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_ORGANIZATION`, `OPENAI_PROJECT`
- **安全约束**: base_url 必须使用 https:// 协议
- **验证**: 需参考官方文档确认 exact API/params 使用方法