import math
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from hintcad import Project
from physics import calculate
from geometry import horizontal, first_contact, slope_rule, excluded_ranges, active_ranges, ditch_rule


def fixture(folder):
    folder=Path(folder)
    folder.mkdir(parents=True,exist_ok=True)
    data={
        'Demo.PRJ':'''HINTCAD6.00_PRJ_SHUJU
203项目标识 = 双幅测试
214项目ID = test-project-identity
301起点桩号 = 1000
302终点桩号 = 1100
312超高旋转方式 = 0|绕中央分隔带边缘旋转
313超高渐变方式 = 244|线性
101平面线形文件(*.PM) = .\\Alignment.Pm
103纵断面地面线文件(*.DMX) = .\\Terrain.DMX
104纵断面设计文件(*.ZDM) = .\\Demo.ZDM
105横断面地面线文件(*.HDM) = .\\Demo.HDM
106路幅宽度文件(*.WID) = .\\Demo.WID
107超高设置文件(*.SUP) = .\\Demo.SUP
108设计参数控制文件(*.CTR) = .\\Demo.CTR
''',
        'Alignment.Pm':'''HINTCAD5.83_PM_SHUJU_PM
1 NULL NULL 0
1 1000 0 0 0 0
1 0 100 0 9999 9999 1
0 0 50 0 100 0 0 0
1000 1100 0 0
0 0 0 0 0 0
''',
        'Demo.ZDM':'''HINTCAD5.83_ZDM_SHUJU
2
1000 10 0 0 0
1100 10 0 0 0
''',
        'Demo.WID':'''HINTCAD6.00_WID_SHUJU
[LEFT]
1000 2 5 0 1 .5 0
1100 2 6 0 1 .5 0
[RIGHT]
1000 2 7 0 1 .5 0
1100 2 7 0 1 .5 0
''',
        'Demo.SUP':'''HINTCAD5.83_SUP_SHUJU
-3 -2 -2 1000 2 2 -3
9999 9999 9999 1050 9999 9999 9999
-3 -2 -2 1100 2 2 -3
''',
        'Terrain.DMX':'HINTCAD5.83_DMX_SHUJU\n1000 0\n1100 0\n',
        'Other.DMX':'HINTCAD5.83_DMX_SHUJU\n1000 999\n1100 999\n',
        'Demo.HDM':'HINTCAD5.83_HDM_SHUJU\n1000\n2 10 0 90 0\n2 10 0 90 0\n1100\n2 10 0 90 0\n2 10 0 90 0\n',
        'Demo.CTR':'''HINTCAD5.83_CTR_SHUJU
ZTFBP.DAT
99999 3 -1.5 0 8 0 0 0 2 0 -1.75 0 8 0
YTFBP.DAT
99999 3 -1.5 0 8 0 0 0 2 0 -1.75 0 8 0
ZWFBP.DAT
99999 1 1.5 0 6 0
YWFBP.DAT
99999 1 1.5 0 6 0
ZBGXS.DAT
99999 3 -9999 .8 0 0 .8 0 9999 .8 0
YBGXS.DAT
99999 3 -9999 .8 0 0 .8 0 9999 .8 0
ZPSGXS.DAT
99999 4 0 2 0 -.5 1.2 0 0 1.1 0 .5 1.2 0
YPSGXS.DAT
99999 4 0 2 0 -.5 1.2 0 0 1.1 0 .5 1.2 0
QHSJ.DAT
1004 1006 1005 Bridge 1 T 90 0 0 1 -1
SUIDAO.DAT
1020 1030 Tunnel
'''}
    for name,value in data.items():
        (folder/name).write_text(value,encoding='utf-8')
    return folder


class HintCadTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.folder=fixture(Path(self.tmp.name)/'data')

    def tearDown(self):
        self.tmp.cleanup()

    def test_prj_resolves_mixed_names_and_multiple_dmx(self):
        p=Project(self.folder)
        self.assertEqual(p.files['pm'].name,'Alignment.Pm')
        self.assertEqual(p.files['dmx'].name,'Terrain.DMX')
        self.assertEqual(p.origin,(0,0,10))
        self.assertEqual(p.terrain.ground(1050,'LEFT')[-1],(100,0))
        self.assertEqual(p.lj_checks['count'],0)

    def test_variable_width_both_sides_and_sup_skip(self):
        p=Project(self.folder)
        left,widths,_=p.section(1050,'LEFT')
        right,rw,_=p.section(1050,'RIGHT')
        self.assertEqual(widths,[2,5.5,1,.5])
        self.assertAlmostEqual(left[-1][0],9)
        self.assertAlmostEqual(left[-1][1],10-5.5*.02-.02-.015)
        self.assertAlmostEqual(right[-1][0],10.5)
        self.assertAlmostEqual(right[-1][1],10+.14+.02-.015)

    def test_bridge_side_tunnel_and_data_driven_drain_size(self):
        p=Project(self.folder)
        model=calculate(p,step=2)
        self.assertFalse(model['unresolved'])
        for run in model['runs']:
            for row in run['profiles']:
                water=row['channel']
                self.assertAlmostEqual(water[0][1]-water[1][1],1.2)
                self.assertAlmostEqual(water[2][0]-water[1][0],1.1)
            if run['side']=='LEFT':
                self.assertFalse(run['start']<1006 and run['end']>1004)
        right=[r for r in model['runs'] if r['side']=='RIGHT']
        self.assertTrue(any(r['start']<=1004 and r['end']>=1006 for r in right))

    def test_range_is_checked_not_silently_extended(self):
        with self.assertRaisesRegex(ValueError,'coverage'):
            Project(self.folder,start=999)

    def test_attached_lane_is_rejected(self):
        f=self.folder/'Demo.WID'
        f.write_text(f.read_text().replace('1000 2 5 0','1000 2 5 1'),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'Attached'):
            Project(self.folder)

    def test_rotation_mode_is_not_guessed(self):
        f=self.folder/'Demo.PRJ'
        f.write_text(f.read_text(encoding='utf-8').replace('312超高旋转方式 = 0|','312超高旋转方式 = 1|'),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'median-edge'):
            Project(self.folder)

    def test_circular_horizontal_and_exact_piecewise_contact(self):
        s=dict(start=0,end=math.pi*50,theta=0,xy=[0,0],k0=.01,k1=.01)
        a,b=horizontal(s,s['end'])
        self.assertAlmostEqual(a,100,places=8)
        self.assertAlmostEqual(b,100,places=8)
        self.assertEqual(first_contact((0,0),(6,0),[(0,-1),(2,1),(4,-1),(6,1)]),(1,0))

    def test_nonzero_slope_control_height_fails_explicitly(self):
        with self.assertRaises(ValueError):
            slope_rule(['99999','1','-1.5','1','8','0'])

    def test_no_external_prj_reference(self):
        f=self.folder/'Demo.PRJ'
        f.write_text(f.read_text(encoding='utf-8').replace('.\\Alignment.Pm','..\\Alignment.Pm'),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'External'):
            Project(self.folder)

    def test_invalid_lining_flag_is_not_truncated(self):
        with self.assertRaisesRegex(ValueError,'lining'):
            ditch_rule(['99999','1','-1','.8','.5'])

    def test_a_later_valid_setting_does_not_hide_an_invalid_one(self):
        f=self.folder/'Demo.PRJ'
        f.write_text('312超高旋转方式 = 1|unsupported\n'+f.read_text(encoding='utf-8'),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'unvalidated'):
            Project(self.folder)

    def test_history_identifiers_are_not_rotation_settings(self):
        f=self.folder/'Demo.PRJ'
        with f.open('a',encoding='utf-8') as stream:
            stream.write('\n312047385 = 2024/08/20 14:27\n31362328 = 2022/08/22 10:12\n')
        Project(self.folder)


if __name__=='__main__':
    unittest.main()
