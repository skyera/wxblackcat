# Author     : Zhigang Liu
# Date       : Jan 2009
# License    : General Public License 2 (GPL2) 
# Description: Slice STL CAD file layer by layer

import wx
import os
import sys
import string
import copy
import time
import logging
import pprint
import math
import cProfile
import random

try:
    import psyco
    psyco.full()
except ImportError, e:
    print e

try:
    from wx import glcanvas
    haveGLCanvas = True
except ImportError, e:
    print e
    sys.exit()

try:
    from OpenGL.GL import *
    from OpenGL.GLUT import *
except ImportError, e:
    print e
    sys.exit()

LIMIT = 1e-8

def equal(f1, f2):
    if abs(f1 - f2) < LIMIT:
        return True
    else:
        return False

class EndFileException(Exception):
    def __init__(self, args=None):
        self.args = args

class FormatError(Exception):
    def __init__(self, value=None):
        self.value = value
    
    def __str__(self):
        return 'FormatError:' + self.value

class Point:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x = x
        self.y = y
        self.z = z

    def __str__(self):
        s = '(%f, %f, %f) ' % (self.x, self.y, self.z)
        return s

    def __eq__(self, other):
        return equal(self.x, other.x) and equal(self.y, other.y) and equal(self.z, other.z)

    def __cmp__(self, other):
        if self == other:
            return 0
        elif self.x < other.x or self.y < other.y or self.z < other.z:
            return -1
        else:
            return 1
    
    def __hash__(self):
        s = '%.6f %.6f %.6f' % (self.x, self.y, self.z)
        return hash(s)
        
        #t = (self.x, self.y, self.z)
        #return hash(t)


class Line:
    
    def __init__(self, p1=Point(), p2=Point()):
        self.p1 = p1
        self.p2 = p2

    def __str__(self):
        return str(self.p1) + " -> " + str(self.p2)

    def __eq__(self, other):
        ret = (self.p1 == other.p1 and self.p2 == other.p2) or (self.p1 == other.p2 and self.p2 == other.p1)
        return ret

    def __cmp__(self, other):
        L1 = [self.p1, self.p2]
        L2 = [other.p1, other.p2]
        L1.sort()
        L2.sort()
        
        if L1 == L2:
            return 0
        elif L1 < L2:
            return -1
        else:
            return 1
    
    def length(self):
        dx = self.p1.x - self.p2.x
        dy = self.p1.y - self.p2.y
        dz = self.p1.z - self.p2.z
        sum = dx * dx + dy * dy + dz * dz
        return math.sqrt(sum)
    
    def slope(self):
        diffy = self.p2.y - self.p1.y 
        diffx = self.p2.x - self.p1.x
        
        if equal(diffx, 0.0):
            return sys.maxint
        else:
            k = diffy / diffx
            return k

    def __hash__(self):
        L = [self.p1, self.p2]
        L.sort()
        t = tuple(L)
        return hash(t)

def intersect(x1, y1, x2, y2, x):
    ''' compute y'''
    y = (y2 - y1) / (x2 - x1) * (x - x1) + y1
    return y

def isIntersect(p1, p2, z):
    if (p1.z - z) * (p2.z - z) <= 0.0:
        return True
    else:
        return False

def calcIntersect(p1, p2, z):
    x1 = p1.x
    y1 = p1.y
    z1 = p1.z

    x2 = p2.x
    y2 = p2.y
    z2 = p2.z
    
    x = intersect(z1, x1, z2, x2, z)
    y = intersect(z1, y1, z2, y2, z)
    p = Point(x, y, z)
    return p

class Facet:
    def __init__(self):
        self.normal = Point()
        self.points = (Point(), Point(), Point())

    def __str__(self):
        s = 'normal: ' + str(self.normal)
        s += ' points:'
        for p in self.points:
            s += str(p)
        return s
    
    def changeDirection(self, direction):
        if direction == "+X":
            for p in self.points:
                p.x, p.z = p.z, p.x
        elif direction == "-X":
            for p in self.points:
                p.x, p.z = p.z, -p.x
        elif direction == "+Y":
            for p in self.points:
                p.y, p.z = p.z, p.y
        elif direction == "-Y":
            for p in self.points:
                p.y, p.z = p.z, -p.y
        elif direction == '-Z':
            for p in self.points:
                p.z = -p.z
        elif direction == '+Z':
            pass
        else:
            assert 0

    def intersect(self, z):
        L1 = [True for p in self.points if p.z > z]
        L2 = [True for p in self.points if p.z < z]
        if len(L1) == 3 or len(L2) == 3:
            return None
        
        L1 = []
        L2 = []
        for i in range(3):
            p = self.points[i]
            if equal(p.z, z):
                L1.append(i)
            else:
                L2.append(i)
        
        points = self.points
        n = len(L1)
        if n == 0:
            line = self.intersect_0_vertex(points, z)
            assert line
        elif n == 1:
            i1 = L2[0]
            i2 = L2[1]
            p1 = points[i1]
            p2 = points[i2]
            if isIntersect(p1, p2, z):
                line = self.intersect_1_vertex(points[L1[0]], p1, p2, z)
            else:
                line = None
        elif n == 2:
            i1 = L1[0]
            i2 = L1[1]
            line = Line(points[i1], points[i2])
        elif n == 3:
            line = None
        else:
            assert 0
        
        if line:
            length = line.length()
            assert length > 0.0
        return line

    def intersect_0_vertex(self, points, z):
        L = []
        for i in range(3):
            next = (i + 1) % 3
            p1 = points[i]
            p2 = points[next]
            if isIntersect(p1, p2, z):
                p = calcIntersect(p1, p2, z)
                L.append(p)
        
        assert len(L) == 2
        return Line(L[0], L[1])

    def intersect_1_vertex(self, p1, p2, p3, z):
        p = calcIntersect(p2, p3, z)
        return Line(p1, p)

