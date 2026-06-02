# 本地翻译器（俄乌）

Windows 便携本地翻译软件：**Argos 强化** 离线翻译，侧重中文 ↔ 俄语 / 乌克兰语，含术语库、斯拉夫语形态后处理与离线语音。

## 翻译引擎

仅 **Argos 强化**（多核 CPU、分档 beam、俄乌术语与后处理）。详见 `命令/引擎说明.txt`。

固定译法、人名、教术语 → 用「术语库」维护（中文源时生效）。

## 检查更新

顶栏 **「检查更新」** 或菜单同名项：从 GitHub [secure-artifacts/ArgosTranslate](https://github.com/secure-artifacts/ArgosTranslate/releases) 拉取最新 Release 的 `ArgosTranslate-vX.Y.Z.zip` 并就地覆盖程序文件（保留 `data/`）。更新完成后请重启软件。

可选配置 `data/config/argos-translate/settings.json`：`"ARGOS_GITHUB_REPO": "组织/仓库名"`。

## 功能

- 多语言翻译（Argos 离线语言包 + 强化后处理）
- 中文术语库与俄/乌变格修补
- 基督教/专业/宗教领域搭配与文体规范化
- 离线语音识别（Vosk，需本地下载模型）

## 安装（用户）

1. 从 [Releases](https://github.com/secure-artifacts/ArgosTranslate/releases) 下载 **`ArgosTranslate-vX.Y.Z.exe`**（一键安装程序，仅需此文件）
2. 双击 exe → **选择安装文件夹**（任意盘符）→ 自动安装（首次需联网，约数分钟）
3. 以后只需再双击同一 exe 即可打开软件
4. 菜单 **「安装位置…」** 可改指向的文件夹，或在空目录 **重新自动安装**

> 更新包 zip 供已有完整目录就地升级；新用户只需 exe。  
> 开发者本地仍可用 `run_gui.bat`（见下方「开发环境」）。

## 开发环境

```bat
cd ArgosTranslate
python -m venv venv
venv\Scripts\pip install argostranslate argostranslategui PyQt5 pymorphy2 pymorphy2-dicts-ru pymorphy2-dicts-uk
python tools\patch_gui_tabs.py
run_gui.bat
```

## 如何发布新版本

本项目使用 GitHub Actions 自动构建和发布。每次发布新版本只需要创建一个 Git Tag 并推送即可。

### 发布步骤

#### 1. 确保代码已提交并推送

```bash
git status
git add .
git commit -m "你的改动说明"
git push origin main
```

#### 2. 创建版本 Tag

版本号格式为 `v主版本.次版本.修订版本`（须与 `app_version.py` 中 `APP_VERSION` 一致或同步更新）。

```bash
git tag -a v1.0.0 -m "Release version 1.0.0"
```

#### 3. 推送 Tag 触发自动构建

```bash
git push origin v1.0.0
```

推送后，GitHub Actions 会自动：

1. 打包便携更新 zip
2. 构建带图标的 launcher exe
3. 生成 Attestation 安全签名
4. 创建 Release 并上传产物

#### 4. 查看构建结果

- 构建进度：仓库 **Actions** 页
- 发布结果：仓库 **Releases** 页

### 版本号说明

| 格式 | 用途 | 示例 |
|------|------|------|
| `vX.0.0` | 重大更新 | `v2.0.0` |
| `vX.Y.0` | 新功能 | `v1.1.0` |
| `vX.Y.Z` | Bug 修复 | `v1.0.1` |

### 构建失败怎么办

1. 在 **Actions** 查看日志
2. 修复代码或 `.github/workflows/release.yml`
3. 删除失败的 tag 并重新创建：

```bash
git tag -d v1.0.1
git push origin :refs/tags/v1.0.1
git tag -a v1.0.1 -m "Release version 1.0.1"
git push origin v1.0.1
```

## 安全发布

本仓库位于 `secure-artifacts` 组织，Release 产物由 `github-actions[bot]` 上传并附带 Attestation。员工可从[软件安全平台](https://tpscsm-web.pages.dev/)跳转下载。

## 许可

第三方组件遵循各自许可证（Argos Translate、PyQt 等）。
