# 作业跟踪

一个面向班主任日常使用的作业缺交记录小工具，包含：

- Flask 数据看板
- SQLite 本地数据存储
- Excel 学生名单导入
- 每日缺交记录导出
- 缺交趋势、学科占比、学生排行榜等可视化

项目默认用于本地管理班级作业缺交情况，不依赖云端服务。

## 功能说明

### 1. 数据看板

启动 Web 服务后，可以查看：

- 本月缺交总人次
- 重灾区学科
- 需重点关注学生
- 每日缺交趋势图
- 各科缺交占比饼图
- 学生缺交次数排行榜

其中学科统计已做归类处理，例如：

- `英语粉书`、`英语卷子`、`英语笔记` 会统一计入 `英语`
- 其他学科也会按学科关键词归并

### 2. 学生名单导入

支持从 Excel 导入学生名单，自动识别常见列名：

- `学号`
- `姓名`
- `性别`

### 3. 缺交记录录入与查询

可通过命令行录入缺交记录，按学生、日期、学科进行查询。

### 4. 每日缺交表导出

录入记录后，会自动按日期导出 Excel 版缺交记录，目录结构类似：

```text
2026/
  03月/
    2026-03-13缺交记录.xlsx
```

## 项目结构

```text
.
├── app.py                # Flask 看板与 API
├── tracker.py            # 命令行记录、查询、导出
├── import_excel.py       # 学生名单 Excel 导入
├── templates/
│   └── index.html        # 看板页面
├── homework.db           # SQLite 数据库（默认不提交）
├── 2025级6班名单.xlsx     # 学生名单（默认不提交）
└── 2026/                 # 每日导出的记录（默认不提交）
```

## 环境准备

建议使用虚拟环境。

### 安装依赖

项目运行依赖主要包括：

- `Flask`
- `pandas`
- `openpyxl`

如果你本地还没有安装，可以执行：

```bash
pip install flask pandas openpyxl
```

## 快速开始

### 1. 初始化数据库

首次使用可执行：

```bash
python tracker.py init
```

### 2. 导入学生名单

```bash
python import_excel.py "2025级6班名单.xlsx"
```

### 3. 启动看板

```bash
python app.py
```

默认访问地址：

```text
http://127.0.0.1:5000
```

## 常用命令

### 录入一条缺交记录

```bash
python tracker.py add_record --name "张三" --date 2026-03-13 --subject "英语粉书" --content "缺交" --remark "请假"
```

### 查询某个学生的缺交记录

```bash
python tracker.py query --name "张三"
```

### 按日期范围查询

```bash
python tracker.py query --name "张三" --start 2026-03-01 --end 2026-03-31
```

### 查看全部学生

```bash
python tracker.py list_students
```

### 手动导出某天的缺交表

```bash
python tracker.py export --date 2026-03-13
```

## Web API

当前看板页面使用以下接口：

- `GET /api/kpi`
- `GET /api/trend`
- `GET /api/subjects`
- `GET /api/rankings`

支持的查询参数：

- `start_date`
- `end_date`
- `student`

示例：

```text
/api/subjects?start_date=2026-03-01&end_date=2026-03-31
```

## 数据与隐私说明

仓库已通过 `.gitignore` 默认忽略以下内容，不会自动提交到 GitHub：

- `homework.db`
- 学生名单 Excel
- 每日导出的 Excel 记录
- `venv`

这部分数据通常包含学生个人信息，建议只保留在本地。

## 后续可扩展方向

- 增加录入表单，而不是只靠命令行
- 增加按班级、学科、学生的筛选维度
- 增加月报、周报导出
- 增加登录与权限控制

## 说明

这个项目更偏向班主任个人工作台，当前实现以实用为主，适合本地部署和日常班级管理。