class Layer:

    def __init__(self, z, pitch):
        self.lines = []
        self.z = z
        self.pitch = pitch

    def empty(self):
        return len(self.lines) == 0

    def createGLList(self):
        self.layerListId = 1001
        glNewList(self.layerListId, GL_COMPILE)
        glColor(0, 0, 1)
        glBegin(GL_LINES)
        for loop in self.loops:
            r = random.random()
            g = random.random()
            b = random.random()
            glColor(r, g, b)
            for line in loop:
                for p in [line.p1, line.p2]:
                    glVertex3f(p.x, p.y, p.z)
        
        for chunk in self.chunks:
            r = random.random()
            g = random.random()
            b = random.random()
            glColor(r, g, b)
 
            for line in chunk:
                for p in [line.p1, line.p2]:
                    glVertex3f(p.x, p.y, p.z)
        
        glEnd()
        glEndList()
        return self.layerListId

    def setLines(self, lines):
        self.lines = lines
        self.createLoops()
        self.calcDimension()             
        self.createScanlines()
        self.createChunks()

    def createLoops(self):
        lines = self.lines

        oldlines = copy.deepcopy(lines)
        self.loops = []
        while len(lines) != 0:
            loop = []
            
            line = lines.pop()
            loop.append(line)
            
            start = line.p1
            p2 = line.p2
            
            while True:
                found = False
                for aline in lines:
                    if p2 == aline.p1:
                        p1 = aline.p1
                        p2 = aline.p2
                        found = True
                        break
                    elif p2 == aline.p2:
                        p1 = aline.p2
                        p2 = aline.p1
                        found = True
                        break

                if found:        
                    lines.remove(aline)
                    loop.append(Line(p1, p2))
                    if p2 == start:
                        break
                else:
                    print 'error'
                    print len(oldlines), len(lines)
                    for it in oldlines:
                        print it
                    print '--'
                    for it in lines:
                        print it
                    print p2
                    assert 0
                    break
            
            if found:
                self.moveLines(loop)
                nloop = self.mergeLines(loop)
                self.loops.append(nloop)
            else:
                self.loops.append(loop)
    
    def moveLines(self, loop):
        tail = loop[-1]
        k1 = tail.slope()
        head = loop[0]
        k2 = head.slope()
        rmList = []
        if equal(k1, k2):
            for aline in loop:
                k = aline.slope()
                if equal(k, k1):
                    rmList.append(aline)
                else:
                    break
            for it in rmList:
                loop.remove(it)
            for it in rmList:
                loop.append(it)
        
        k1 = loop[0].slope()
        k2 = loop[-1].slope()
        assert k1 != k2

    def mergeLines(self, loop):
        n1 = len(loop)
        nloop = []
        
        while len(loop) != 0:
            
            line = loop.pop(0) 
            k1 = line.slope()
            p1 = line.p1
            p2 = line.p2
            
            rmList = []            
            for aline in loop:
                k2 = aline.slope()
                if k1 != k2:
                    p2 = aline.p1
                    break
                else:
                    p2 = aline.p2
                    rmList.append(aline)
            
            for it in rmList:
                loop.remove(it)
            nloop.append(Line(p1, p2))
        head = nloop[0]
        tail = nloop[-1]
        assert head.p1 == tail.p2
        
        #for i in range(0, len(nloop) - 1):
        #    k1 = nloop[i]
        #    k2 = nloop[i + 1]
        #    #assert k1 != k2
        return nloop

    def calcDimension(self):
        ylist = []
        for loop in self.loops:
            for line in loop:
                ylist.append(line.p1.y)
                ylist.append(line.p2.y)
        self.miny = min(ylist)                
        self.maxy = max(ylist)
    
    def calcDimension2(self):
        ylist = []
        for line in self.lines:
            ylist.append(line.p1.y)
            ylist.append(line.p2.y)
        self.miny = min(ylist)
        self.maxy = max(ylist)
    
    def createScanlines(self):
        self.scanlines = []
        y = self.miny + self.pitch
        while y < self.maxy:
            scanline = self.createOneScanline(y)
            if len(scanline) != 0:
                self.scanlines.append(scanline)
            y += self.pitch
    
    def createOneScanline(self, y):
        L = []
        for loop in self.loops:
            for line in loop:
                x = self.intersect(y, line, loop)
                if x != None:
                    for it in L:
                        if equal(x, it):
                            break
                    else:
                        L.append(x)
        L.sort()                    
        ok = (len(L) % 2 == 0)
        assert ok

        L2 = []
        n = len(L)
        for i in range(0, n, 2):
            x1 = L[i]
            x2 = L[i + 1]
            p1 = Point(x1, y, self.z)
            p2 = Point(x2, y, self.z)
            line = Line(p1, p2)
            L2.append(line)
        return L2

    def createOneScanline2(self, y):
        L = []
        lines = self.lines
        for line in lines:
            x = self.intersect(y, line, lines)
            if x != None:

                for it in L:
                    if equal(x, it):
                        break;
                else:
                    L.append(x)
        
        L.sort()                    
        ok = (len(L) % 2 == 0)
        if not ok:
            for it in L:
                print it
            L.pop(-1)
            assert ok

        L2 = []
        n = len(L)
        for i in range(0, n, 2):
            x1 = L[i]
            x2 = L[i + 1]
            p1 = Point(x1, y, self.z)
            p2 = Point(x2, y, self.z)
            line = Line(p1, p2)
            L2.append(line)
        return L2

    def intersect(self, y, line, loop):
        y1 = line.p1.y
        y2 = line.p2.y
        if self.isIntersect(y1, y2, y):
            count = 0
            if equal(y, y1):
                count += 1
                p = line.p1

            if equal(y, y2):
                count += 1
                p = line.p2
            
            if count == 0:
                x = self.intersect_0(y, line)
            elif count == 1:
                x = self.intersect_1(y, p, line, loop)
            elif count == 2:
                x = None

            return x
        else:
            return None

    def intersect_0(self, y, line):
        x1 = line.p1.x
        y1 = line.p1.y
        x2 = line.p2.x
        y2 = line.p2.y
        
        if equal(x1, x2):
            x = x1
            return x
        else:
           x = (y -  y1) * (x2 - x1) / (y2 - y1) + x1
           return x

    def isPeak(self, y, point, lines):
        L = []
        for line in lines:
            if point == line.p1:
                p = line.p2
            elif point == line.p2:
                p = line.p1
            else:
                assert 0
            L.append(p)
        
        n = len(L)
        if n != 2:
            print n
            assert 0
        assert L[0] != L[1]
        val = (L[0].y - y) * (L[1].y - y)
        if val > 0.0:
            return True
        else:
            return False

    def intersect_1(self, y, point, line, loop):
        L = []
        for it in loop:
            if point in (it.p1, it.p2):
                L.append(it)
        assert len(L) == 2
        assert line in L
        
        peak = self.isPeak(y, point, L)
        
        if peak:
            print 'peak'
            return None
        else:
            return point.x     

    def isIntersect(self, y1, y2, y):
        if (y1 - y) * (y2 - y) <= 0.0:
            return True
        else:
            return False
    
    def getOverlapLine(self, line, scanline):
        y2 = scanline[0].p1.y
        y1 = line.p1.y
        
        if not equal(y2 - y1, self.pitch):
            return False
        
        for aline in scanline:
            if aline.p1.x >= line.p2.x or aline.p2.x <= line.p1.x:
                pass
            else:
                return aline
        return False                

    def createChunks(self):
        self.chunks = []
        scanlines = self.scanlines
        while len(scanlines) != 0:
            chunk = []
            scanline = scanlines[0]
            line = scanline.pop(0)
            chunk.append(line)
            
            for scanline in scanlines[1:]:
                nline = self.getOverlapLine(line, scanline)
                if nline:
                    chunk.append(nline)
                    scanline.remove(nline)
                    line = nline 
                else:
                    break
            
            self.chunks.append(chunk)
            scanlines = filter(lambda x: len(x) > 0, scanlines)

