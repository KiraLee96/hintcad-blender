# 可选超图导入

选择model.obj，保留同目录model.mtl，单位米、Z轴向上，OBJ旋转方式选择“不旋转”。若只检查外形，可先在局部平面场景以(0,0,0)导入。恢复工程定位时，先确认项目投影坐标系，再按placement.json的origin_E_N_H设置模型定位点。不要重复把原点加到顶点，不要把工程米制坐标当经纬度。

新版本可选择model.gltf并保留其.bin文件。glTF按标准Y-up：X向东，Y为高程，Z为负北向；由导入器遵循其轴向，不能机械套用OBJ旋转设置。

OBJ只保留几何、对象名和材质。glTF节点extras保留属性；是否自动变为超图字段须在目标版本核验。properties.csv/.json是完整属性表，以ObjectName或ExportId关联；如果导入工具合并对象，要先保留/拆分构件，不按记录顺序匹配。未生成原生S3M、OSGB或IFC；需要S3M时在超图中生成模型缓存，不改扩展名假装转换成功。

源模型未交地红线、未应用的短过渡、未知坐标基准等限制随quality_report.json保留。导出验证检查对象、glTF属性、三角面统计和文件完整性，不等同于在SuperMap实机导入验证。

官方文档：[支持的三维模型文件](https://help.supermap.com/iDesktopx/zh/Tools/Import/Import3DModel/Import3DModel.html)、[批量导入与OBJ旋转](https://help.supermap.com/iDesktopx/zh/Tools/3DData/Importdata/Importmodels.html)、[定位点及投影设置](https://help.supermap.com/iDesktopX/1130/zh/tutorial/DataProcessing/DataConversion/BatchImportModel.html)。
