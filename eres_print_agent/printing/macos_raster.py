"""Render PDF pages to 8-bit gray bitmaps with CoreGraphics, which every Mac
has, so receipts can be sent to the printer as ESC/POS without poppler or
any other extra install."""

from __future__ import annotations

import ctypes
from typing import List, Tuple

_CG = "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
_CF = "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"


class _Rect(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double), ("w", ctypes.c_double), ("h", ctypes.c_double)]


def _libs():
    cg = ctypes.cdll.LoadLibrary(_CG)
    cf = ctypes.cdll.LoadLibrary(_CF)
    vp = ctypes.c_void_p
    cf.CFURLCreateFromFileSystemRepresentation.restype = vp
    cf.CFURLCreateFromFileSystemRepresentation.argtypes = [vp, ctypes.c_char_p, ctypes.c_long, ctypes.c_bool]
    cf.CFRelease.argtypes = [vp]
    cg.CGPDFDocumentCreateWithURL.restype = vp
    cg.CGPDFDocumentCreateWithURL.argtypes = [vp]
    cg.CGPDFDocumentGetNumberOfPages.restype = ctypes.c_size_t
    cg.CGPDFDocumentGetNumberOfPages.argtypes = [vp]
    cg.CGPDFDocumentGetPage.restype = vp
    cg.CGPDFDocumentGetPage.argtypes = [vp, ctypes.c_size_t]
    cg.CGPDFPageGetBoxRect.restype = _Rect
    cg.CGPDFPageGetBoxRect.argtypes = [vp, ctypes.c_int]
    cg.CGPDFDocumentRelease.argtypes = [vp]
    cg.CGColorSpaceCreateDeviceGray.restype = vp
    cg.CGColorSpaceRelease.argtypes = [vp]
    cg.CGBitmapContextCreate.restype = vp
    cg.CGBitmapContextCreate.argtypes = [vp, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_size_t, vp, ctypes.c_uint32]
    cg.CGContextSetGrayFillColor.argtypes = [vp, ctypes.c_double, ctypes.c_double]
    cg.CGContextFillRect.argtypes = [vp, _Rect]
    cg.CGContextScaleCTM.argtypes = [vp, ctypes.c_double, ctypes.c_double]
    cg.CGContextTranslateCTM.argtypes = [vp, ctypes.c_double, ctypes.c_double]
    cg.CGContextDrawPDFPage.argtypes = [vp, vp]
    cg.CGContextSetShouldAntialias.argtypes = [vp, ctypes.c_bool]
    cg.CGContextRelease.argtypes = [vp]
    return cg, cf


def render_pdf_gray(file_path: str, width_px: int) -> List[Tuple[bytes, int, int]]:
    """Every page as (gray bytes top row first, width, height), scaled so the
    page width is `width_px`. Raises RuntimeError if the PDF can't be read."""
    cg, cf = _libs()
    path = file_path.encode("utf-8")
    url = cf.CFURLCreateFromFileSystemRepresentation(None, path, len(path), False)
    if not url:
        raise RuntimeError("Could not open the PDF")
    doc = cg.CGPDFDocumentCreateWithURL(url)
    cf.CFRelease(url)
    if not doc:
        raise RuntimeError("Could not read the PDF")
    space = cg.CGColorSpaceCreateDeviceGray()
    pages: List[Tuple[bytes, int, int]] = []
    try:
        for number in range(1, cg.CGPDFDocumentGetNumberOfPages(doc) + 1):
            page = cg.CGPDFDocumentGetPage(doc, number)
            box = cg.CGPDFPageGetBoxRect(page, 0)  # media box
            if box.w <= 0 or box.h <= 0:
                continue
            scale = width_px / box.w
            height_px = max(1, int(round(box.h * scale)))
            buffer = ctypes.create_string_buffer(width_px * height_px)
            ctx = cg.CGBitmapContextCreate(buffer, width_px, height_px, 8, width_px, space, 0)
            if not ctx:
                raise RuntimeError("Could not create a bitmap")
            try:
                cg.CGContextSetGrayFillColor(ctx, 1.0, 1.0)
                cg.CGContextFillRect(ctx, _Rect(0, 0, width_px, height_px))
                # Hard black/white edges for text and shapes: soft grey edges
                # get dithered into speckles, which break QR codes. Images
                # (a logo) are unaffected and still print as shading.
                cg.CGContextSetShouldAntialias(ctx, False)
                cg.CGContextScaleCTM(ctx, scale, scale)
                cg.CGContextTranslateCTM(ctx, -box.x, -box.y)
                cg.CGContextDrawPDFPage(ctx, page)
            finally:
                cg.CGContextRelease(ctx)
            pages.append((buffer.raw, width_px, height_px))
    finally:
        cg.CGColorSpaceRelease(space)
        cg.CGPDFDocumentRelease(doc)
    return pages