class CadModel:
    def __init__(self):
        self.initLogger()
        self.loaded = False
        self.currLayer = -1
        self.sliced = False
        self.dimension = {}
    
    def nextLayer(self):
        n = len(self.layers)
        self.currLayer = (self.currLayer + 1) % len(self.layers)
    
    def prevLayer(self):
        n = len(self.layers)
        self.currLayer -= 1
        if self.currLayer == -1:
            self.currLayer = len(self.layers) -1

    def getCurrLayer(self):
        return self.layers[self.currLayer]

    def initLogger(self):
        #self.logger = logging.getLogger(self.__class__.__name__)
        self.logger = logging.getLogger("cadmodel")
        self.logger.setLevel(logging.DEBUG)
        h = logging.StreamHandler()
        h.setLevel(logging.DEBUG)
        f = logging.Formatter("%(levelname)s %(filename)s:%(lineno)d %(message)s")
        h.setFormatter(f)
        self.logger.addHandler(h)
    
    def getLine(self, f):
        line = f.readline()
        if not line:
            raise EndFileException, 'end of file'
        return line.strip()

    def getNormal(self, f):
        line = self.getLine(f)
        items = line.split()
        no = len(items)
        if no != 5:
            if no >=1 and items[0] == "endsolid":
                self.loaded = True
                raise EndFileException, 'endfile'
            else:
                self.logger.error(line)
                raise FormatError, line
        
        if items[0] != 'facet' and items[1] != 'normal':
            self.logger.error(line)
            raise FormatError, line
        
        L = map(lambda x: float(x), items[2:])
        normal = Point(L[0], L[1], L[2])
        return normal

    def getOuterloop(self, f):
        line = self.getLine(f)
        if line != "outer loop":
            self.logger.error(line)
            raise FormatError, line

    def getVertex(self, f):
        points = []
        for i in range(3):
            line = self.getLine(f)
            items = line.split()
            no = len(items)
            if no != 4:
                self.logger.error(line)
                raise FormatError, line
            if items[0] != 'vertex':
                self.logger.error(line)
                raise FormatError, line

            L = map(lambda x: float(x), items[1:])
            point = Point(L[0], L[1], L[2])
            points.append(point)
        return points
    
    def getEndloop(self, f):
        line = self.getLine(f) 
        if line != 'endloop':
            self.logger.error(line)
            raise FormatError, line
    
    def getEndFacet(self, f):
        line = self.getLine(f)
        if line != 'endfacet':
            self.logger.error(line)
            raise FormatError, line

    def getFacet(self, f):
        normal = self.getNormal(f)   
        self.getOuterloop(f)
        points = self.getVertex(f)
        facet = Facet()
        facet.normal = normal
        facet.points = points
        self.getEndloop(f)
        self.getEndFacet(f)
        return facet
    
    def getSolidLine(self, f):
        ''' Read the first line'''
        line = self.getLine(f)
        items = line.split()
        no = len(items)
        if no >= 2 and items[0] == 'solid':
            self.modelName = items[1]
        else:
            self.logger.error(line)
            raise FormatError, line
    
    def calcDimension(self):
        if self.loaded:
            xlist = []
            ylist = []
            zlist = []
            for facet in self.facets:
                for p in facet.points:
                    xlist.append(p.x)
                    ylist.append(p.y)
                    zlist.append(p.z)
            self.minx = min(xlist)
            self.maxx = max(xlist)
            self.miny = min(ylist)
            self.maxy = max(ylist)
            self.minz = min(zlist)
            self.maxz = max(zlist)
            
            self.xsize = self.maxx - self.minx
            self.ysize = self.maxy - self.miny
            self.zsize = self.maxz - self.minz

            self.diameter = math.sqrt(self.xsize * self.xsize + self.ysize * self.ysize + self.zsize * self.zsize)

            # Center
            self.xcenter = (self.minx + self.maxx) / 2
            self.ycenter = (self.miny + self.maxy) / 2
            self.zcenter = (self.minz + self.maxz) / 2

    def open(self, filename):
        start = time.time()
        try:
            f = open(filename) 
        except IOError, e:
            print e
            return False
        
        try:
            self.getSolidLine(f)
            self.facets = [] 
            while True:
                facet = self.getFacet(f)
                self.facets.append(facet)
        except EndFileException, e:
            pass
        except FormatError, e:
            print e
            return False
        
        if self.loaded:
            self.calcDimension()
            self.logger.debug("no of facets:" + str(len(self.facets)))
            self.oldfacets = copy.deepcopy(self.facets)
            self.sliced = False
            self.setOldDimension()
            cpu = '%.1f' % (time.time() - start)
            
            print 'open cpu', cpu, 'secs'
            return True
        else:
            return False

    def slice(self, para):
        self.height = float(para["height"])
        self.pitch = float(para["pitch"])
        self.speed = float(para["speed"])
        self.fast = float(para["fast"])
        self.direction = para["direction"]
        self.scale = float(para["scale"])
        
        self.scaleModel(self.scale)
        self.changeDirection(self.direction)
        self.calcDimension()
        self.createLayers()
        if len(self.layers) > 0:
            self.currLayer = 0
            self.sliced = True
            self.currLayer = 0
            self.setNewDimension()
            return True
        else:
            self.sliced = False
            return False
    
    def setOldDimension(self):
        self.dimension["oldx"] = str(self.xsize)
        self.dimension["oldy"] = str(self.ysize)
        self.dimension["oldz"] = str(self.zsize)
        self.dimension["newx"] = ""
        self.dimension["newy"] = ""
        self.dimension["newz"] = ""

    def setNewDimension(self):
        self.dimension["newx"] = str(self.xsize)
        self.dimension["newy"] = str(self.ysize)
        self.dimension["newz"] = str(self.zsize)

    def scaleModel(self, factor):
        self.facets = []
        for facet in self.oldfacets:
            nfacet = copy.deepcopy(facet)
            ps = []
            for p in nfacet.points:
                p.x *= factor
                p.y *= factor
                p.z *= factor
                ps.append(p)
            nfacet.points = ps
            self.facets.append(nfacet)
    
    def changeDirection(self, direction):
        for facet in self.facets:
            facet.changeDirection(direction)
    
    def createLayers(self):
        start = time.time()
        self.layers = []
        z = self.minz + self.height
        count = 0
        while z < self.maxz:
            layer = self.createOneLayer(z)
            z += self.height
            if layer:
                count += 1
                self.layers.append(layer)
        print 'no of layers:', len(self.layers)                
        cpu = '%.1f' % (time.time() - start)
        print 'slice cpu', cpu,'secs'
    
    def createOneLayer(self, z):
        layer = Layer(z, self.pitch)
        lines = []
        for facet in self.facets:
            line = facet.intersect(z) 
            if line:
                p1 = line.p1
                p2 = line.p2
                for it in lines:
                    if (p1 == it.p1 and p2 == it.p2) or (p1 == it.p2 and p2 == it.p1):
                        break
                else:
                    lines.append(line)
        
        if len(lines) != 0:
            layer.setLines(lines)
            return layer
        else:
            return None
    
    def createGLModelList(self):
        self.modelListId = 1000
        glNewList(self.modelListId, GL_COMPILE)
        if self.loaded:
            glColor(1, 0, 0)
            glBegin(GL_TRIANGLES)
            for facet in self.facets:
                normal = facet.normal
                glNormal3f(normal.x, normal.y, normal.z)
                for p in facet.points:
                    glVertex3f(p.x, p.y, p.z)
            glEnd()
        glEndList()

    def createGLLayerList(self):
        layer = self.getCurrLayer()
        return layer.createGLList()

