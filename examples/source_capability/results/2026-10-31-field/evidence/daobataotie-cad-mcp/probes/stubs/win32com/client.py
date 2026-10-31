"""Reviewer stub for win32com.client (Linux container; not pywin32)."""
import fakecad


def VARIANT(vt, value):
    return list(value)


def GetActiveObject(progid):
    return fakecad.get_app(progid)


def Dispatch(progid):
    return fakecad.get_app(progid)
