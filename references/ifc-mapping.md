# IFC 4.3 属性约定

这里的结果是Blender对象自定义属性映射，并不是已构造IfcRelDefinesByProperties等关系的原生IFC文件。

- 路线：IfcAlignment/NOTDEFINED；名称、稳定GlobalId、工程原点、范围和来源。长度、范围等放Project_字段，不虚构Pset_AlignmentCommon。
- 行车道/硬路肩：IfcPavement/NOTDEFINED；Pset_PavementCommon.NominalLength；宽度恒定时附NominalWidth，变宽时用自定义WidthMin/WidthMax。Qto_PavementBaseQuantities.Length为条带中心线三维长度。其Width在规范中是厚度方向，不拿行车道宽度填充。
- 中分带/土路肩表面：IfcGeographicElement/USERDEFINED，ObjectType描述表面角色，不因绿色材质推断VEGETATION。
- 填坡/平台：IfcEarthworksFill/SLOPEFILL；挖坡：IfcEarthworksCut/CUT；沟体开挖表面：IfcEarthworksCut/TRENCH。保留坡率、砌护标志、左右侧、桩号和当前控制记录。
- 填挖混合渐变坡面：IfcGeographicElement/USERDEFINED，避免把兼含填挖的过渡面全部误分类为单一填方。渐变水沟仍为TRENCH。
- 桩号文字：IfcReferent/STATION，Pset_Stationing.Station、HasIncreasingStation；文字位于侧方用于显示，正式IFC导出需在轴线上建立参照及表示关系。
- 长度m，面积m²；SUP横坡为有符号比值；CTR放坡字段是1:m而不是横坡百分数。所有Project_字段都是项目自定义数据。
- GlobalId按PRJ项目ID与稳定对象名推导，不复用其他路线的ID；无项目ID时由输入身份建立命名空间。
- Pset_Superelevation和Pset_Width适用于相应IfcReferent事件，不硬套到IfcPavement；道路设计速度等也不硬套到路线实体。
- 不填猜测的材料、厚度、状态、松胀系数、填挖体积、IRI和纹理深度。自定义网格曲面面积不冒充要求棱柱体条件的标准面积。

官方依据：[IfcAlignment](https://standards.buildingsmart.org/IFC/RELEASE/IFC4_3/HTML/lexical/IfcAlignment.htm)、[Pset_PavementCommon](https://standards.buildingsmart.org/IFC/RELEASE/IFC4_3/HTML/lexical/Pset_PavementCommon.htm)、[Pset_Stationing](https://standards.buildingsmart.org/IFC/RELEASE/IFC4_3/HTML/lexical/Pset_Stationing.htm)、[IfcEarthworksFill](https://standards.buildingsmart.org/IFC/RELEASE/IFC4_3/HTML/lexical/IfcEarthworksFill.htm)、[IfcEarthworksCut](https://standards.buildingsmart.org/IFC/RELEASE/IFC4_3/HTML/lexical/IfcEarthworksCut.htm)。