class PathCanvas(glcanvas.GLCanvas):

    def __init__(self, parent):
        glcanvas.GLCanvas.__init__(self, parent, -1)

        self.Bind(wx.EVT_ERASE_BACKGROUND, self.OnEraseBackground)
        self.Bind(wx.EVT_SIZE, self.OnSize)
        self.Bind(wx.EVT_PAINT, self.OnPaint)
        self.cadModel = None

    def OnEraseBackground(self, event):
        pass

    def OnSize(self, event):
        if self.GetContext():
            self.SetCurrent()
            size = self.GetClientSize()
            glViewport(0, 0, size.width, size.height)
        self.Refresh()
        event.Skip()

    def OnPaint(self, event):
        dc = wx.PaintDC(self)
        self.SetCurrent()
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        self.showPath()
        self.SwapBuffers()

    def setModel(self, cadModel):
        self.cadModel = cadModel
        self.Refresh()

    def setupProjection(self):
        maxlen = self.cadModel.diameter
        size = self.GetClientSize()
        w = size.width
        h = size.height
        
        half = maxlen / 2
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()

        if w <= h:
            factor = float(h) / w
            left = -half
            right = half
            bottom = -half * factor
            top = half * factor
        else:
            factor = float(w) / h
            left  = -half * factor 
            right = half * factor
            bottom = -half
            top = half
        near = 0
        far = maxlen * 2
        glOrtho(left, right, bottom, top, near, far)           

    def showPath(self):
        if not self.cadModel or not self.cadModel.sliced:
            return

        self.setupProjection()
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()
        layer = self.cadModel.getCurrLayer()
        z = layer.z
        glTranslatef(-self.cadModel.xcenter, -self.cadModel.ycenter, -z)
        layerId = self.cadModel.createGLLayerList()
        glCallList(layerId)

            
