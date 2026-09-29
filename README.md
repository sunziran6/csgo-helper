# CS:GO 瞄点记录工具

一个轻量级的本地桌面软件，用于记录 CS:GO 各地图的道具瞄点（站位/瞄点截图 + 文字描述）。数据完全保存在本地，开箱即用，无需联网、无需数据库服务。

> 层级结构：**地图** →（**分类** | **瞄点**）。分类下只能建瞄点；不属于任何分类的瞄点直接挂在地图下。每个瞄点支持**多张图片** + 名称 + 描述。

---

## ✨ 功能特性

- **地图管理**：自由新建 / 重命名 / 删除地图（不预置任何地图）
- **分类与瞄点**：地图下可建分类，也可直接建"地图直属"瞄点；分类可编辑、删除
- **多图瞄点**：一个瞄点可关联多张图片，支持从磁盘多选、`Ctrl+V` 粘贴截图，缩略图可单张移除
- **图片处理**：自动去重（MD5）、超限自动压缩（长边 1920px / JPEG 质量 85）、自动生成缩略图
- **搜索**：按关键字全局 / 按当前地图 / 按当前分类筛选瞄点
- **大图查看**：详情页多图画廊，点开可左右切换看大图
- **备份与恢复**：导出 / 导入 zip 备份包（含全部数据与图片），支持跳过 / 覆盖 / 副本三种冲突策略；启动时按策略自动备份
- **浅色圆润界面**：白底黑字、圆角卡片、无滚动条（滚轮滑动）、右下角悬浮 ＋ 号快速新建

---

## 🧱 技术栈

| 组成 | 选型 |
| --- | --- |
| 语言 | Python 3.12 |
| 界面 | Tkinter / ttk（纯标准库，无重型 GUI 依赖）|
| 存储 | SQLite（WAL 模式，外键级联，`user_version` 版本迁移）|
| 图片 | Pillow（缩放 / 压缩 / 剪贴板抓取 / 缩略图）|
| 第三方依赖 | 仅 `Pillow` |

架构为清晰的三层：**UI 层 → Service 层 → Repository/DAO 层**，单向依赖。

---

## 📁 目录结构

```
job/
├── main.py                     # 程序入口
├── requirements.txt            # 依赖（Pillow）
├── app/
│   ├── config.py               # 路径与全局配置
│   ├── context.py              # 应用上下文（装配 db 与各服务）
│   ├── logging_setup.py        # 日志
│   ├── db/
│   │   ├── database.py         # SQLite 封装、建表、迁移
│   │   └── dao.py              # MapDao / CategoryDao / SpotDao
│   ├── services/
│   │   ├── image_service.py    # 图片导入/去重/压缩/缩略图/剪贴板
│   │   ├── map_service.py      # 地图/分类/瞄点业务编排
│   │   ├── search_service.py   # 搜索
│   │   └── backup_service.py   # 备份导出/导入/自动备份
│   └── ui/
│       ├── theme.py            # 浅色主题与圆角辅助
│       ├── main_window.py      # 主窗口
│       ├── add_page.py         # 新建/编辑对话框（多图画廊）
│       ├── image_viewer.py     # 大图查看器（多图切换）
│       ├── settings_dialog.py  # 设置
│       └── simple_dialog.py    # 通用输入对话框
├── tests/
│   ├── smoke_test.py           # 全链路无界面冒烟测试
│   └── multi_image_test.py     # 多图 + 迁移专项测试
└── data/                       # 【运行时生成，已在 .gitignore 中忽略】
    ├── data.db                 # SQLite 数据库
    ├── images/                 # 图片原图 + thumbs/ 缩略图
    ├── backups/                # 自动备份
    └── app.log                 # 日志
```

---

## 🚀 安装与运行

### 1. 环境要求

- Python **3.12+**（Windows / macOS / Linux 均可，界面基于 Tkinter）
- 确保安装 Python 时勾选了 **tcl/tk and IDLE**（Tkinter 随官方安装包默认提供）

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 运行

```bash
python main.py
```

首次运行会在程序目录下自动创建 `data/` 文件夹（数据库、图片、备份、日志），无需任何手动配置。

### 4. 运行测试（可选）

```bash
python tests/smoke_test.py         # 全链路冒烟测试
python tests/multi_image_test.py   # 多图 + 数据迁移测试
```

> 测试全程使用系统临时目录，**不会触碰** `data/` 下的真实数据。

---

## 📦 打包为 exe（免装 Python 分发）

```bash
pip install pyinstaller
pyinstaller -w -F -n "CSGO瞄点记录" main.py
```

- `-w`：不弹出控制台窗口
- `-F`：打包成单个可执行文件
- 产物在 `dist/` 下；运行时 `data/` 会生成在 exe 同级目录

---

## 💾 数据存储与备份

- **所有个人数据都集中在 `data/` 目录**：拷贝整个文件夹即可迁移或手动备份到别处。
- **数据库结构升级**：程序启动时自动检测 `user_version` 并执行迁移（例如 v1 单图 → v2 多图），**无需手动执行任何 SQL**，旧数据自动保留。
- **应用内备份**：
  - 手动导出 / 导入 zip 备份包（含数据与图片），导入支持"跳过 / 覆盖 / 副本"冲突策略；
  - 启动时若距上次备份超过 7 天，自动备份数据库到 `data/backups/`，最多保留 5 份。
- **图片去重**：相同内容的图片只存一份（按 MD5），删除瞄点时仅清理不再被引用的图片文件。

---

## 🔒 隐私说明

`data/` 目录（数据库、图片、备份、日志）属于**本地个人数据**，已列入 `.gitignore`，**不应提交到版本库**。若曾误提交，请及时从仓库中移除并清理历史。

---

## 📝 说明

本项目为个人学习/自用的小工具，与 Valve、CS:GO 官方无任何关联。
