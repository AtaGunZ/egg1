;; AutoLISP (UNTESTED SKETCH): save the drawing and push it to a BIMCheck server. Command: BIMCHECK
(defun c:BIMCHECK (/ dwg cmd)
  (command "_.QSAVE")
  (setq dwg (strcat (getvar "DWGPREFIX") (getvar "DWGNAME")))
  (setq cmd (strcat "curl.exe -s -F \"file=@" dwg "\" http://127.0.0.1:8765/api/projects/REPLACE_WITH_PROJECT_ID/drawing"))
  (startapp "cmd.exe" (strcat "/c " cmd " & pause"))
  (princ)
)