class ModelCanvas(glcanvas.GLCanvas):

    def __init__(self, parent):
        glcanvas.GLCanvas.__init__(self, parent, -1)
        self.init = False
        self.cadModel = None
        # initial mouse position
        self.lastx = self.x = 30
        self.lasty = self.y = 30
        self.size = None
        self.xangle = 0
        self.yangle = 0

        self.Bind(wx.EVT_ERASE_BACKGROUND, self.OnEraseBackground)
        self.Bind(wx.EVT_SIZE, self.OnSize)
        self.Bind(wx.EVT_PAINT, self.OnPaint)
        self.Bind(wx.EVT_LEFT_DOWN, self.OnMouseDown)
        self.Bind(wx.EVT_LEFT_UP, self.OnMouseUp)
        self.Bind(wx.EVT_MOTION, self.OnMouseMotion)
        self.loaded = False

        self.modelList = 1000

    def OnEraseBackground(self, event):
        pass # Do nothing, to avoid flashing on MSW.

    def OnPaint(self, event):
        dc = wx.PaintDC(self)
        self.SetCurrent()
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        self.showModel()

        if self.cadModel and self.cadModel.sliced:
            layerId = self.cadModel.createGLLayerList()
            glCallList(layerId)
        self.SwapBuffers()

    def showModel(self):
        if not self.loaded:
            return
        
        #self.setupGLContext()
        self.setupProjection()
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()
         
        glTranslatef(0, 0, -self.cadModel.diameter)
        # Rotate model
        glRotatef(self.xangle, 1, 0, 0)
        glRotatef(self.yangle, 0, 1, 1)
        
        # Move model to origin
        glTranslatef(-self.cadModel.xcenter, -self.cadModel.ycenter, -self.cadModel.zcenter)
        
        glCallList(self.cadModel.modelListId)

    def OnMouseDown(self, evt):
        self.CaptureMouse()
        self.x, self.y = self.lastx, self.lasty = evt.GetPosition()

    def OnMouseUp(self, evt):
        if self.HasCapture():
            self.ReleaseMouse()

    def OnMouseMotion(self, evt):
        if evt.Dragging() and evt.LeftIsDown():
            self.lastx, self.lasty = self.x, self.y
            self.x, self.y = evt.GetPosition()

            self.xangle += (self.y - self.lasty)
            self.yangle += (self.x - self.lastx)
            self.Refresh(False)

    def setModel(self, cadModel):
        self.cadModel = cadModel
        self.xangle = 0
        self.yangle = 0
        self.loaded = True
        self.SetCurrent()
        
        if not self.init:
            self.setupGLContext()
            self.init =  True
        self.cadModel.createGLModelList()
        self.Refresh()

    def OnSize(self, event):
        if self.GetContext():
            self.SetCurrent()
            self.setupViewport()
        self.Refresh()
        event.Skip()
    
    def setupViewport(self):
        size = self.GetClientSize()
        glViewport(0, 0, size.width, size.height)

    def setupProjection(self):
        maxlen = self.cadModel.diameter
        size = self.GetClientSize()
        w = size.width
        h = size.height
        
        half = maxlen / 2
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()

        if w <= h:
            factor = float(h) / w
            left = -half
            right = half
            bottom = -half * factor
            top = half * factor
        else:
            factor = float(w) / h
            left  = -half * factor 
            right = half * factor
            bottom = -half
            top = half
        near = 0
        far = maxlen * 2
        glOrtho(left, right, bottom, top, near, far)    

    def setupGLContext(self):
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        glEnable(GL_LIGHTING);
        glEnable(GL_LIGHT0);

        ambientLight = [0.2, 0.2, 0.2, 1.0]
        diffuseLight = [0.8, 0.8, 0.8, 1.0]
        specularLight = [0.5, 0.5, 0.5, 1.0]
        position = [-1.5, 1.0, -4.0, 1.0 ]
        position = [-15.0, 30.0, -40.0, 1.0]

        glLightfv(GL_LIGHT0, GL_AMBIENT, ambientLight);
        glLightfv(GL_LIGHT0, GL_DIFFUSE, diffuseLight);
        glLightfv(GL_LIGHT0, GL_SPECULAR, specularLight);
        glLightfv(GL_LIGHT0, GL_POSITION, position);
        glLightModelfv(GL_LIGHT_MODEL_AMBIENT, [0.2, 0.2, 0.2, 1.0])

        mcolor = [ 0.0, 0.0, 0.4, 1.0]
        glMaterialfv(GL_FRONT, GL_AMBIENT_AND_DIFFUSE, mcolor)
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_CULL_FACE)
        glPolygonMode(GL_BACK, GL_LINE)
        glColorMaterial(GL_FRONT, GL_AMBIENT_AND_DIFFUSE)
        glEnable(GL_COLOR_MATERIAL)
        glMaterial(GL_FRONT, GL_SHININESS, 50)#96)


