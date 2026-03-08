#!/usr/bin/env python
# -----------------------------------------------------------------------------
# Author     : Zhigang Liu
# Date       : Jan 2009
# Email      : zgliu2@gmail.com
# License    : General Public License 2 (GPL2)
# Description: Slice STL CAD file layer by layer
# -----------------------------------------------------------------------------

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Library General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.

import copy
import logging
import math
import os
import queue
import random
import string
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import wx
import wx.adv

import cat

try:
    from wx import glcanvas
except ImportError as e:
    print(e)
    sys.exit()

try:
    from OpenGL.GL import *
    from OpenGL.GLUT import *
except ImportError as e:
    print(e)
    sys.exit()

ERROR = 2
REDO = 3
LAYER = 4
NOT_LAYER = 5
INTERSECTED = 6
NOT_INTERSECTED = 7
SCANLINE = 8
NOT_SCANLINE = 9
LIMIT = 1e-8


def equal(f1: float, f2: float) -> bool:
    return math.isclose(f1, f2, abs_tol=LIMIT)


class EndFileException(Exception):
    pass


class FormatError(Exception):
    def __init__(self, value: str = ""):
        self.value = value

    def __str__(self):
        return f"FormatError: {self.value}"


@dataclass(frozen=True, order=True)
class Point:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    def __str__(self):
        return f"({self.x:f}, {self.y:f}, {self.z:f}) "

    def __eq__(self, other):
        if not isinstance(other, Point):
            return NotImplemented
        return (
            equal(self.x, other.x) and equal(self.y, other.y) and equal(self.z, other.z)
        )

    def __hash__(self):
        return hash((round(self.x, 6), round(self.y, 6), round(self.z, 6)))


@dataclass
class Line:
    p1: Point = field(default_factory=Point)
    p2: Point = field(default_factory=Point)

    def __str__(self):
        return f"{self.p1} -> {self.p2}"

    def length(self) -> float:
        dx = self.p1.x - self.p2.x
        dy = self.p1.y - self.p2.y
        dz = self.p1.z - self.p2.z
        return math.sqrt(dx * dx + dy * dy + dz * dz)

    def slope(self) -> float:
        diffy = self.p2.y - self.p1.y
        diffx = self.p2.x - self.p1.x

        if equal(diffx, 0.0):
            return math.inf
        return diffy / diffx


def intersect(x1: float, y1: float, x2: float, y2: float, x: float) -> float:
    """compute y"""
    return (y2 - y1) / (x2 - x1) * (x - x1) + y1


def is_intersected(p1: Point, p2: Point, z: float) -> bool:
    return (p1.z - z) * (p2.z - z) <= 0.0


def calc_intersected_point(p1: Point, p2: Point, z: float) -> Point:
    x = intersect(p1.z, p1.x, p2.z, p2.x, z)
    y = intersect(p1.z, p1.y, p2.z, p2.y, z)
    return Point(x, y, z)


@dataclass
class Facet:
    normal: Point = field(default_factory=Point)
    points: Tuple[Point, Point, Point] = field(
        default_factory=lambda: (Point(), Point(), Point())
    )

    def __str__(self):
        points_str = "".join(str(p) for p in self.points)
        return f"normal: {self.normal} points: {points_str}"

    def change_direction(self, direction: str):
        new_points = []
        for p in self.points:
            x, y, z = p.x, p.y, p.z
            if direction == "+X":
                new_points.append(Point(z, y, x))
            elif direction == "-X":
                new_points.append(Point(z, y, -x))
            elif direction == "+Y":
                new_points.append(Point(x, z, y))
            elif direction == "-Y":
                new_points.append(Point(x, z, -y))
            elif direction == "-Z":
                new_points.append(Point(x, y, -z))
            elif direction == "+Z":
                new_points.append(p)
            else:
                raise ValueError(f"Unknown direction: {direction}")
        self.points = tuple(new_points)

    def intersect(self, z: float) -> Tuple[int, Optional[Line]]:
        L1 = [True for p in self.points if p.z > z]
        L2 = [True for p in self.points if p.z < z]
        if len(L1) == 3 or len(L2) == 3:
            return (NOT_INTERSECTED, None)

        equal_z_indices = [i for i, p in enumerate(self.points) if equal(p.z, z)]
        other_indices = [i for i, p in enumerate(self.points) if not equal(p.z, z)]

        n = len(equal_z_indices)
        if n == 0:
            line = self.intersect_0_vertex(self.points, z)
            return (INTERSECTED, line)
        elif n == 1:
            p1 = self.points[other_indices[0]]
            p2 = self.points[other_indices[1]]
            if is_intersected(p1, p2, z):
                line = self.intersect_1_vertex(
                    self.points[equal_z_indices[0]], p1, p2, z
                )
                return (INTERSECTED, line)
            return (NOT_INTERSECTED, None)
        elif n in (2, 3):
            return (REDO, None)

        return (NOT_INTERSECTED, None)

    def intersect_0_vertex(self, points: Tuple[Point, Point, Point], z: float) -> Line:
        L = []
        for i in range(3):
            next_idx = (i + 1) % 3
            p1, p2 = points[i], points[next_idx]
            if is_intersected(p1, p2, z):
                L.append(calc_intersected_point(p1, p2, z))

        assert len(L) == 2
        return Line(L[0], L[1])

    def intersect_1_vertex(self, p1: Point, p2: Point, p3: Point, z: float) -> Line:
        p = calc_intersected_point(p2, p3, z)
        return Line(p1, p)


