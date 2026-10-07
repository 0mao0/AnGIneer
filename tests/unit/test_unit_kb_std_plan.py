import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../scripts")))

from kb_std_plan import route, tier_of_filename  # noqa: E402


class KbStdPlanRouteTests(unittest.TestCase):
    """代号前缀→专业库（plan-standards-kb-corpus-package Stage B）。长前缀优先，认不出的进待裁决。"""

    def test_route_specialty(self):
        self.assertEqual(route("JTG_F60-2009 公路交通安全设施设计细则.pdf").library, "公路")
        self.assertEqual(route("JTS 165-2021 水运工程施工规范.pdf").library, "水运")
        self.assertEqual(route("JT 0071-2006 公路.pdf").library, "公路")
        self.assertEqual(route("JTJ 073-2007 旧公路.pdf").library, "公路")
        self.assertEqual(route("SL 228-2013 土石坝沥青混凝土面板.pdf").library, "水利")
        self.assertEqual(route("CJJ 2-2008 城市桥梁设计规范.pdf").library, "市政")
        self.assertEqual(route("CJ 3012-1999 城市配件.pdf").library, "市政")
        self.assertEqual(route("JGJ 130-2011 脚手架.pdf").library, "建筑")
        self.assertEqual(route("DL_T 5044-2014 电力工程直流电源.pdf").library, "电力")
        self.assertEqual(route("TB 10002-2017 铁路桥涵设计规范.pdf").library, "铁路")
        self.assertEqual(route("HY_T 031-2012 海洋工程.pdf").library, "其他行业")
        self.assertEqual(route("LY_T 1607-2020 林业.pdf").library, "其他行业")

    def test_route_unknown_goes_adjudicate(self):
        self.assertEqual(route("GB 50010-2010 混凝土结构设计规范.pdf").library, "待裁决")
        self.assertEqual(route("GB_T 51234-2017 现场设备.pdf").library, "待裁决")
        self.assertEqual(route("随便一份没有代号的.docx").library, "待裁决")
        self.assertEqual(route("DB33_T 1207-2020 某省地标.pdf").library, "待裁决")

    def test_route_t_group_standard_body(self):
        # 团标按 T/ 后的代号主体归专业，认不出进待裁决
        self.assertEqual(route("T_JTJ 0914-2021 公路团标.pdf").library, "公路")
        self.assertEqual(route("T_CETS 001-2019 综合团标.pdf").library, "待裁决")


class KbStdPlanTierTests(unittest.TestCase):
    def test_tier_by_prefix(self):
        self.assertEqual(tier_of_filename("GB 50010-2010 混凝土.pdf"), "国家标准")
        self.assertEqual(tier_of_filename("GBJ 16-87 旧国标.pdf"), "国家标准")
        self.assertEqual(tier_of_filename("JTG_F60-2009 公路.pdf"), "行业标准")
        self.assertEqual(tier_of_filename("DB33_T 1207-2020 某省地标.pdf"), "地方标准")
        self.assertEqual(tier_of_filename("DBJT 15-2017 地方建工.pdf"), "地方标准")
        self.assertEqual(tier_of_filename("DG_TJ08-502-2012 上海建工.pdf"), "地方标准")
        self.assertEqual(tier_of_filename("DGJ 08-107-2015 上海建工.pdf"), "地方标准")
        self.assertEqual(tier_of_filename("T_CETS 001-2019 团标.pdf"), "团体标准")
        self.assertEqual(tier_of_filename("CECS 187-2005 -old团标.pdf"), "团体标准")
        self.assertEqual(tier_of_filename("ISO 9001-2015 国际.pdf"), "国际标准")
        self.assertEqual(tier_of_filename("招标文件.docx"), "")


if __name__ == "__main__":
    unittest.main()