class DimensionPanel(wx.Panel):
    
    def __init__(self, parent):
        wx.Panel.__init__(self, parent)
        self.txtFields = {}
        self.createControls()

    def createControls(self):
        box = wx.StaticBox(self, label="Dimension") 
        sizer = wx.StaticBoxSizer(box, wx.HORIZONTAL)
        self.SetSizer(sizer)
        
        label = "Original"
        items = [("X", "oldx"), ("Y", "oldy"), ("Z", "oldz")]
        s1 = self.createDimension(label, items)
        sizer.Add(s1, 1, wx.EXPAND|wx.ALL, 2)

        label = "Scaled"
        items = [("X", 'newx'), ('Y', 'newy'), ('Z', 'newz')]
        s2 = self.createDimension(label, items)
        sizer.Add(s2, 1, wx.EXPAND|wx.ALL, 2)

    def createDimension(self, label, items):
        sizer = wx.BoxSizer(wx.VERTICAL) 
        caption = wx.StaticText(self, label=label)
        sizer.Add(caption, 0, wx.ALIGN_CENTER)

        flex = wx.FlexGridSizer(rows=len(items), cols=2, hgap=2, vgap=2)
        for label, key in items:
            lblCtrl = wx.StaticText(self, label=label)
            txtCtrl = wx.TextCtrl(self, size=(70, -1), style=wx.TE_READONLY)
            flex.Add(lblCtrl)
            flex.Add(txtCtrl, 0, wx.EXPAND)
            self.txtFields[key] = txtCtrl
        sizer.Add(flex, 0, wx.EXPAND)
        flex.AddGrowableCol(1, 1)
        return sizer

    def setValues(self, dimension):
        for key in dimension:
            self.txtFields[key].SetValue(dimension[key])

class ControlPanel(wx.Panel):
    
    def __init__(self, parent):
        wx.Panel.__init__(self, parent, -1)
        self.createControls()

    def createControls(self):
        mainsizer = wx.BoxSizer(wx.VERTICAL)
        
        sizer = wx.BoxSizer(wx.VERTICAL)
        mainsizer.Add(sizer, 1, wx.ALL|wx.EXPAND, 10)
        self.SetSizer(mainsizer)
        
        # Dimension panel
        self.dimensionPanel = DimensionPanel(self)
        sizer.Add(self.dimensionPanel, 0, wx.EXPAND|wx.ALIGN_CENTER)
        
        # Slice info panel
        sizer.Add((10,10)) 
        sliceSizer = self.createSliceInfo()
        sizer.Add(sliceSizer, 0, wx.EXPAND)

        # image
        sizer.Add((10, 10), 1, wx.ALL|wx.EXPAND, 5)
        img = wx.Image('cat.jpg', wx.BITMAP_TYPE_ANY)
        w = img.GetWidth()
        h = img.GetHeight()
        factor = 0.8
        img2 = img.Scale(w * factor, h * factor)
        sb = wx.StaticBitmap(self, -1, wx.BitmapFromImage(img2), style=wx.SUNKEN_BORDER)
        sizer.Add(sb)

    def createSliceInfo(self):
        self.txtFields = {}
        box = wx.StaticBox(self, -1, "Slice Info")
        sizer = wx.StaticBoxSizer(box, wx.VERTICAL)

        items = [("Layer hight", "height"), ("Pitch", "pitch"), ("Speed", "speed"), 
                 ("Direction", "direction"), ("Num Layers", "nolayer"),
                 ("Current Layer", "currlayer")]
        flex = wx.FlexGridSizer(rows=len(items), cols=2, hgap=2, vgap=2)
        for label, key in items:
            lblCtrl = wx.StaticText(self, label=label)
            txtCtrl = wx.TextCtrl(self, size=(70, -1), style=wx.TE_READONLY)
            flex.Add(lblCtrl)
            flex.Add(txtCtrl, 0, wx.EXPAND)
            self.txtFields[key] = txtCtrl
        flex.AddGrowableCol(1, 1)
        sizer.Add(flex, 1, wx.EXPAND|wx.ALL, 2)
        return sizer

    def setDimension(self, dimension): 
        self.dimensionPanel.setValues(dimension)

    def setSliceInfo(self, info):
        for key in self.txtFields.keys():
            txt = self.txtFields[key]
            value = info.get(key, "")
            txt.SetValue(value)
    
    def setNoLayer(self, nolayer):
        self.txtFields["nolayer"].SetValue(str(nolayer))

    def setCurrLayer(self, curr):
        self.txtFields["currlayer"].SetValue(str(curr))

sliceParameter = {"height":"0.4", "pitch":"0.38", "speed":"10", "fast":"20", "direction":"+Z", "scale":"1"}