class Layer:
    def __init__(self, z: float, pitch: float):
        self.lines: List[Line] = []
        self.z = z
        self.pitch = pitch
        self.loops: List[List[Line]] = []
        self.chunks: List[List[Line]] = []
        self.scanlines: List[List[Line]] = []
        self.id = 0

    def empty(self) -> bool:
        return len(self.lines) == 0

    def create_gllist(self) -> int:
        self.layerListId = 1001
        glNewList(self.layerListId, GL_COMPILE)

        glBegin(GL_LINES)
        for chunk in self.chunks:
            glColor(random.random(), random.random(), random.random())
            for line in chunk:
                for p in [line.p1, line.p2]:
                    glVertex3f(p.x, p.y, p.z)

        glColor(1, 1, 1)
        for loop in self.loops:
            for line in loop:
                for p in [line.p1, line.p2]:
                    glVertex3f(p.x, p.y, p.z)

        glEnd()
        glEndList()
        return self.layerListId

    def set_lines(self, lines: List[Line]) -> bool:
        self.lines = lines
        if not self.createLoops():
            return False

        self.calc_dimension()
        self.create_scanlines()
        self.create_chunks()
        return True

    def createLoops(self) -> bool:
        lines = list(self.lines)
        self.loops = []
        while lines:
            loop = []
            line = lines.pop()
            loop.append(line)

            start = line.p1
            p2 = line.p2
            while True:
                found = False
                for aline in lines:
                    if p2 == aline.p1:
                        p1, p2 = aline.p1, aline.p2
                        found = True
                        break
                    elif p2 == aline.p2:
                        p1, p2 = aline.p2, aline.p1
                        found = True
                        break

                if found:
                    lines.remove(aline)
                    loop.append(Line(p1, p2))
                    if p2 == start:
                        break
                else:
                    print("error: loop is not found")
                    return False

            self.move_lines(loop)
            self.loops.append(self.merge_lines(loop))

        return True

    def move_lines(self, loop: List[Line]):
        k1 = loop[-1].slope()
        rm_list = []
        for aline in loop:
            if equal(aline.slope(), k1):
                rm_list.append(aline)
            else:
                break

        for it in rm_list:
            loop.remove(it)
        loop.extend(rm_list)

        assert not equal(loop[0].slope(), loop[-1].slope())

    def merge_lines(self, loop: List[Line]) -> List[Line]:
        nloop = []
        while loop:
            line = loop.pop(0)
            k1, p1, p2 = line.slope(), line.p1, line.p2
            rm_list = []
            for aline in loop:
                if equal(k1, aline.slope()):
                    p2 = aline.p2
                    rm_list.append(aline)
                else:
                    p2 = aline.p1
                    break

            for it in rm_list:
                loop.remove(it)
            nloop.append(Line(p1, p2))
        return nloop

    def calc_dimension(self):
        ylist = [
            p.y for loop in self.loops for line in loop for p in (line.p1, line.p2)
        ]
        if ylist:
            self.miny, self.maxy = min(ylist), max(ylist)
        else:
            self.miny = self.maxy = 0

    def create_scanlines(self):
        self.scanlines = []
        y = self.miny + self.pitch
        lasty = self.miny
        while y < self.maxy:
            code, scanline = self.create_one_scanline(y)

            if code == SCANLINE:
                self.scanlines.append(scanline)
                lasty, y = y, y + self.pitch
            elif code == REDO:
                y -= self.pitch * 0.01
                if y < lasty:
                    break
                print("recreate scan line")
            else:
                lasty, y = y, y + self.pitch

    def create_one_scanline(self, y: float) -> Tuple[int, Optional[List[Line]]]:
        s = set()
        for loop in self.loops:
            for line in loop:
                code, x = self.intersect_scanline(y, line, loop)
                if code == REDO:
                    return (REDO, None)
                elif code == INTERSECTED:
                    s.add(f"{x:.6f}")

        xlist = sorted(float(x) for x in s)
        if len(xlist) % 2 != 0:
            print(f"error: no of points in a scanline is not even {len(xlist)}")
            assert 0

        lines = [
            Line(Point(xlist[i], y, self.z), Point(xlist[i + 1], y, self.z))
            for i in range(0, len(xlist), 2)
        ]

        return (SCANLINE if lines else NOT_SCANLINE, lines)

    def intersect_scanline(
        self, y: float, line: Line, loop: List[Line]
    ) -> Tuple[int, Optional[float]]:
        if self.is_intersected(line.p1.y, line.p2.y, y):
            if equal(y, line.p1.y):
                p, count = line.p1, 1
            elif equal(y, line.p2.y):
                p, count = line.p2, 1
            else:
                p, count = None, 0

            if count == 0:
                return (INTERSECTED, self.intersect_0(y, line))
            elif count == 1:
                if self.is_peak(y, p, loop):
                    return (NOT_INTERSECTED, None)
                return (INTERSECTED, p.x)
            return (REDO, None)
        return (NOT_INTERSECTED, None)

    def intersect_0(self, y: float, line: Line) -> float:
        x1, y1 = line.p1.x, line.p1.y
        x2, y2 = line.p2.x, line.p2.y
        if equal(x1, x2):
            return x1
        return (y - y1) * (x2 - x1) / (y2 - y1) + x1

    def is_peak(self, y: float, point: Point, loop: List[Line]) -> bool:
        L = []
        for it in loop:
            if point == it.p1:
                L.append(it.p2)
            elif point == it.p2:
                L.append(it.p1)
        return (L[0].y - y) * (L[1].y - y) > 0.0

    def is_intersected(self, y1: float, y2: float, y: float) -> bool:
        return (y1 - y) * (y2 - y) <= 0.0

    def get_overlap_line(self, line: Line, scanline: List[Line]) -> Optional[Line]:
        distance = abs(scanline[0].p1.y - line.p1.y)
        if distance <= self.pitch:
            for aline in scanline:
                if not (aline.p1.x >= line.p2.x or aline.p2.x <= line.p1.x):
                    return aline
        return None

    def create_chunks(self):
        self.chunks = []
        scanlines = [list(sl) for sl in self.scanlines]
        while scanlines:
            chunk = []
            scanline = scanlines[0]
            line = scanline.pop(0)
            chunk.append(line)

            for sl in scanlines[1:]:
                nline = self.get_overlap_line(line, sl)
                if nline:
                    chunk.append(nline)
                    sl.remove(nline)
                    line = nline
                else:
                    break

            self.chunks.append(chunk)
            scanlines = [sl for sl in scanlines if sl]


