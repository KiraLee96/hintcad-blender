# 纬地道路三维建模 Skill

将纬地/HintCAD 项目数据转换为 Blender 道路三维模型。

## 功能

- PM/ZDM 路线、WID/SUP 双侧路面、中分带、路肩与桩号。
- DMX/HDM 地面与 CTR 填挖边坡、水沟、填挖渐变；边坡和水沟自动扣除桥隧范围。
- IFC 属性映射、模型回读检查、预览和质量报告；按需导出 OBJ/glTF。

## 安装与使用

将本仓库放入 Codex 的 `~/.codex/skills/hintcad-blender`，然后输入：

> 使用 $hintcad-blender，根据指定的纬地数据文件夹生成三维模型。

也可直接运行（需要 Python 和已安装的 Blender；已在 Blender 4.5 验证）：

```sh
python scripts/run.py --input "<纬地项目目录>" --output "<独立输出目录>" --inspect
python scripts/run.py --input "<纬地项目目录>" --output "<独立输出目录>" --blender "<blender可执行文件>"
```

详细流程见 [SKILL.md](SKILL.md)，文件要求和支持边界见 [数据约定](references/data-contract.md)。源工程只读，已有模型不会默认覆盖。

## 验证

使用 Z1、Z3 和独立双幅样本验证。工程数据及生成模型未包含在仓库中。

```sh
python -m unittest discover -s scripts/tests
```

## 限制

支持指定的纬地文本格式，不识别扫描图纸。不支持的设置或缺失数据会报错；未交地和跳过的短过渡会在报告中列出。IFC 为 Blender 自定义属性映射，并非原生 IFC 文件。几何过渡、边坡及水沟结果需要工程复核；超图导出未在实际超图软件中验证导入。