class BlackCatFrame(wx.Frame):

    def __init__(self):
        wx.Frame.__init__(self, None, -1, "Black Cat", size=(800, 600))
        self.createMenuBar()
        self.createToolbar()
        self.cadmodel = CadModel()
        self.statusbar = self.CreateStatusBar()
        self.createPanel()
        self.Centre()

    def createToolbar(self):
        self.ID_OPEN = 1000
        self.ID_SLICE = 1001
        self.ID_NEXT = 2000
        self.ID_PREV = 2001
        toolbar = self.CreateToolBar()
        img_open = wx.ArtProvider.GetBitmap(wx.ART_FILE_OPEN)
        img_slice = wx.ArtProvider.GetBitmap(wx.ART_CDROM)
        img_next = wx.ArtProvider.GetBitmap(wx.ART_GO_DOWN)
        img_prev = wx.ArtProvider.GetBitmap(wx.ART_GO_UP)
        toolbar.AddLabelTool(self.ID_OPEN, 'open', img_open, shortHelp='open file', longHelp='open CAD model')
        toolbar.AddLabelTool(self.ID_SLICE, 'slice', img_slice, shortHelp='slice modal')
        toolbar.AddLabelTool(self.ID_NEXT, 'next', img_next, shortHelp='next layer')
        toolbar.AddLabelTool(self.ID_PREV, 'prev', img_prev, shortHelp='previous layer')
        toolbar.Realize()

        self.Bind(wx.EVT_TOOL, self.OnOpen, id=self.ID_OPEN)
        self.Bind(wx.EVT_TOOL, self.OnSlice, id=self.ID_SLICE)
        self.Bind(wx.EVT_TOOL, self.OnNextLayer, id=self.ID_NEXT)
        self.Bind(wx.EVT_TOOL, self.OnPrevLayer, id=self.ID_PREV)
        
    def OnNextLayer(self, event):
        if not self.cadmodel.sliced:
            return
        self.cadmodel.nextLayer()
        self.leftPanel.setCurrLayer(self.cadmodel.currLayer)
        self.Refresh()

    def OnPrevLayer(self, event):
        if not self.cadmodel.sliced:
            return

        self.cadmodel.prevLayer()
        self.leftPanel.setCurrLayer(self.cadmodel.currLayer)
        self.Refresh()

    def createPanel(self):
        self.leftPanel  = ControlPanel(self)
        
        self.sp = wx.SplitterWindow(self)
        self.modelPanel = wx.Panel(self.sp, style=wx.SUNKEN_BORDER)
        self.pathPanel = wx.Panel(self.sp, style=wx.SUNKEN_BORDER)
        self.pathPanel.SetBackgroundColour('sky blue')
        self.sp.Bind(wx.EVT_SPLITTER_SASH_POS_CHANGED, self.OnPosChanging)
        
        # Model canvas
        self.modelCanvas = ModelCanvas(self.modelPanel)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.modelCanvas, 1, wx.EXPAND)
        self.modelPanel.SetSizer(sizer)

        box = wx.BoxSizer(wx.HORIZONTAL)
        box.Add(self.leftPanel, 0, wx.EXPAND)
        box.Add(self.sp, 1, wx.EXPAND)
        self.SetSizer(box)

        # Path canvas
        self.pathCanvas = PathCanvas(self.pathPanel)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.pathCanvas, 1, wx.EXPAND)
        self.pathPanel.SetSizer(sizer)

        self.sp.Initialize(self.modelPanel)
        self.sp.SplitVertically(self.modelPanel, self.pathPanel, 300)
        self.sp.SetMinimumPaneSize(20)
    
    def OnPosChanging(self, event):
        self.Refresh(False)

    def createMenuBar(self):
        menubar = wx.MenuBar()
        for data in self.menuData():
            label = data[0]
            items = data[1:]
            menubar.Append(self.createMenu(items), label)
        self.SetMenuBar(menubar)    

    def menuData(self):
        return (("&File", ("&Open", "Open CAD file", self.OnOpen),
                         ("&Slice", "Slice CAD model", self.OnSlice),
                         ("", "", ""),
                         ("&Quit", "Quit", self.OnQuit)),
                ("&Help", ("&About", "About this program", self.OnAbout))
                 )
    
    def OnAbout(self, event):
        info = wx.AboutDialogInfo()
        info.Name = "Black Cat"
        info.Version = "0.1"
        info.Copyright = "(C) 2009"
        info.Description = "Slice CAD model"
        info.Developers = ["Zhigang Liu"]
        info.License = "GPL v2"
        wx.AboutBox(info)

    def createMenu(self, menuData):
        menu = wx.Menu()
        for label, status, handler in menuData:
            if not label:
                menu.AppendSeparator()
                continue
            menuItem = menu.Append(-1, label, status)
            self.Bind(wx.EVT_MENU, handler, menuItem)
        return menu

    def OnOpen(self, event):
        wildcard = "CAD std files (*.stl)|*.stl|All files (*.*)|*.*"
        dlg = wx.FileDialog(None, "Open CAD stl file", os.getcwd(), "", wildcard, wx.OPEN)
        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            self.statusbar.SetStatusText(path)
            print 'open', path
            ok = self.cadmodel.open(path)
            if ok:
                self.modelCanvas.setModel(self.cadmodel)
                self.pathCanvas.setModel(None)
                self.leftPanel.setDimension(self.cadmodel.dimension)
            else:
                wx.MessageBox("Cannot open " + path, 'Error')
        dlg.Destroy()

    def OnSlice(self, event):
        if not self.cadmodel.loaded:
            wx.MessageBox("load a CAD model first", "warning")
            return

        dlg = ParaDialog(self)
        result = dlg.ShowModal()
        if result == wx.ID_OK:
            sliceParameter =  dlg.getValues()
            print 'slicing...'
            ok = self.cadmodel.slice(sliceParameter)
            if ok:
                self.modelCanvas.setModel(self.cadmodel)
                self.leftPanel.setDimension(self.cadmodel.dimension)
                self.leftPanel.setSliceInfo(sliceParameter)
                self.leftPanel.setNoLayer(len(self.cadmodel.layers))
                self.leftPanel.setCurrLayer(self.cadmodel.currLayer)
                self.pathCanvas.setModel(self.cadmodel)
                
            else:
                self.Refresh()
                wx.MessageBox("no layers", "Warning")

        else:
            print 'Cancel'
        dlg.Destroy()

    def OnQuit(self, event):
        self.Close() 