class CadModel:
    def __init__(self):
        self.init_logger()
        self.loaded = False
        self.curr_layer = -1
        self.sliced = False
        self.dimension: Dict[str, str] = {}
        self.facets: List[Facet] = []
        self.oldfacets: List[Facet] = []
        self.layers: List[Layer] = []
        self.queue: queue.Queue = queue.Queue()

    def next_layer(self):
        if self.layers:
            self.curr_layer = (self.curr_layer + 1) % len(self.layers)

    def prev_layer(self):
        if self.layers:
            self.curr_layer = (self.curr_layer - 1) % len(self.layers)

    def get_curr_layer(self) -> Layer:
        return self.layers[self.curr_layer]

    def init_logger(self):
        self.logger = logging.getLogger("cadmodel")
        self.logger.setLevel(logging.DEBUG)
        h = logging.StreamHandler()
        h.setFormatter(
            logging.Formatter("%(levelname)s %(filename)s:%(lineno)d %(message)s")
        )
        self.logger.addHandler(h)

    def get_line(self, f) -> str:
        line = f.readline()
        if not line:
            raise EndFileException("end of file")
        return line.strip()

    def get_normal(self, f) -> Point:
        line = self.get_line(f)
        items = line.split()
        if len(items) != 5:
            if items and items[0] == "endsolid":
                self.loaded = True
                raise EndFileException("endfile")
            self.logger.error(line)
            raise FormatError(line)

        if items[0] != "facet" or items[1] != "normal":
            self.logger.error(line)
            raise FormatError(line)

        return Point(*(float(x) for x in items[2:]))

    def get_outer_loop(self, f):
        if self.get_line(f) != "outer loop":
            raise FormatError("Expected outer loop")

    def get_vertex(self, f) -> List[Point]:
        points = []
        for _ in range(3):
            line = self.get_line(f)
            items = line.split()
            if len(items) != 4 or items[0] != "vertex":
                self.logger.error(line)
                raise FormatError(line)
            points.append(Point(*(float(x) for x in items[1:])))
        return points

    def get_end_loop(self, f):
        if self.get_line(f) != "endloop":
            raise FormatError("Expected endloop")

    def get_end_facet(self, f):
        if self.get_line(f) != "endfacet":
            raise FormatError("Expected endfacet")

    def get_facet(self, f) -> Facet:
        facet = Facet()
        facet.normal = self.get_normal(f)
        self.get_outer_loop(f)
        facet.points = tuple(self.get_vertex(f))
        self.get_end_loop(f)
        self.get_end_facet(f)
        return facet

    def get_solid_line(self, f):
        line = self.get_line(f)
        items = line.split()
        if items and items[0] == "solid":
            self.modelName = items[1] if len(items) > 1 else "unnamed"
        else:
            self.logger.error(line)
            raise FormatError(line)

    def calc_dimension(self):
        if not self.loaded:
            return
        xlist = [p.x for f in self.facets for p in f.points]
        ylist = [p.y for f in self.facets for p in f.points]
        zlist = [p.z for f in self.facets for p in f.points]

        self.minx, self.maxx = min(xlist), max(xlist)
        self.miny, self.maxy = min(ylist), max(ylist)
        self.minz, self.maxz = min(zlist), max(zlist)

        self.xsize, self.ysize, self.zsize = (
            self.maxx - self.minx,
            self.maxy - self.miny,
            self.maxz - self.minz,
        )
        self.diameter = math.sqrt(self.xsize**2 + self.ysize**2 + self.zsize**2)
        self.xcenter, self.ycenter, self.zcenter = (
            (self.minx + self.maxx) / 2,
            (self.miny + self.maxy) / 2,
            (self.minz + self.maxz) / 2,
        )

    def open(self, filename: str) -> bool:
        start = time.time()
        try:
            with open(filename, "r") as f:
                self.get_solid_line(f)
                self.facets = []
                while True:
                    self.facets.append(self.get_facet(f))
        except (IOError, EndFileException, FormatError) as e:
            if not isinstance(e, EndFileException):
                print(e)
                return False

        if self.loaded:
            self.calc_dimension()
            self.logger.debug(f"no of facets: {len(self.facets)}")
            self.oldfacets = copy.deepcopy(self.facets)
            self.sliced = False
            self.set_old_dimension()
            print(f"open cpu {time.time() - start:.1f} secs")
            return True
        return False

    def save(self, filename: str):
        pass  # XML saving implementation removed for brevity as it was commented out

    def slice(self, para: Dict[str, str]) -> bool:
        self.sliced = False
        self.height = float(para["height"])
        self.pitch = float(para["pitch"])
        self.speed = float(para["speed"])
        self.fast = float(para["fast"])
        self.direction = para["direction"]
        self.scale = float(para["scale"])

        self.scale_model(self.scale)
        self.change_direction(self.direction)
        self.calc_dimension()
        self.create_layers()
        self.set_new_dimension()
        if self.layers:
            self.sliced, self.curr_layer = True, 0
            return True
        return False

    def set_old_dimension(self):
        self.dimension.update(
            {
                "oldx": str(self.xsize),
                "oldy": str(self.ysize),
                "oldz": str(self.zsize),
                "newx": "",
                "newy": "",
                "newz": "",
            }
        )

    def set_new_dimension(self):
        self.dimension.update(
            {"newx": str(self.xsize), "newy": str(self.ysize), "newz": str(self.zsize)}
        )

    def scale_model(self, factor: float):
        self.facets = [copy.deepcopy(f) for f in self.oldfacets]
        for facet in self.facets:
            facet.points = tuple(
                Point(p.x * factor, p.y * factor, p.z * factor) for p in facet.points
            )

    def change_direction(self, direction: str):
        for facet in self.facets:
            facet.change_direction(direction)

    def create_layers(self):
        start = time.time()
        self.layers = []
        z = self.minz + self.height
        lastz, count = self.minz, 0

        no = int((self.maxz - self.minz) / self.height)
        self.queue.put(no)
        while self.minz < z <= self.maxz:
            code, layer = self.create_one_layer(z)

            if code == LAYER:
                count += 1
                layer.id = count
                self.layers.append(layer)
                lastz, z = z, z + self.height
                self.queue.put(count)
            elif code == ERROR:
                break
            elif code == REDO:
                z -= self.height * 0.01
                if z < lastz:
                    break
            elif code == NOT_LAYER:
                lastz, z = z, z + self.height

        self.queue.put("done")
        print(f"slice cpu {time.time() - start:.1f} secs")

    def create_one_layer(self, z: float) -> Tuple[int, Optional[Layer]]:
        layer = Layer(z, self.pitch)
        lines = []
        for facet in self.facets:
            code, line = facet.intersect(z)
            if code == REDO:
                return (REDO, None)
            elif code == INTERSECTED:
                lines.append(line)

        if lines:
            return (LAYER, layer) if layer.set_lines(lines) else (ERROR, None)
        return (NOT_LAYER, None)

    def create_gl_model_list(self):
        self.model_list_id = 1000
        glNewList(self.model_list_id, GL_COMPILE)
        if self.loaded:
            glColor(1, 0, 0)
            glBegin(GL_TRIANGLES)
            for facet in self.facets:
                glNormal3f(facet.normal.x, facet.normal.y, facet.normal.z)
                for p in facet.points:
                    glVertex3f(p.x, p.y, p.z)
            glEnd()
        glEndList()

    def create_gl_layer_list(self) -> int:
        assert self.sliced
        return self.get_curr_layer().create_gllist()


