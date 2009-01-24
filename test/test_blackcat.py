import sys
import os
sys.path.append(os.path.join(sys.path[0], ".."))
from blackcat import *
import unittest

class CadModelTest(unittest.TestCase):
    def setUp(self):
        pass

    def tearDown(self):
        pass

    def testOpen(self):
        cadmodel = CadModel()
        ok = cadmodel.open("rect.stl")
        self.assert_(ok)

    def testOpen_notexistfile(self):
        cadmodel = CadModel()
        ok = cadmodel.open("xxx.stl")
        self.assert_(not ok)

    def testOpen_wrongformat(self):
        fname = 'tmp.txt'
        f = open(fname, 'w')
        print >> f, 'xxx'
        f.close()

        cadmodel = CadModel()
        ok = cadmodel.open(fname)
        self.assert_(not ok)

    def testOpen_emptyfile(self):
        fname = 'tmp.txt'
        f = open(fname, 'w')
        f.close()

        cadmodel = CadModel()
        ok = cadmodel.open(fname)
        self.assert_(not ok)

    def testOpen_normal(self):
        fname = 'tmp.txt'
        f = open(fname, 'w')
        print >> f, "solid TEST"
        print >> f, "facet norma"
        f.close()

        cadmodel = CadModel()
        ok = cadmodel.open(fname)
        self.assert_(not ok)
    
    def testLine(self):
        p1 = Point(1.0, 2.0, 3.0)
        p2 = Point(4.0, 5.0, 6.0)
        
        line1 = Line(p1, p2)
        line2 = Line(p2, p1)
        
        ok = line1 == line2
        self.assert_(ok)
        
        ok = (line1 < line2)
        self.assert_(not ok)

        ok = (line2 > line1)
        self.assert_(not ok)

        s = set()
        s.add(line1)
        s.add(line2)
        self.assert_(len(s) == 1)

        ok = line1 in s
        self.assert_(ok)
        ok = line2 in s
        self.assert_(ok)
    
    def testLine2(self):
        p1 = Point(1.0, -0.0, 2.0)
        p2 = Point(1.0, 0.0, 2.0)

        ok = (p1 == p2)
        self.assert_(ok)
    
    def testOnSameLine(self):
        p1 = Point(0, 0, 0)
        p2 = Point(2, 4, 0)
        p3 = Point(4, 8, 0)
        line1 = Line(p1, p2)
        line2 = Line(p2, p3)
        
        ok = line1.onSameLine(line2)
        self.assert_(ok)
if __name__ == '__main__':
    unittest.main()
