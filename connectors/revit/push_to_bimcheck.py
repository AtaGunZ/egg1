# pyRevit script (UNTESTED SKETCH): export current model to IFC and push to a BIMCheck server.
# Put in a pyRevit extension as push_to_bimcheck.pushbutton/script.py
import os
import tempfile
import uuid
import urllib2  # IronPython 2.7 inside pyRevit

from Autodesk.Revit.DB import IFCExportOptions, Transaction

SERVER = "http://127.0.0.1:8765"
PROJECT = "REPLACE_WITH_PROJECT_ID"  # create one in the web UI first

doc = __revit__.ActiveUIDocument.Document  # noqa: F821  (provided by pyRevit)
folder = tempfile.mkdtemp()
name = "model.ifc"

opts = IFCExportOptions()
t = Transaction(doc, "BIMCheck IFC export")
t.Start()
doc.Export(folder, name, opts)
t.RollBack()

data = open(os.path.join(folder, name), "rb").read()
b = uuid.uuid4().hex
body = ("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\n"
        "Content-Type: application/octet-stream\r\n\r\n" % (b, name)).encode("utf-8") + data + \
       ("\r\n--%s--\r\n" % b).encode("utf-8")
req = urllib2.Request("%s/api/projects/%s/model" % (SERVER, PROJECT), body,
                      {"Content-Type": "multipart/form-data; boundary=%s" % b})
print(urllib2.urlopen(req).read())