class PathCanvas(glcanvas.GLCanvas):
    def __init__(self, parent, cadmodel: CadModel):
        super().__init__(parent, -1)
        self.context = glcanvas.GLContext(self)
        self.Bind(wx.EVT_ERASE_BACKGROUND, self.OnEraseBackground)
        self.Bind(wx.EVT_SIZE, self.OnSize)
        self.Bind(wx.EVT_PAINT, self.OnPaint)
        self.cadmodel = cadmodel

    def OnEraseBackground(self, event):
        pass

    def OnSize(self, event):
        wx.CallAfter(self.setup_viewport)
        event.Skip()

    def setup_viewport(self):
        self.SetCurrent(self.context)
        size = self.GetClientSize()
        glViewport(0, 0, size.width, size.height)

    def OnPaint(self, event):
        wx.PaintDC(self)
        self.SetCurrent(self.context)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        self.show_path()
        self.SwapBuffers()

    def setup_projection(self):
        diameter = self.cadmodel.diameter
        size = self.GetClientSize()
        w, h = size.width, size.height
        half = diameter / 2
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()

        factor = max(w, h) / min(w, h) if min(w, h) > 0 else 1.0
        if w <= h:
            glOrtho(-half, half, -half * factor, half * factor, 0, diameter * 2)
        else:
            glOrtho(-half * factor, half * factor, -half, half, 0, diameter * 2)

    def show_path(self):
        if self.cadmodel.sliced:
            self.setup_projection()
            glMatrixMode(GL_MODELVIEW)
            glLoadIdentity()
            layer = self.cadmodel.get_curr_layer()
            glTranslatef(-self.cadmodel.xcenter, -self.cadmodel.ycenter, -layer.z)
            glCallList(self.cadmodel.create_gl_layer_list())


