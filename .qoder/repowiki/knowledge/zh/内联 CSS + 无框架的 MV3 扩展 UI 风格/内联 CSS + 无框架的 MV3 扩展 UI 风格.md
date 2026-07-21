---
kind: frontend_style
name: 内联 CSS + 无框架的 MV3 扩展 UI 风格
category: frontend_style
scope:
    - '**'
source_files:
    - extension/popup.html
---

本仓库的前端样式完全基于 Edge/Chrome Manifest V3 扩展的 popup.html，采用纯内联 style 块加原生 DOM API 的方式实现，未引入任何 CSS 框架、CSS-in-JS 库或构建工具。

1. 样式系统与方法论
- 所有视觉样式集中在 extension/popup.html 的 <style> 标签中（约 450 行），按功能模块分组：基础排版（body/h1/code/p）、面板与统计卡片（.panel/.stats/.stat）、按钮族（主按钮 .tab-button、变体 .secondary/.revise/.danger、禁用态）、表单控件（input/select/textarea）、分类折叠区（.category-group/.category-header/.category-details）、动作预览列表（.action-item 及其子元素）、状态反馈（.error/.ok/.warning/.hint）、加载动画（.spinner + @keyframes spin）。
- 布局主要使用 CSS Grid（.tabs/.stats/.row/.wide-row/.button-row）和 Flexbox（.category-header/.action-meta/.action-actions），没有响应式断点，popup 宽度固定为 420px。
- 交互通过 JS 动态切换 [hidden] 属性与 .open/.expanded 类名控制可见性，而非 CSS :has() 或伪类。

2. 设计令牌与主题约定
- 颜色体系围绕深青绿色 #115e59（主色）、浅灰背景 #f7fafc 到 #eef4f7 渐变、中性文本 #17202a/#52616d、边框 #e4edf0/#cbd8df 展开；语义色用绿色 #166534（成功/同意）、红棕色 #991b1b（拒绝/危险）、琥珀 #92400e（警告）。
- 圆角统一 10px（面板、按钮、输入框），阴影仅用于 .panel（0 6px 18px rgba(18,34,49,0.06)），整体呈现扁平化、卡片化的轻量风格。
- 字体栈使用系统默认 -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif，字号层级从 10px（标签/徽章）到 18px（标题/统计数字）。

3. 关键文件
- extension/popup.html：唯一包含样式的页面，承载全部 UI 结构与内联 CSS。
- extension/offscreen.html：Offscreen Document，不含样式，仅加载逻辑脚本。
- extension/popup.js 与 extension/popup/*.js：通过 element.style.* 与类名切换驱动样式变化，不直接操作 CSS。

4. 开发者应遵循的规则
- 新增样式一律写入 extension/popup.html 的 <style> 块，按现有模块顺序插入，保持命名空间清晰（BEM 风格前缀如 .category-、.action-）。
- 避免在 JS 中硬编码具体颜色值，优先复用已有 class；若必须写内联 style，保持与现有 palette 一致。
- 不使用外部 CSS 文件或构建流程，确保扩展可直接打包安装。
- 由于 popup 尺寸固定，布局以 Grid/Flex 为主，不要依赖媒体查询做响应式适配。