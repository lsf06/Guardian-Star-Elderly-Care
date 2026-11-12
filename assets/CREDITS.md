# 图片素材说明

`index.html` 现在引用的图全部在 `assets/images/`，共 6 张，**都是 AI 生成的概念示意图，不是实物照片，也不是在售产品**。

## 一、当前使用的图（`assets/images/`）

| 文件 | 画的是什么 | 来源 |
| --- | --- | --- |
| `hero.jpg` | 床头柜上的白色圆盘设备，首屏大图 | AI 生成 |
| `scene.jpg` | 老人坐在床边，设备置于桌面（情景示意） | AI 生成 |
| `detail.jpg` | 磨砂机身、中央确认键、红色 SOS 键近景 | AI 生成 |
| `hardware.jpg` | 树莓派、LD2410C 雷达、门磁、按键的组合示意 | AI 生成 |
| `door.jpg` | 门框上的有线门磁特写 | AI 生成 |
| `ui.jpg` | 交互 / 状态示意 | AI 生成 |

**必须知道的两件事**

1. **图里的设备不是本产品实物。** 外形、按键位置、灯带都是设计意图，实物以 [`hardware/BOM.md`](../hardware/BOM.md) 与接线图为准。首页页脚已写明「页面中的场景、硬件与产品视觉为 AI 生成的概念示意图，非实物照片」，答辩时也要这么说——否则老师一问「按键在哪、壳怎么开的」就穿帮。
2. **替换不用改代码。** 硬件装好后拍实拍图，用同名文件覆盖 `assets/images/` 里的对应文件即可。

> 3D 模型在 `assets/js/model3d.js`，渲染库是 `assets/vendor/three.min.js`（本地引入，断网也能转）。

## 二、旧版素材（`assets/` 根目录三张，已不再被引用）

这三张是改版前的首屏素材，来自 Pexels，遵循 [Pexels License](https://www.pexels.com/license/)：可免费用于商业与非商业用途、无需署名、可修改；限制是不得转售原图、不得暗示图中人物或品牌为本产品背书。

当前 `index.html` 已不再引用它们，保留在仓库里只为留档（如需减小体积可以删）。

| 文件 | 内容 | 来源 | 尺寸 |
| --- | --- | --- | --- |
| `hero.jpg` | 白色桌面上的一台小型智能音箱实拍 | Pexels [#4132542](https://www.pexels.com/photo/4132542/) | 1600 × 1000 |
| `detail-button.jpg` | 金属面板上的圆形按键微距 | Pexels [#36845378](https://www.pexels.com/photo/36845378/) | 1100 × 733 |
| `detail-window.jpg` | 金属网孔面板极近微距 | Pexels [#29754884](https://www.pexels.com/photo/29754884/) | 900 × 600 |

原始文件地址格式：`https://images.pexels.com/photos/<id>/pexels-photo-<id>.jpeg?auto=compress&cs=tinysrgb&w=1600`