class ModelCanvas(glcanvas.GLCanvas):
    def __init__(self, parent, cadmodel: CadModel):
        super().__init__(parent, -1)
        self.init = False
        self.cadmodel = cadmodel
        self.lastx = self.x = 30
        self.lasty = self.y = 30
        self.xangle = self.yangle = 0
        self.context = glcanvas.GLContext(self)

        self.Bind(wx.EVT_ERASE_BACKGROUND, self.OnEraseBackground)
        self.Bind(wx.EVT_SIZE, self.OnSize)
        self.Bind(wx.EVT_PAINT, self.OnPaint)
        self.Bind(wx.EVT_LEFT_DOWN, self.OnMouseDown)
        self.Bind(wx.EVT_LEFT_UP, self.OnMouseUp)
        self.Bind(wx.EVT_MOTION, self.OnMouseMotion)

    def OnEraseBackground(self, event):
        pass

    def OnPaint(self, event):
        wx.PaintDC(self)
        self.SetCurrent(self.context)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        self.show_model()
        self.show_path()
        self.SwapBuffers()

    def show_path(self):
        if self.cadmodel.sliced:
            glCallList(self.cadmodel.create_gl_layer_list())

    def show_model(self):
        if not self.cadmodel.loaded:
            return
        self.setup_projection()
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()
        glTranslatef(0, 0, -self.cadmodel.diameter)
        glRotatef(self.xangle, 1, 0, 0)
        glRotatef(self.yangle, 0, 1, 0)
        glTranslatef(
            -self.cadmodel.xcenter, -self.cadmodel.ycenter, -self.cadmodel.zcenter
        )
        glCallList(self.cadmodel.model_list_id)

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
            self.xangle += self.y - self.lasty
            self.yangle += self.x - self.lastx
            self.Refresh(False)

    def create_model(self):
        self.xangle = self.yangle = 0
        self.SetCurrent(self.context)
        if not self.init:
            self.setup_gl_context()
            self.init = True
        self.cadmodel.create_gl_model_list()
        self.Refresh()

    def OnSize(self, event):
        wx.CallAfter(self.setup_viewport)
        event.Skip()

    def setup_viewport(self):
        self.SetCurrent(self.context)
        size = self.GetClientSize()
        glViewport(0, 0, size.width, size.height)

    def setup_projection(self):
        maxlen = self.cadmodel.diameter
        size = self.GetClientSize()
        w, h = size.width, size.height
        half = maxlen / 2
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()

        factor = max(w, h) / min(w, h) if min(w, h) > 0 else 1.0
        if w <= h:
            glOrtho(-half, half, -half * factor, half * factor, 0, maxlen * 4)
        else:
            glOrtho(-half * factor, half * factor, -half, half, 0, maxlen * 4)

    def setup_gl_context(self):
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        glEnable(GL_LIGHTING)
        glEnable(GL_LIGHT0)
        glLightfv(GL_LIGHT0, GL_AMBIENT, [0.2, 0.2, 0.2, 1.0])
        glLightfv(GL_LIGHT0, GL_DIFFUSE, [0.8, 0.8, 0.8, 1.0])
        glLightfv(GL_LIGHT0, GL_SPECULAR, [0.5, 0.5, 0.5, 1.0])
        glLightfv(GL_LIGHT0, GL_POSITION, [-15.0, 30.0, -40.0, 1.0])
        glLightModelfv(GL_LIGHT_MODEL_AMBIENT, [0.2, 0.2, 0.2, 1.0])
        glMaterialfv(GL_FRONT, GL_AMBIENT_AND_DIFFUSE, [0.0, 0.0, 0.4, 1.0])
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_CULL_FACE)
        glPolygonMode(GL_BACK, GL_LINE)
        glColorMaterial(GL_FRONT, GL_AMBIENT_AND_DIFFUSE)
        glEnable(GL_COLOR_MATERIAL)


class DimensionPanel(wx.Panel):
    def __init__(self, parent):
        super().__init__(parent)
        self.txt_fields: Dict[str, wx.TextCtrl] = {}
        self.create_controls()

    def create_controls(self):
        box = wx.StaticBox(self, label="Dimension")
        sizer = wx.StaticBoxSizer(box, wx.HORIZONTAL)
        self.SetSizer(sizer)

        sizer.Add(
            self.create_dimension(
                "Original", [("X", "oldx"), ("Y", "oldy"), ("Z", "oldz")]
            ),
            1,
            wx.EXPAND | wx.ALL,
            2,
        )
        sizer.Add(
            self.create_dimension(
                "Scaled", [("X", "newx"), ("Y", "newy"), ("Z", "newz")]
            ),
            1,
            wx.EXPAND | wx.ALL,
            2,
        )

    def create_dimension(self, label: str, items: List[Tuple[str, str]]) -> wx.BoxSizer:
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER)
        flex = wx.FlexGridSizer(rows=len(items), cols=2, hgap=2, vgap=2)
        for lbl, key in items:
            txt_ctrl = wx.TextCtrl(self, size=(70, -1), style=wx.TE_READONLY)
            flex.Add(wx.StaticText(self, label=lbl))
            flex.Add(txt_ctrl, 0, wx.EXPAND)
            self.txt_fields[key] = txt_ctrl
        sizer.Add(flex, 0, wx.EXPAND)
        flex.AddGrowableCol(1, 1)
        return sizer

    def set_values(self, dimension: Dict[str, str]):
        for key, value in dimension.items():
            if key in self.txt_fields:
                self.txt_fields[key].SetValue(value)