class CharValidator(wx.PyValidator):

    def __init__(self, data, key):
        wx.PyValidator.__init__(self)
        self.Bind(wx.EVT_CHAR, self.OnChar)
        self.data = data
        self.key = key

    def Clone(self):
        return CharValidator(self.data, self.key)
    
    def Validate(self, win):
        textCtrl = self.GetWindow()
        text = textCtrl.GetValue()
        if len(text) == 0:
            wx.MessageBox("This field must contain some text!", "Error")
            textCtrl.SetBackgroundColour('pink')
            textCtrl.SetFocus()
            textCtrl.Refresh()
            return False
        else:
            try:
                value = float(text)
            except ValueError:
                wx.MessageBox("must be a number", "Error")  
                textCtrl.SetBackgroundColour('pink')
                textCtrl.SetFocus()
                textCtrl.Refresh()

                return False
            if value < 0:
                wx.MessageBox("value < 0!", "Error")
                textCtrl.SetBackgroundColour('pink')
                textCtrl.SetFocus()
                textCtrl.Refresh()

                return False

        textCtrl.SetBackgroundColour(wx.SystemSettings_GetColour(wx.SYS_COLOUR_WINDOW))
        textCtrl.Refresh()
        return True
    
    def TransferToWindow(self):
        textCtrl = self.GetWindow()
        value = self.data.get(self.key, "")
        textCtrl.SetValue(value)
        return True

    def TransferFromWindow(self):
        textCtrl = self.GetWindow()
        self.data[self.key] = textCtrl.GetValue()
        return True
    
    def OnChar(self, event):
        code = event.GetKeyCode()
        if code < 256: 
            key = chr(code)
            if key in string.letters:
                return
        event.Skip()

class SlicePanel(wx.Panel):

    def __init__(self, parent, data):
        wx.Panel.__init__(self, parent, -1)
        self.data = data
        self.txtList = []
        self.createControls()

    def createControls(self):
        labels = [("Layer height", "0.43", "height"), ("Pitch", "0.38", "pitch"), \
                  ("Scanning speed", "20", "speed"), ("Fast speed", "20", "fast")]
        
        outsizer = wx.BoxSizer(wx.VERTICAL)
        sizer = wx.BoxSizer(wx.VERTICAL)
        outsizer.Add(sizer, 0, wx.ALL, 10)
        box = wx.FlexGridSizer(rows=3, cols=2, hgap=5, vgap=5)
        for label, dvalue, key in labels:
            lbl = wx.StaticText(self, label=label)
            box.Add(lbl, 0, 0)
            txt = wx.TextCtrl(self, -1, dvalue, size=(80, -1), validator=CharValidator(self.data, key))
            box.Add(txt, 0, 0)
            self.txtList.append(txt)
        sizer.Add(box, 0, 0)
        
        # slice direction
        lbl = wx.StaticText(self, label="Slice direction")
        box.Add(lbl, 0, 0)

        self.dirList = ["+X", "-X", "+Y", "-Y", "+Z", "-Z"]
        self.dirChoice = dirChoice = wx.Choice(self, -1, (160, -1), choices=self.dirList)
        dirChoice.SetSelection(4)
        box.Add(dirChoice, 0, wx.EXPAND)
        self.txtList.append(dirChoice)
        
        # scale
        lbl = wx.StaticText(self, label="Scale factor")
        box.Add(lbl, 0, 0)
        scaleTxt = wx.TextCtrl(self, -1, "1", size=(80, -1), validator=CharValidator(self.data, "scale"))
        box.Add(scaleTxt, 0, wx.EXPAND)
        self.SetSizer(outsizer)
        self.txtList.append(scaleTxt)

    def getSliceDir(self):
        self.data["direction"] = self.dirList[self.dirChoice.GetCurrentSelection()]
        self.Validate()

    def disableTxt(self):
        for txt in self.txtList:
            txt.SetBackgroundColour('white')
            txt.Disable()

class ParaDialog(wx.Dialog):

    def __init__(self, parent):
        pre = wx.PreDialog()
        pre.SetExtraStyle(wx.WS_EX_VALIDATE_RECURSIVELY)
        pre.Create(parent, -1, "Slice parameters")
        self.PostCreate(pre)
        self.createControls()

    def createControls(self):
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.panel = SlicePanel(self, sliceParameter)
        sizer.Add(self.panel, 0, 0)
        sizer.Add(wx.StaticLine(self), 0, wx.EXPAND|wx.TOP|wx.BOTTOM, 5)
        
        #
        btnSizer = wx.BoxSizer(wx.HORIZONTAL)
        btnSizer.Add((10, 10), 1)
        okBtn = wx.Button(self, wx.ID_OK)
        okBtn.SetDefault()
        cancelBtn = wx.Button(self, wx.ID_CANCEL, "Cancel")
        btnSizer.Add(okBtn)
        btnSizer.Add((10,10), 1)
        btnSizer.Add(cancelBtn)
        btnSizer.Add((10,10), 1)
        sizer.Add(btnSizer, 0, wx.EXPAND|wx.ALL, 10)

        self.SetSizer(sizer)
        self.Fit()
    
    def getValues(self):
        self.panel.getSliceDir()
        return sliceParameter

if __name__ == '__main__':
    app = wx.PySimpleApp()
    BlackCatFrame().Show()
    app.MainLoop()