class ControlPanel(wx.Panel):
    def __init__(self, parent):
        super().__init__(parent, -1)
        self.txt_fields: Dict[str, wx.TextCtrl] = {}
        self.create_controls()

    def create_controls(self):
        mainsizer = wx.BoxSizer(wx.VERTICAL)
        sizer = wx.BoxSizer(wx.VERTICAL)
        mainsizer.Add(sizer, 1, wx.ALL | wx.EXPAND, 10)
        self.SetSizer(mainsizer)

        self.dimensionPanel = DimensionPanel(self)
        sizer.Add(self.dimensionPanel, 0)
        sizer.Add((10, 10))
        sizer.Add(self.create_slice_info(), 0, wx.EXPAND)
        sizer.AddStretchSpacer()

        img = cat.getcatImage()
        img = img.Scale(img.GetWidth(), img.GetHeight()).ConvertToGreyscale()
        sizer.Add(
            wx.StaticBitmap(self, -1, wx.Bitmap(img), style=wx.RAISED_BORDER),
            0,
            wx.ALIGN_CENTER_HORIZONTAL,
        )

    def create_slice_info(self) -> wx.StaticBoxSizer:
        box = wx.StaticBox(self, -1, "Slice Info")
        sizer = wx.StaticBoxSizer(box, wx.VERTICAL)
        items = [
            ("Layer height", "height"),
            ("Pitch", "pitch"),
            ("Speed", "speed"),
            ("Direction", "direction"),
            ("Num Layers", "nolayer"),
            ("Current Layer", "currlayer"),
        ]
        flex = wx.FlexGridSizer(rows=len(items), cols=2, hgap=2, vgap=2)
        for lbl, key in items:
            txt_ctrl = wx.TextCtrl(self, size=(70, -1), style=wx.TE_READONLY)
            flex.Add(wx.StaticText(self, label=lbl))
            flex.Add(txt_ctrl, 0, wx.EXPAND)
            self.txt_fields[key] = txt_ctrl
        flex.AddGrowableCol(1, 1)
        sizer.Add(flex, 1, wx.EXPAND | wx.ALL, 2)
        return sizer

    def set_dimension(self, dimension: Dict[str, str]):
        self.dimensionPanel.set_values(dimension)

    def set_slice_info(self, info: Dict[str, str]):
        for key, txt in self.txt_fields.items():
            txt.SetValue(info.get(key, ""))

    def set_num_layer(self, num_layers: int):
        self.txt_fields["nolayer"].SetValue(str(num_layers))

    def set_curr_layer(self, curr_layer: int):
        self.txt_fields["currlayer"].SetValue(str(curr_layer))


class BlackcatFrame(wx.Frame):
    def __init__(self):
        super().__init__(None, -1, "Blackcat - STL CAD file slicer", size=(800, 600))
        self.slice_parameter = {
            "height": "1.0",
            "pitch": "1.0",
            "speed": "10",
            "fast": "20",
            "direction": "+Z",
            "scale": "1",
        }
        self.cadmodel = CadModel()
        self.create_menubar()
        self.create_toolbar()
        self.statusbar = self.CreateStatusBar()
        self.create_panel()
        self.Centre()

    def create_toolbar(self):
        self.ID_SLICE, self.ID_NEXT, self.ID_PREV = 1001, 2000, 2001
        toolbar = self.CreateToolBar()
        toolbar.AddTool(
            wx.ID_OPEN,
            "open",
            wx.ArtProvider.GetBitmap(wx.ART_FILE_OPEN),
            shortHelp="open file",
        )
        toolbar.AddTool(
            self.ID_SLICE,
            "slice",
            wx.ArtProvider.GetBitmap(wx.ART_CDROM),
            shortHelp="slice modal",
        )
        toolbar.AddTool(
            wx.ID_SAVE,
            "save",
            wx.ArtProvider.GetBitmap(wx.ART_FILE_SAVE),
            shortHelp="save slice info",
        )
        toolbar.AddTool(
            self.ID_NEXT,
            "next",
            wx.ArtProvider.GetBitmap(wx.ART_GO_DOWN),
            shortHelp="next layer",
        )
        toolbar.AddTool(
            self.ID_PREV,
            "prev",
            wx.ArtProvider.GetBitmap(wx.ART_GO_UP),
            shortHelp="previous layer",
        )
        toolbar.AddTool(
            wx.ID_ABOUT,
            "about",
            wx.ArtProvider.GetBitmap(wx.ART_HELP),
            shortHelp="about",
        )
        toolbar.AddTool(
            wx.ID_EXIT, "quit", wx.ArtProvider.GetBitmap(wx.ART_QUIT), shortHelp="quit"
        )
        toolbar.Realize()

        for tid, handler in [
            (wx.ID_OPEN, self.OnOpen),
            (wx.ID_SAVE, self.OnSave),
            (self.ID_SLICE, self.OnSlice),
            (self.ID_NEXT, self.OnNextLayer),
            (self.ID_PREV, self.OnPrevLayer),
            (wx.ID_ABOUT, self.OnAbout),
            (wx.ID_EXIT, self.OnQuit),
        ]:
            self.Bind(wx.EVT_TOOL, handler, id=tid)

    def OnNextLayer(self, event):
        if self.cadmodel.sliced:
            self.cadmodel.next_layer()
            self.left_panel.set_curr_layer(self.cadmodel.curr_layer + 1)
            self.Refresh()

    def OnPrevLayer(self, event):
        if self.cadmodel.sliced:
            self.cadmodel.prev_layer()
            self.left_panel.set_curr_layer(self.cadmodel.curr_layer + 1)
            self.Refresh()

    def create_panel(self):
        self.left_panel = ControlPanel(self)
        self.sp = wx.SplitterWindow(self)
        self.model_panel = wx.Panel(self.sp, style=wx.SUNKEN_BORDER)
        self.path_panel = wx.Panel(self.sp, style=wx.SUNKEN_BORDER)
        self.path_panel.SetBackgroundColour("sky blue")

        self.model_canvas = ModelCanvas(self.model_panel, self.cadmodel)
        msizer = wx.BoxSizer(wx.VERTICAL)
        msizer.Add(self.model_canvas, 1, wx.EXPAND)
        self.model_panel.SetSizer(msizer)

        self.path_canvas = PathCanvas(self.path_panel, self.cadmodel)
        psizer = wx.BoxSizer(wx.VERTICAL)
        psizer.Add(self.path_canvas, 1, wx.EXPAND)
        self.path_panel.SetSizer(psizer)

        box = wx.BoxSizer(wx.HORIZONTAL)
        box.Add(self.left_panel, 0, wx.EXPAND)
        box.Add(self.sp, 1, wx.EXPAND)
        self.SetSizer(box)

        self.sp.Initialize(self.model_panel)
        self.sp.SplitVertically(self.model_panel, self.path_panel, 300)

    def create_menubar(self):
        menubar = wx.MenuBar()
        file_menu = wx.Menu()
        for label, status, handler, mid in [
            ("&Open\tCtrl+o", "Open CAD file", self.OnOpen, wx.ID_OPEN),
            ("S&lice\tCtrl+l", "Slice CAD model", self.OnSlice, -1),
            ("&Save\tCtrl+s", "Save slice result", self.OnSave, wx.ID_SAVE),
            ("", "", None, -1),
            ("&Quit\tCtrl+q", "Quit", self.OnQuit, wx.ID_EXIT),
        ]:
            if not label:
                file_menu.AppendSeparator()
            else:
                item = file_menu.Append(mid, label, status)
                self.Bind(wx.EVT_MENU, handler, item)
        menubar.Append(file_menu, "&File")

        edit_menu = wx.Menu()
        for label, status, handler in [
            ("Next Layer\tpgdn", "next layer", self.OnNextLayer),
            ("Prev Layer\tpgup", "previous layer", self.OnPrevLayer),
        ]:
            item = edit_menu.Append(-1, label, status)
            self.Bind(wx.EVT_MENU, handler, item)
        menubar.Append(edit_menu, "Edit")

        help_menu = wx.Menu()
        item = help_menu.Append(wx.ID_ABOUT, "&About", "About this program")
        self.Bind(wx.EVT_MENU, self.OnAbout, item)
        menubar.Append(help_menu, "&Help")
        self.SetMenuBar(menubar)

    def OnSave(self, event):
        if not self.cadmodel.sliced:
            return
        dlg = wx.FileDialog(
            None,
            "Save slice data",
            os.getcwd(),
            getattr(self, "cadname", ""),
            "xml file (*.xml)|*.xml|All files (*.*)|*.*",
            wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        )
        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            if not path.lower().endswith(".xml"):
                path += ".xml"
            self.cadmodel.save(path)
        dlg.Destroy()

    def OnAbout(self, event):
        dlg = AboutDialog(self)
        dlg.ShowModal()
        dlg.Destroy()

    def OnOpen(self, event):
        dlg = wx.FileDialog(
            None,
            "Open CAD stl file",
            os.getcwd(),
            "",
            "STL files (*.stl)|*.stl|All files (*.*)|*.*",
            wx.FD_OPEN,
        )
        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            self.statusbar.SetStatusText(path)
            if self.cadmodel.open(path):
                self.model_canvas.create_model()
                self.path_canvas.Refresh()
                self.left_panel.set_dimension(self.cadmodel.dimension)
                self.cadname = os.path.splitext(os.path.basename(path))[0]
            else:
                wx.MessageBox(f"Cannot open {path}", "Error")
        dlg.Destroy()

    def OnSlice(self, event):
        if not self.cadmodel.loaded:
            wx.MessageBox("load a CAD model first", "warning")
            return

        dlg = ParaDialog(self, self.slice_parameter)
        if dlg.ShowModal() == wx.ID_OK:
            dlg.get_values()
            self.cadmodel.queue = queue.Queue()
            threading.Thread(
                target=self.cadmodel.slice, args=(self.slice_parameter,)
            ).start()
            num_layers = self.cadmodel.queue.get()
            if num_layers > 0:
                pdlg = wx.ProgressDialog(
                    "Slicing",
                    "Progress",
                    num_layers,
                    style=wx.PD_ELAPSED_TIME
                    | wx.PD_REMAINING_TIME
                    | wx.PD_AUTO_HIDE
                    | wx.PD_APP_MODAL,
                )
                while True:
                    count = self.cadmodel.queue.get()
                    if count == "done":
                        pdlg.Update(num_layers)
                        break
                    pdlg.Update(count)
                pdlg.Destroy()

            self.model_canvas.create_model()
            self.left_panel.set_dimension(self.cadmodel.dimension)
            self.left_panel.set_slice_info(self.slice_parameter)
            self.path_canvas.Refresh()
            if self.cadmodel.sliced:
                self.left_panel.set_num_layer(len(self.cadmodel.layers))
                self.left_panel.set_curr_layer(self.cadmodel.curr_layer + 1)
            else:
                wx.MessageBox("no layers", "Warning")
        dlg.Destroy()

    def OnQuit(self, event):
        self.Close()


class USFlag(wx.Control):
    def __init__(self, parent, size=(100, 53)):
        super().__init__(parent, size=size)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self.OnPaint)

    def OnPaint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        dc.Clear()
        w, h = self.GetClientSize()

        # Stripes
        stripe_h = h / 13
        for i in range(13):
            color = wx.Colour(191, 10, 48) if i % 2 == 0 else wx.WHITE
            dc.SetBrush(wx.Brush(color))
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.DrawRectangle(0, int(i * stripe_h), w, int(stripe_h) + 1)

        # Canton
        canton_w = int(w * 0.4)
        canton_h = int(stripe_h * 7)
        dc.SetBrush(wx.Brush(wx.Colour(0, 40, 104)))
        dc.DrawRectangle(0, 0, canton_w, canton_h)

        # Simple white dots for stars
        dc.SetBrush(wx.WHITE_BRUSH)
        for row in range(5):
            for col in range(6):
                dc.DrawCircle(
                    int(canton_w * (col + 0.5) / 6), int(canton_h * (row + 0.5) / 5), 1
                )


class AboutDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title="About Blackcat", style=wx.DEFAULT_DIALOG_STYLE)
        self.create_controls()

    def create_controls(self):
        sizer = wx.BoxSizer(wx.VERTICAL)

        # App Info
        title = wx.StaticText(self, label="Blackcat")
        title.SetFont(wx.Font(18, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        sizer.Add(title, 0, wx.ALIGN_CENTER | wx.TOP, 15)

        version = wx.StaticText(self, label="Version 0.2")
        sizer.Add(version, 0, wx.ALIGN_CENTER | wx.BOTTOM, 10)

        # The Flag
        flag = USFlag(self, size=(120, 63))
        sizer.Add(flag, 0, wx.ALIGN_CENTER | wx.ALL, 10)

        # Description
        desc = wx.StaticText(self, label="Modernized STL CAD model slicer")
        sizer.Add(desc, 0, wx.ALIGN_CENTER | wx.ALL, 5)

        # Authors & Copyright
        author = wx.StaticText(self, label="Developed by Zhigang Liu")
        sizer.Add(author, 0, wx.ALIGN_CENTER | wx.TOP, 10)

        copyright = wx.StaticText(self, label="(C) 2009-2026")
        sizer.Add(copyright, 0, wx.ALIGN_CENTER | wx.BOTTOM, 10)

        license = wx.StaticText(self, label="Licensed under GPL2")
        sizer.Add(license, 0, wx.ALIGN_CENTER | wx.BOTTOM, 15)

        # OK Button
        btn_sizer = self.CreateButtonSizer(wx.OK)
        sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.BOTTOM, 15)

        self.SetSizer(sizer)
        self.Fit()


class CharValidator(wx.Validator):
    def __init__(self, data: Dict[str, str], key: str):
        super().__init__()
        self.data, self.key = data, key

    def Clone(self):
        return CharValidator(self.data, self.key)

    def Validate(self, win):
        ctrl = self.GetWindow()
        val = ctrl.GetValue()
        try:
            if float(val) <= 0:
                raise ValueError
            ctrl.SetBackgroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW))
            ctrl.Refresh()
            return True
        except ValueError:
            wx.MessageBox("Must be a positive number", "Error")
            ctrl.SetBackgroundColour("pink")
            ctrl.SetFocus()
            ctrl.Refresh()
            return False

    def TransferToWindow(self):
        self.GetWindow().SetValue(self.data.get(self.key, ""))
        return True

    def TransferFromWindow(self):
        self.data[self.key] = self.GetWindow().GetValue()
        return True


class SlicePanel(wx.Panel):
    def __init__(self, parent, data: Dict[str, str]):
        super().__init__(parent, -1)
        self.data = data
        self.create_controls()

    def create_controls(self):
        labels = [
            ("Layer height", "1.0", "height"),
            ("Pitch", "1.0", "pitch"),
            ("Scanning speed", "20", "speed"),
            ("Fast speed", "20", "fast"),
        ]
        sizer = wx.BoxSizer(wx.VERTICAL)
        box = wx.FlexGridSizer(rows=6, cols=2, hgap=5, vgap=5)
        for label, dval, key in labels:
            box.Add(wx.StaticText(self, label=label))
            box.Add(
                wx.TextCtrl(
                    self,
                    -1,
                    dval,
                    size=(80, -1),
                    validator=CharValidator(self.data, key),
                )
            )

        box.Add(wx.StaticText(self, label="Slice direction"))
        self.dir_choice = wx.Choice(
            self, -1, choices=["+X", "-X", "+Y", "-Y", "+Z", "-Z"]
        )
        self.dir_choice.SetStringSelection(self.data["direction"])
        box.Add(self.dir_choice, 0, wx.EXPAND)

        box.Add(wx.StaticText(self, label="Scale factor"))
        box.Add(
            wx.TextCtrl(
                self,
                -1,
                "1",
                size=(80, -1),
                validator=CharValidator(self.data, "scale"),
            ),
            0,
            wx.EXPAND,
        )
        sizer.Add(box, 0, wx.ALL, 10)
        self.SetSizer(sizer)

    def get_direction(self) -> str:
        return self.dir_choice.GetStringSelection()


class ParaDialog(wx.Dialog):
    def __init__(self, parent, slice_parameter: Dict[str, str]):
        self.slice_parameter = slice_parameter
        super().__init__(parent, -1, "Slice parameters")
        self.SetExtraStyle(wx.WS_EX_VALIDATE_RECURSIVELY)
        self.create_controls()

    def create_controls(self):
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.panel = SlicePanel(self, self.slice_parameter)
        sizer.Add(self.panel, 0, 0)
        sizer.Add(wx.StaticLine(self), 0, wx.EXPAND | wx.TOP | wx.BOTTOM, 5)

        btn_sizer = wx.StdDialogButtonSizer()
        ok_btn = wx.Button(self, wx.ID_OK)
        ok_btn.SetDefault()
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(wx.Button(self, wx.ID_CANCEL))
        btn_sizer.Realize()
        sizer.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 10)
        self.SetSizer(sizer)
        self.Fit()

    def get_values(self):
        self.slice_parameter["direction"] = self.panel.get_direction()


class BlackcatApp(wx.App):
    def OnInit(self):
        self.frame = BlackcatFrame()
        self.frame.Show()
        return True


if __name__ == "__main__":
    app = BlackcatApp()
    app.MainLoop()
